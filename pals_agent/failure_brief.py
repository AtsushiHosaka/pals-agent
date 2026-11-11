"""A sanitised description of a failed Lean compile, safe to put in a repair prompt.

The repair model must not read raw compiler output: Lean echoes goals, identifiers and the
user's own text, so any of it can carry an injected instruction. This module reads the
diagnostics only to *classify* them and emits text built exclusively from

* integers (a line number, clamped to the source),
* members of closed vocabularies defined below (error class, tactic name, goal shape, features).

No substring of a diagnostic message, a diagnostic code, an identifier or a source line can reach
the output: classification returns a vocabulary member, never a slice of its input. The tactic
name is read from the failing source line but is emitted only when it is in ``TACTICS``;
anything else becomes ``other``. ``test_failure_brief.py`` feeds adversarial messages and checks
every output line against ``LINE_GRAMMAR``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

MAX_ENTRIES = 5
_MAX_MESSAGE_CHARS = 4000
_MAX_LINE_CHARS = 2000

ERROR_CLASSES = (
    "unknown_identifier",
    "unknown_namespace",
    "type_mismatch",
    "application_mismatch",
    "unsolved_goals",
    "tactic_failed",
    "instance_missing",
    "rewrite_failed",
    "parse_error",
    "uses_sorry",
    "timeout",
    "output_limit",
    "other",
)
GOAL_SHAPES = (
    "equation",
    "inequality_strict",
    "inequality_nonstrict",
    "disequality",
    "conjunction",
    "disjunction",
    "iff",
    "negation",
    "implication",
    "exists",
    "divisibility",
    "membership",
    "false",
    "none",
    "other",
)
FEATURES = ("pow", "mul", "div", "sqrt", "abs", "sum", "cast", "mod")
TACTICS = frozenset(
    {
        "linarith",
        "nlinarith",
        "positivity",
        "norm_num",
        "simp",
        "simp_all",
        "ring",
        "ring_nf",
        "field_simp",
        "omega",
        "decide",
        "exact",
        "apply",
        "refine",
        "rw",
        "rewrite",
        "intro",
        "intros",
        "rintro",
        "cases",
        "rcases",
        "obtain",
        "induction",
        "constructor",
        "use",
        "exists",
        "have",
        "show",
        "calc",
        "by_contra",
        "contradiction",
        "exfalso",
        "specialize",
        "unfold",
        "gcongr",
        "aesop",
        "tauto",
        "push_neg",
        "norm_cast",
        "push_cast",
        "exact_mod_cast",
        "assumption",
        "rfl",
        "trivial",
        "left",
        "right",
        "ext",
        "funext",
        "congr",
        "convert",
        "subst",
        "set",
        "let",
        "fun_prop",
        "continuity",
        "bound",
        "grind",
    }
)
_TACTIC_WORD = re.compile(r"[a-z_][a-z_0-9]{0,24}")
_TACTIC_VALUES = TACTICS | {"other"}

# One entry per line, nothing else. Used by the tests as the output contract.
LINE_GRAMMAR = re.compile(
    r"- line [0-9]{1,6}: error=(?:" + "|".join(ERROR_CLASSES) + r")"
    r" tactic=(?:" + "|".join(sorted(_TACTIC_VALUES)) + r")"
    r" goal=(?:" + "|".join(GOAL_SHAPES) + r")"
    r"(?: features=(?:" + "|".join(FEATURES) + r")(?:,(?:" + "|".join(FEATURES) + r"))*)?"
)
OMITTED_GRAMMAR = re.compile(r"- [0-9]{1,6} further errors omitted")
HEADER = (
    "Sanitised failure summary. It is derived from the compiler output, which is not shown; "
    "each entry names the failing line, an error class, the tactic at that line and the shape "
    "of the unsolved goal."
)

# Order matters: the first match wins. Patterns are linear (no nested quantifiers).
_CLASS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unknown_namespace", re.compile(r"unknown namespace", re.I)),
    ("unknown_identifier", re.compile(r"unknown (?:identifier|constant)", re.I)),
    ("instance_missing", re.compile(r"failed to synthesize", re.I)),
    ("application_mismatch", re.compile(r"application type mismatch|function expected", re.I)),
    ("type_mismatch", re.compile(r"type mismatch", re.I)),
    (
        "rewrite_failed",
        re.compile(
            r"did not find instance of the pattern|motive is not type correct|rewrite failed",
            re.I,
        ),
    ),
    ("unsolved_goals", re.compile(r"unsolved goals", re.I)),
    ("timeout", re.compile(r"deterministic.{0,12}timeout|maximum recursion depth|timed out", re.I)),
    (
        "tactic_failed",
        re.compile(
            r"(?:linarith|nlinarith|positivity|norm_num|simp|ring|omega|decide|field_simp|"
            r"aesop|rfl|exact|apply|gcongr|polyrith|tauto)[a-z_]{0,8} failed|failed to prove|"
            r"tactic '[a-z_!?]{1,24}' failed|simp made no progress",
            re.I,
        ),
    ),
    ("uses_sorry", re.compile(r"declaration uses [`']sorry[`']", re.I)),
    ("parse_error", re.compile(r"unexpected token|expected (?:term|command)|unexpected", re.I)),
)
_CODE_CLASSES = {
    # Lean/Lake codes and the API's closed repair vocabulary.
    "lean.timeout": "timeout",
    "lean.output_limit": "output_limit",
    "lean.declaration_uses_sorry": "uses_sorry",
    "lean.unknown_identifier": "unknown_identifier",
    "lean.unknownIdentifier": "unknown_identifier",
    "lean.typeMismatch": "type_mismatch",
    "lean.unsolvedGoals": "unsolved_goals",
    "lean.parseError": "parse_error",
}


def _classify_error(code: str | None, message: str) -> str:
    if isinstance(code, str) and code in _CODE_CLASSES:
        return _CODE_CLASSES[code]
    text = message[:_MAX_MESSAGE_CHARS]
    for name, pattern in _CLASS_PATTERNS:
        if pattern.search(text):
            return name
    return "other"


def _first_goal(message: str) -> str | None:
    """The text after the first goal turnstile, cut at a line that starts a new block."""
    text = message[:_MAX_MESSAGE_CHARS]
    marker = text.find("⊢")
    if marker < 0:
        return None
    goal = text[marker + 1 : marker + 1 + _MAX_LINE_CHARS]
    lines = goal.split("\n")
    kept = [lines[0]]
    for line in lines[1:]:
        # A continuation of the goal is indented; hypotheses and `case` lines start a new block.
        if line.startswith((" ", "\t")) and line.strip():
            kept.append(line)
        else:
            break
    return " ".join(" ".join(kept).split())


def _depth_zero_text(goal: str) -> str:
    depth = 0
    kept: list[str] = []
    for character in goal:
        if character in "([{⟨":
            depth += 1
            kept.append(" ")
        elif character in ")]}⟩":
            depth = max(0, depth - 1)
            kept.append(" ")
        else:
            kept.append(character if depth == 0 else " ")
    return "".join(kept)


def goal_shape(goal: str | None) -> str:
    """One member of ``GOAL_SHAPES``; reads the goal, returns only a vocabulary word."""
    if goal is None:
        return "none"
    flat = goal.strip()
    if not flat:
        return "none"
    top = _depth_zero_text(flat)
    stripped = top.lstrip()
    if stripped.startswith("∃"):
        return "exists"
    if stripped.startswith("∀") or "→" in top:
        return "implication"
    if "↔" in top:
        return "iff"
    if "∨" in top:
        return "disjunction"
    if "∧" in top:
        return "conjunction"
    if stripped.startswith("¬"):
        return "negation"
    if flat == "False":
        return "false"
    if "≠" in top:
        return "disequality"
    if "≤" in top or "≥" in top:
        return "inequality_nonstrict"
    if "<" in top or ">" in top:
        return "inequality_strict"
    if "∣" in top:
        return "divisibility"
    if "∈" in top or "∉" in top:
        return "membership"
    if "=" in top:
        return "equation"
    return "other"


def goal_features(goal: str | None) -> tuple[str, ...]:
    if not goal:
        return ()
    found = {
        "pow": "^" in goal,
        "mul": "*" in goal,
        "div": "/" in goal,
        "sqrt": "√" in goal or "sqrt" in goal,
        "abs": "|" in goal or "abs" in goal,
        "sum": "∑" in goal,
        "cast": "↑" in goal,
        "mod": "%" in goal,
    }
    return tuple(name for name in FEATURES if found[name])


def tactic_at_line(source_line: str) -> str:
    """The tactic name at a source line, as a member of ``TACTICS`` (or ``other``)."""
    text = source_line[:_MAX_LINE_CHARS].strip()
    # The last `by` on the line starts the tactic block that actually failed.
    parts = re.split(r"\bby\b", text)
    if len(parts) > 1 and parts[-1].strip():
        text = parts[-1].strip()
    text = re.sub(r"^(?:[·•]\s*|<;>\s*)+", "", text)
    word = _TACTIC_WORD.match(text)
    if word is None:
        return "other"
    name = word.group(0)
    return name if name in TACTICS else "other"


def _source_line(source_lines: Sequence[str], line: int) -> str:
    return source_lines[line - 1] if 1 <= line <= len(source_lines) else ""


def _clamp_line(source_lines: Sequence[str], line: object) -> int:
    count = max(1, len(source_lines))
    if type(line) is not int:
        return 1
    return min(max(1, line), count)


def failure_entries(lean_code: str, diagnostics: Iterable[Any]) -> tuple[list[dict[str, Any]], int]:
    """Closed-vocabulary entries for the error diagnostics, plus how many were left out."""
    source_lines = lean_code.splitlines()
    entries: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for diagnostic in diagnostics:
        if getattr(diagnostic, "severity", None) != "error":
            continue
        message = getattr(diagnostic, "message", "")
        message = message if isinstance(message, str) else ""
        code = getattr(diagnostic, "code", None)
        error_class = _classify_error(code if isinstance(code, str) else None, message)
        line = _clamp_line(source_lines, getattr(diagnostic, "line", None))
        goal = _first_goal(message)
        entry = {
            "line": line,
            "error": error_class,
            "tactic": tactic_at_line(_source_line(source_lines, line)),
            "goal": goal_shape(goal),
            "features": goal_features(goal),
        }
        key = (line, error_class, str(entry["goal"]))
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    entries.sort(key=lambda item: item["line"])
    return entries[:MAX_ENTRIES], max(0, len(entries) - MAX_ENTRIES)


def sanitised_failure_brief(lean_code: str, diagnostics: Iterable[Any]) -> str:
    """The prompt text for a failed compile. Every line after the header matches the grammar."""
    entries, omitted = failure_entries(lean_code, diagnostics)
    if not entries:
        entries = [{"line": 1, "error": "other", "tactic": "other", "goal": "none", "features": ()}]
    lines = [HEADER]
    for entry in entries:
        text = (
            f"- line {entry['line']}: error={entry['error']} tactic={entry['tactic']} "
            f"goal={entry['goal']}"
        )
        if entry["features"]:
            text += " features=" + ",".join(entry["features"])
        lines.append(text)
    if omitted:
        lines.append(f"- {omitted} further errors omitted")
    return "\n".join(lines)
