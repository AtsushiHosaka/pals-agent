"""Trusted post-compilation audit that an elaboration-time exit cannot satisfy.

The candidate compiles to ``Main.olean`` in one process. A later process runs only the fixed program
below: it reads the artifact as data, activates none of the candidate's environment extensions,
replays every candidate constant through the kernel, and reports theorems and transitive axioms with
a nonce created after the candidate exited. A candidate that exits early writes no artifact, and it
never sees the nonce because the nonce does not exist while it runs.

The audit also binds what the candidate claims. ``statement_reference`` rewrites the visible source
with proofs replaced by ``sorry`` and every command that could change a statement from outside its
own text removed. The fixed program elaborates that text over the imports alone and compares it with
the compiled constants, so a hypothesis from ``variable``, a rewriting macro, a local instance or
shadowing notation makes the compiled type differ from the statement a reader sees.
"""

from __future__ import annotations

from dataclasses import dataclass

from pals_agent.models import Diagnostic

ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
AUDIT_FAILED = "lean.trusted_audit_failed"
STATEMENT_MISMATCH = "lean.statement_mismatch"
_THEOREM_PREFIX = "theorem "
_AXIOM_PREFIX = "axiom "
_COMPLETE_PREFIX = "complete "
_BOUND_PREFIX = "bound "
_UNBOUND_PREFIX = "unbound "
_STATEMENT_ERROR_PREFIX = "statement_error "
_STATEMENT_GUIDANCE = (
    "State every hypothesis in the theorem header. Do not rely on `variable`, `include`, local "
    "instances or other commands outside the declaration."
)

TRUSTED_AUDIT_SOURCE = """\
import Lean.Elab.Frontend
import Lean.Replay
import Lean.Util.CollectAxioms
open Lean

unsafe def main (args : List String) : IO UInt32 := do
  let [nonce, olean, reference] := args | return 64
  let (mod, _region) ← readModuleData olean
  enableInitializersExecution
  let env ← importModules mod.imports {} 0 (loadExts := true)
  let mut constants : Std.HashMap Name ConstantInfo := {}
  for name in mod.constNames, info in mod.constants do
    constants := constants.insert name info
  let checked ← env.replay constants
  let names := constants.toList
  let axioms ← Core.CoreM.toIO' (ctx := { fileName := "<audit>", fileMap := default })
    (s := { env := checked }) do
      let mut found : NameSet := {}
      for (name, _) in names do
        for axiomName in ← collectAxioms name do
          found := found.insert axiomName
      return found
  for (name, info) in names do
    if info.isTheorem then
      IO.println s!"theorem {name}"
  for axiomName in axioms do
    IO.println s!"axiom {axiomName}"
  let input ← IO.FS.readFile reference
  -- The parser reports an error for input with no command, such as a lone typeless `example`.
  let (restated, messages) ←
    if input.all Char.isWhitespace then pure (env, {}) else Lean.Elab.process input env {}
  for message in messages.toList do
    if message.severity == .error then
      let text := (← message.data.toString).replace "\\n" " "
      IO.println s!"statement_error {text}"
  for (name, info) in names do
    if let some other := restated.find? (privateToUserName name) then
      let levels := info.levelParams.map mkLevelParam
      let sameType := info.levelParams.length == other.levelParams.length &&
        info.type == other.type.instantiateLevelParams other.levelParams levels
      let sameValue := match info, other with
        | .defnInfo left, .defnInfo right =>
          "pals_audit_".isPrefixOf name.toString ||
            left.value == right.value.instantiateLevelParams right.levelParams levels
        | _, _ => true
      IO.println s!"{if sameType && sameValue then "bound" else "unbound"} {name}"
  IO.println s!"complete {nonce}"
  return 0
"""


@dataclass(frozen=True, slots=True)
class AuditReport:
    theorems: tuple[str, ...]
    axioms: tuple[str, ...]
    bound: tuple[str, ...] = ()
    unbound: tuple[str, ...] = ()
    statement_errors: tuple[str, ...] = ()


def parse_audit_report(stdout: str, nonce: str) -> AuditReport | None:
    """Return the report only when it is closed by exactly this request's nonce."""
    lines = stdout.splitlines()
    if not lines or lines[-1] != _COMPLETE_PREFIX + nonce:
        return None
    theorems: list[str] = []
    axioms: list[str] = []
    bound: list[str] = []
    unbound: list[str] = []
    statement_errors: list[str] = []
    for line in lines[:-1]:
        if line.startswith(_THEOREM_PREFIX):
            theorems.append(line.removeprefix(_THEOREM_PREFIX))
        elif line.startswith(_AXIOM_PREFIX):
            axioms.append(line.removeprefix(_AXIOM_PREFIX))
        elif line.startswith(_BOUND_PREFIX):
            bound.append(line.removeprefix(_BOUND_PREFIX))
        elif line.startswith(_UNBOUND_PREFIX):
            unbound.append(line.removeprefix(_UNBOUND_PREFIX))
        elif line.startswith(_STATEMENT_ERROR_PREFIX):
            statement_errors.append(line.removeprefix(_STATEMENT_ERROR_PREFIX))
        else:
            return None
    return AuditReport(
        tuple(theorems), tuple(axioms), tuple(bound), tuple(unbound), tuple(statement_errors)
    )


def audit_failure(message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=AUDIT_FAILED, message=message)


def statement_mismatch(detail: str) -> Diagnostic:
    return Diagnostic(
        severity="error",
        code=STATEMENT_MISMATCH,
        message=f"{detail} {_STATEMENT_GUIDANCE}",
    )


def audit_diagnostics(report: AuditReport, declared_theorems: tuple[str, ...]) -> list[Diagnostic]:
    """Apply axiom, declaration and statement policy; no errors means the audit passed."""
    diagnostics: list[Diagnostic] = []
    disallowed = sorted(set(report.axioms) - ALLOWED_AXIOMS)
    if disallowed:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="lean.disallowed_axiom",
                message="Lean proof depends on disallowed axioms: " + ", ".join(disallowed) + ".",
            )
        )
    missing = [
        name
        for name in declared_theorems
        if not any(_names_declaration(reported, name) for reported in report.theorems)
    ]
    if missing:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="lean.undeclared_theorem",
                message="Compiled module lacks declared theorems: " + ", ".join(missing) + ".",
            )
        )
    unbound = sorted(
        {
            *report.unbound,
            *(
                name
                for name in declared_theorems
                if name not in missing
                and not any(_names_declaration(bound, name) for bound in report.bound)
            ),
        }
    )
    if report.statement_errors:
        diagnostics.append(
            statement_mismatch(
                "A statement does not elaborate on its own: " + report.statement_errors[0][:300]
            )
        )
    elif unbound:
        diagnostics.append(
            statement_mismatch(
                "The compiled type differs from the written statement of: "
                + ", ".join(unbound)
                + "."
            )
        )
    return diagnostics


def _names_declaration(reported: str, declared: str) -> bool:
    return reported == declared or reported.endswith("." + declared)
