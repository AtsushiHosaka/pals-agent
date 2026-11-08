"""Mechanical classification of Lean diagnostics for failed Sketch checks (experiment only).

A Sketch fails when `LeanVerifier.verify_sketch` reports an error. Most Lean errors carry the
generic code `lean.error`, so the class is read from the message by fixed regular expressions,
checked in order. The first matching rule wins; a diagnostic that matches nothing is `other`.
The primary class of a failed check is the class of its earliest error by source position,
because later errors are often cascades of the first. Message text is never stored in records:
only classes, codes and the region of the source the error points at.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

# (class, pattern) in priority order. Patterns are matched against the lowercased message.
RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.DOTALL))
    for name, pattern in (
        ("harness_mismatch", r"does not contain the fixed formal statement"),
        (
            "missing_module",
            r"object file .* does not exist|unknown module prefix|"
            r"unknown package|no such file or directory",
        ),
        ("timeout", r"deterministic.{0,20}timeout|maximum recursion depth|heartbeats|timed out"),
        ("unknown_notation", r"unknown identifier `[^`a-z0-9_]*`"),
        ("unknown_identifier", r"unknown (identifier|constant|namespace)\b"),
        ("invalid_field", r"invalid field|invalid projection|has no field"),
        (
            "syntax",
            r"unexpected token|unknown tactic|expected (term|'|command)|parse error|"
            r"unterminated|invalid 'end'|expected token|<input>",
        ),
        (
            "missing_instance",
            r"failed to synthesize|typeclass instance problem is stuck|"
            r"could not synthesize default",
        ),
        (
            "application_mismatch",
            r"application type mismatch|function expected|"
            r"too many (explicit )?arguments|invalid .*argument|"
            r"insufficient number of arguments|"
            r"don't know how to synthesize (implicit|placeholder)|"
            r"explicit argument|named argument",
        ),
        (
            "type_mismatch",
            r"type mismatch|has type|but is expected to have type|"
            r"unification hint|ambiguous, possible interpretations|"
            r"invalid coercion|coercion",
        ),
        (
            "tactic_failed",
            r"(linarith|nlinarith|omega|positivity|norm_num|simp|ring|ring_nf|"
            r"field_simp|decide|aesop|fun_prop|gcongr|polyrith|rfl|rw|rewrite|"
            r"exact|apply|nlinarith|continuity|measurability|tauto|"
            r"constructor|cases|rcases|obtain|induction|intro|use|refine|"
            r"calc|conv|congr|ext)\b.{0,40}(failed|could not|made no progress|"
            r"no progress)|did not find instance of the pattern|"
            r"motive is not type correct|failed to prove|could not prove",
        ),
        ("unsolved_goals", r"unsolved goals|no goals"),
        (
            "other_unsupported_declaration",
            r"unknown (attribute|option|command)|"
            r"invalid (declaration|binder)|autobound",
        ),
    )
)

CLASSES: tuple[str, ...] = (*(name for name, _ in RULES), "other")

_HEADER_END = re.compile(r":=")
_DECLARATION = re.compile(
    r"^\s*(?:(?:private|protected|noncomputable)\s+)*"
    r"(theorem|lemma|example)\b"
)


def classify_message(message: str) -> str:
    text = message.lower()
    for name, pattern in RULES:
        if pattern.search(text):
            return name
    return "other"


def source_regions(lean_code: str) -> tuple[int, int]:
    """1-based lines: last import line, and the line where the first declaration header ends."""
    import_end = 0
    header_end = 0
    in_declaration = False
    for number, line in enumerate(lean_code.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("import "):
            import_end = number
        if not in_declaration and _DECLARATION.match(line):
            in_declaration = True
        if in_declaration and _HEADER_END.search(line):
            header_end = number
            break
    return import_end, header_end


def region_of(line: int | None, regions: tuple[int, int]) -> str:
    if line is None:
        return "unknown"
    import_end, header_end = regions
    if line <= import_end:
        return "imports"
    if header_end and line <= header_end:
        return "statement"
    return "body"


@dataclass(frozen=True, slots=True)
class DiagnosticClass:
    cls: str
    code: str | None
    line: int | None
    region: str


def classify_check(diagnostics: list[Any], lean_code: str) -> list[DiagnosticClass]:
    """Classify the error diagnostics of one Lean check, ordered by source position."""
    regions = source_regions(lean_code)
    rows = [
        DiagnosticClass(
            cls=classify_message(str(getattr(d, "message", ""))),
            code=getattr(d, "code", None),
            line=getattr(d, "line", None),
            region=region_of(getattr(d, "line", None), regions),
        )
        for d in diagnostics
        if getattr(d, "severity", "error") == "error"
        and getattr(d, "code", None) != "lean.declaration_uses_sorry"
    ]
    return sorted(rows, key=lambda r: (r.line is None, r.line or 0))


def summarize(rows: list[DiagnosticClass]) -> dict[str, Any]:
    return {
        "primary": rows[0].cls if rows else None,
        "primary_region": rows[0].region if rows else None,
        "classes": sorted({row.cls for row in rows}),
        "errors": len(rows),
        "class_counts": dict(Counter(row.cls for row in rows)),
    }
