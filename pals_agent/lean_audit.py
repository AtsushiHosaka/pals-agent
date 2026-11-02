"""Trusted post-compilation audit that an elaboration-time exit cannot satisfy.

The candidate compiles to ``Main.olean`` in one process. A later process runs only the fixed program
below: it reads the artifact as data, activates none of the candidate's environment extensions,
replays every candidate constant through the kernel, and reports theorems and transitive axioms with
a nonce created after the candidate exited. A candidate that exits early writes no artifact, and it
never sees the nonce because the nonce does not exist while it runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from pals_agent.models import Diagnostic

ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
AUDIT_FAILED = "lean.trusted_audit_failed"
_THEOREM_PREFIX = "theorem "
_AXIOM_PREFIX = "axiom "
_COMPLETE_PREFIX = "complete "

TRUSTED_AUDIT_SOURCE = """\
import Lean
open Lean

unsafe def main (args : List String) : IO UInt32 := do
  let [nonce, olean] := args | return 64
  let (mod, _region) ← readModuleData olean
  let env ← importModules mod.imports {} 0
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
  IO.println s!"complete {nonce}"
  return 0
"""


@dataclass(frozen=True, slots=True)
class AuditReport:
    theorems: tuple[str, ...]
    axioms: tuple[str, ...]


def parse_audit_report(stdout: str, nonce: str) -> AuditReport | None:
    """Return the report only when it is closed by exactly this request's nonce."""
    lines = stdout.splitlines()
    if not lines or lines[-1] != _COMPLETE_PREFIX + nonce:
        return None
    theorems: list[str] = []
    axioms: list[str] = []
    for line in lines[:-1]:
        if line.startswith(_THEOREM_PREFIX):
            theorems.append(line.removeprefix(_THEOREM_PREFIX))
        elif line.startswith(_AXIOM_PREFIX):
            axioms.append(line.removeprefix(_AXIOM_PREFIX))
        else:
            return None
    return AuditReport(tuple(theorems), tuple(axioms))


def audit_failure(message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=AUDIT_FAILED, message=message)


def audit_diagnostics(report: AuditReport, declared_theorems: tuple[str, ...]) -> list[Diagnostic]:
    """Apply axiom and declaration policy; no error diagnostics means the audit passed."""
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
    return diagnostics


def _names_declaration(reported: str, declared: str) -> bool:
    return reported == declared or reported.endswith("." + declared)
