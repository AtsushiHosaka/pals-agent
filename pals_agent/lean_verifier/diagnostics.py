"""Helpers for normalizing Lean diagnostics."""

from __future__ import annotations

from pals_agent.tools.lean_compile import LeanDiagnostic


def summarize_diagnostics(diagnostics: tuple[LeanDiagnostic, ...]) -> str:
    """Return a compact, public-safe diagnostic summary."""
    if not diagnostics:
        return "no diagnostics"

    parts: list[str] = []
    for diagnostic in diagnostics:
        location = ""
        if diagnostic.line is not None:
            location = f" line {diagnostic.line}"
            if diagnostic.column is not None:
                location += f":{diagnostic.column}"
        parts.append(f"{diagnostic.severity}{location}: {diagnostic.message}")
    return "\n".join(parts)

