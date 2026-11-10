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
# Only a profile whose audit program checks statement origins ever prints this line.
_UNTRUSTED_STATEMENT_PREFIX = "untrusted_statement "
UNTRUSTED_STATEMENT_LIBRARY = "lean.statement_uses_untrusted_library"
# Only a profile that RECORDS (rather than rejects) unreviewed statement constants prints these.
_TRUST_RECORDED = "trust_recorded"
_STATEMENT_ROOT_PREFIX = "statement_root "
_FRONTIER_STATEMENT_PREFIX = "frontier_statement "
_PROOF_ROOT_PREFIX = "proof_root "
_FRONTIER_DUPLICATE_PREFIX = "frontier_duplicate "
TRUST_LEVEL_DIAGNOSTIC = "lean.library_trust"
FRONTIER_DUPLICATE_DIAGNOSTIC = "lean.frontier_duplicate_definition"
FRONTIER_ROOT = "StacksFrontier"
CORE_ROOT = "StacksCore"
# The trust levels a recording profile attaches to a verified result, weakest claim last.
TRUST_MATHLIB = "mathlib"
TRUST_CORE = "core"
TRUST_FRONTIER_PROOF = "frontier_proof"
TRUST_FRONTIER_STATEMENT = "frontier_statement"
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
    untrusted_statements: tuple[str, ...] = ()
    # Filled only by a recording profile (see ``trust_recorded``). ``statement_roots`` and
    # ``proof_roots`` hold ``"<theorem> <root>"``, ``frontier_statements`` holds
    # ``"<theorem> <constant> <module>"`` and ``frontier_duplicates`` holds
    # ``"<frontier constant> <other constant> <reason>"``.
    trust_recorded: bool = False
    statement_roots: tuple[str, ...] = ()
    frontier_statements: tuple[str, ...] = ()
    proof_roots: tuple[str, ...] = ()
    frontier_duplicates: tuple[str, ...] = ()


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
    untrusted_statements: list[str] = []
    trust_recorded = False
    statement_roots: list[str] = []
    frontier_statements: list[str] = []
    proof_roots: list[str] = []
    frontier_duplicates: list[str] = []
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
        elif line.startswith(_UNTRUSTED_STATEMENT_PREFIX):
            untrusted_statements.append(line.removeprefix(_UNTRUSTED_STATEMENT_PREFIX))
        elif line == _TRUST_RECORDED:
            trust_recorded = True
        elif line.startswith(_STATEMENT_ROOT_PREFIX):
            statement_roots.append(line.removeprefix(_STATEMENT_ROOT_PREFIX))
        elif line.startswith(_FRONTIER_STATEMENT_PREFIX):
            frontier_statements.append(line.removeprefix(_FRONTIER_STATEMENT_PREFIX))
        elif line.startswith(_PROOF_ROOT_PREFIX):
            proof_roots.append(line.removeprefix(_PROOF_ROOT_PREFIX))
        elif line.startswith(_FRONTIER_DUPLICATE_PREFIX):
            frontier_duplicates.append(line.removeprefix(_FRONTIER_DUPLICATE_PREFIX))
        else:
            return None
    return AuditReport(
        tuple(theorems),
        tuple(axioms),
        tuple(bound),
        tuple(unbound),
        tuple(statement_errors),
        tuple(untrusted_statements),
        trust_recorded,
        tuple(statement_roots),
        tuple(frontier_statements),
        tuple(proof_roots),
        tuple(frontier_duplicates),
    )


def audit_failure(message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=AUDIT_FAILED, message=message)


def statement_mismatch(detail: str) -> Diagnostic:
    return Diagnostic(
        severity="error",
        code=STATEMENT_MISMATCH,
        message=f"{detail} {_STATEMENT_GUIDANCE}",
    )


def audit_diagnostics(
    report: AuditReport,
    declared_theorems: tuple[str, ...],
    *,
    allowed_axioms: frozenset[str] = ALLOWED_AXIOMS,
    unreviewed_roots: tuple[str, ...] = (FRONTIER_ROOT,),
    reviewed_roots: tuple[str, ...] = (CORE_ROOT,),
) -> list[Diagnostic]:
    """Apply axiom, declaration and statement policy; no errors means the audit passed.

    ``allowed_axioms`` is the profile's axiom allow-list (a manifest may narrow the default, never
    widen it). ``unreviewed_roots`` and ``reviewed_roots`` are the library roots the profile's
    manifest declares, which decide the trust level a recording profile reports.
    """
    if not allowed_axioms <= ALLOWED_AXIOMS:
        raise ValueError("an axiom allow-list can only be narrowed")
    diagnostics: list[Diagnostic] = []
    disallowed = sorted(set(report.axioms) - allowed_axioms)
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
    if report.untrusted_statements:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code=UNTRUSTED_STATEMENT_LIBRARY,
                message=(
                    "A statement depends on a constant from an unreviewed library "
                    "(statement constant, library module): "
                    + "; ".join(item[:200] for item in report.untrusted_statements[:4])
                    + ". Only proofs may use it."
                ),
            )
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
    if report.trust_recorded and "exhausted" in {_last_word(item) for item in report.proof_roots}:
        diagnostics.append(
            audit_failure("The proof's library use could not be traced completely.")
        )
    if not any(diagnostic.severity == "error" for diagnostic in diagnostics):
        diagnostics.extend(_trust_diagnostics(report, unreviewed_roots, reviewed_roots))
    return diagnostics


def _last_word(item: str) -> str:
    return item.rsplit(" ", 1)[-1]


def trust_level(
    report: AuditReport,
    unreviewed_roots: tuple[str, ...] = (FRONTIER_ROOT,),
    reviewed_roots: tuple[str, ...] = (CORE_ROOT,),
) -> str | None:
    """The trust level of what a recording profile verified; ``None`` if nothing was recorded.

    ``frontier_statement`` means a statement reaches a ``StacksFrontier`` definition, which an AI
    wrote and no human reviewed. ``frontier_proof`` means only the proof uses the Frontier. An
    exhausted walk, whose coverage is unknown, is never reported as a lower level. Which roots are
    unreviewed (``frontier_*``) and which reviewed (``core``) comes from the profile's manifest.
    """
    if not report.trust_recorded:
        return None
    statement_roots = {_last_word(item) for item in report.statement_roots}
    proof_roots = {_last_word(item) for item in report.proof_roots}
    unreviewed = set(unreviewed_roots)
    if report.frontier_statements or unreviewed & statement_roots:
        return TRUST_FRONTIER_STATEMENT
    if unreviewed & proof_roots or "exhausted" in proof_roots:
        return TRUST_FRONTIER_PROOF
    if set(reviewed_roots) & (statement_roots | proof_roots):
        return TRUST_CORE
    return TRUST_MATHLIB


def _trust_diagnostics(
    report: AuditReport, unreviewed_roots: tuple[str, ...], reviewed_roots: tuple[str, ...]
) -> list[Diagnostic]:
    level = trust_level(report, unreviewed_roots, reviewed_roots)
    if level is None:
        return []
    constants = sorted({" ".join(item.split(" ")[1:2]) for item in report.frontier_statements})
    modules = sorted({_last_word(item) for item in report.frontier_statements})
    shown = {
        TRUST_MATHLIB: "Lean and Mathlib only.",
        TRUST_CORE: "Uses the human-reviewed StacksCore.",
        TRUST_FRONTIER_PROOF: (
            "The proof uses Frontier lemmas (AI-written, not human-reviewed); "
            "the statement does not."
        ),
        TRUST_FRONTIER_STATEMENT: (
            "Frontier (human-unreviewed): the statement uses AI-written definitions that no human "
            "has reviewed: " + ", ".join(constants[:6]) + "."
        ),
    }[level]
    diagnostics = [
        Diagnostic(
            severity="warning" if level.startswith("frontier") else "info",
            code=TRUST_LEVEL_DIAGNOSTIC,
            message=shown,
            metadata={
                "trust_level": level,
                "frontier_statement_constants": constants[:32],
                "frontier_modules": modules[:32],
                "statement_roots": sorted({_last_word(item) for item in report.statement_roots}),
                "proof_roots": sorted({_last_word(item) for item in report.proof_roots}),
            },
        )
    ]
    if report.frontier_duplicates:
        pairs = [item.split(" ", 2) for item in report.frontier_duplicates]
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code=FRONTIER_DUPLICATE_DIAGNOSTIC,
                message=(
                    "A Frontier definition used by a statement resembles a Mathlib or StacksCore "
                    "one under another name; recorded, not rejected: "
                    + "; ".join(f"{a} ~ {b} ({c})" for a, b, c in pairs[:4])
                    + "."
                ),
                metadata={
                    "duplicates": [
                        {"frontier": a, "other": b, "reason": c} for a, b, c in pairs[:24]
                    ]
                },
            )
        )
    return diagnostics


def _names_declaration(reported: str, declared: str) -> bool:
    return reported == declared or reported.endswith("." + declared)
