"""Repair a failed Lean Sketch check without calling a model.

Two mechanical repairs, both applied only after the Sketch check failed:

* ``normalize_header``: replace the model's focused imports by ``import Mathlib`` and add the
  ``open`` line that a notation in the code needs. The model chooses imports from memory and
  often misses a module (unknown constant, failed instance) or names one that does not exist.
* ``sorry_failing_leaves``: replace each failing proof block by ``sorry``.

Details of the second repair:

A Sketch is a skeleton: its substantive steps are `sorry` gaps that Prove fills in. The model
often writes a real proof for an easy step instead, and that proof does not compile. The
Sketch check then fails and the pipeline pays for a repair instruction, a route choice and a
fresh Sketch. This module replaces each failing proof block by `sorry`, keeping every `have`
statement, so the skeleton checks and Prove starts from the same structure.

Only errors inside the proof body are handled. An error in the imports, the theorem
statement, or a parse error leaves the code unchanged (``None``). The caller re-checks the
result with Lean; nothing here decides success.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from pals_agent.models import Diagnostic, VerificationResult

# Notations that exist only inside a namespace the model must open. Source: Mathlib `scoped`
# notation declarations; the mapping is a fixed table, not learned from evaluation cards.
SCOPED_NOTATION: tuple[tuple[str, str], ...] = (
    ("𝓝", "Topology"),
    ("⟪", "RealInnerProductSpace"),
    ("ᵀ", "Matrix"),
    ("⬝ᵥ", "Matrix"),
    ("≥0∞", "ENNReal"),
    ("ℝ≥0", "NNReal"),
    ("⊗ₜ", "TensorProduct"),
)

_SORRY = "sorry"
_BY = re.compile(r"(?<![\w.'])by(?![\w'])")
_DECLARATION = re.compile(
    r"^\s*(?:(?:private|protected|noncomputable)\s+)*(?:theorem|lemma|example)\b"
)
_PARSE_ERROR = re.compile(
    r"unexpected token|unknown tactic|unterminated|^expected token|expected ':'|<input>",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class _Block:
    """A `by` block: the `by` token and the lines of its tactic body (1-based, inclusive)."""

    by_line: int
    by_column: int
    first: int
    last: int
    inline: bool
    indent: int


def _mask(lines: list[str]) -> list[str]:
    """Blank out comments and strings so `by` inside them is ignored (positions are kept)."""
    masked: list[str] = []
    block_depth = 0
    for line in lines:
        chars = list(line)
        i = 0
        in_string = False
        while i < len(chars):
            two = line[i : i + 2]
            if block_depth:
                if two == "-/":
                    block_depth -= 1
                    chars[i : i + 2] = "  "
                    i += 2
                elif two == "/-":
                    block_depth += 1
                    chars[i : i + 2] = "  "
                    i += 2
                else:
                    chars[i] = " "
                    i += 1
            elif in_string:
                if line[i] == "\\":
                    chars[i : i + 2] = "  "
                    i += 2
                    continue
                if line[i] == '"':
                    in_string = False
                chars[i] = " "
                i += 1
            elif two == "/-":
                block_depth += 1
                chars[i : i + 2] = "  "
                i += 2
            elif two == "--":
                for j in range(i, len(chars)):
                    chars[j] = " "
                break
            elif line[i] == '"':
                in_string = True
                chars[i] = " "
                i += 1
            else:
                i += 1
        masked.append("".join(chars))
    return masked


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _blocks(lines: list[str], masked: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    for number, text in enumerate(masked, start=1):
        for match in _BY.finditer(text):
            rest = text[match.end() :].strip()
            if rest:
                # Tactics on the same line as `by`: the block is that text only, plus any
                # following lines indented deeper than the line that holds `by`.
                tactic_column = match.end() + (
                    len(text) - match.end() - len(text[match.end() :].lstrip())
                )
                last = number
                for follower in range(number + 1, len(lines) + 1):
                    if not masked[follower - 1].strip():
                        continue
                    if _indent(lines[follower - 1]) < tactic_column:
                        break
                    last = follower
                blocks.append(_Block(number, match.start(), number, last, True, match.end()))
                continue
            first = number + 1
            while first <= len(lines) and not masked[first - 1].strip():
                first += 1
            if first > len(lines):
                continue
            indent = _indent(lines[first - 1])
            if indent < _indent(lines[number - 1]):
                continue  # A body indented less than its `by` line is not a block we can isolate.
            last = first
            for follower in range(first + 1, len(lines) + 1):
                if not masked[follower - 1].strip():
                    continue
                if _indent(lines[follower - 1]) < indent:
                    break
                last = follower
            blocks.append(_Block(number, match.start(), first, last, False, indent))
    return blocks


def _header_end(masked: list[str]) -> int:
    inside = False
    for number, text in enumerate(masked, start=1):
        if not inside and _DECLARATION.match(text):
            inside = True
        if inside and ":=" in text:
            return number
    return 0


def sorry_failing_leaves(lean_code: str, diagnostics: list[Diagnostic]) -> str | None:
    """Return the Sketch with each failing proof block replaced by `sorry`, or None.

    None means no error lies inside a proof body that can be isolated, so the caller must keep
    its existing failure path.
    """
    errors = [
        d
        for d in diagnostics
        if d.severity == "error" and d.line is not None and d.code != "lean.declaration_uses_sorry"
    ]
    if not errors:
        return None
    lines = lean_code.split("\n")
    masked = _mask(lines)
    header_end = _header_end(masked)
    if not header_end:
        return None
    blocks = _blocks(lines, masked)
    top = next((b for b in blocks if b.by_line == header_end), None)
    if top is None:
        return None

    replace_blocks: dict[tuple[int, int], _Block] = {}
    top_edits: list[tuple[int, str]] = []  # (first line to cut, replacement)
    for diagnostic in errors:
        line = int(diagnostic.line or 0)
        column = int(diagnostic.column or 0)
        if line <= header_end and not (line == top.by_line and column >= top.by_column):
            return None  # imports, statement or header: not a proof body
        if _PARSE_ERROR.search(diagnostic.message.lower()):
            return None
        position = (line, column)
        enclosing = [
            b
            for b in blocks
            if (b.by_line, b.by_column) <= position <= (b.last, 10**9)
            and not (b.by_line == line and column < b.by_column)
        ]
        if not enclosing:
            return None
        inner = max(enclosing, key=lambda b: (b.by_line, b.by_column))
        if inner is not top:
            replace_blocks[(inner.first, inner.last)] = inner
            continue
        # The error is in the theorem's own block.
        if (line, column) == (top.by_line, top.by_column) or line == top.by_line:
            top_edits.append((top.last + 1, f"{' ' * top.indent}all_goals {_SORRY}"))
            continue
        start = line
        while start > top.first and _indent(lines[start - 1]) > top.indent:
            start -= 1
        top_edits.append((start, f"{' ' * top.indent}all_goals {_SORRY}"))

    # A nested block inside another replaced block is covered by the outer replacement.
    kept = [
        b
        for b in replace_blocks.values()
        if not any(
            o is not b
            and o.first <= b.first
            and b.last <= o.last
            and (o.first, o.last) != (b.first, b.last)
            for o in replace_blocks.values()
        )
    ]
    edits: list[tuple[int, int, str]] = []  # (first, last, replacement text)
    for block in kept:
        if block.inline:
            head = lines[block.by_line - 1][: block.by_column + 2]
            edits.append((block.by_line, block.last, f"{head} {_SORRY}"))
        else:
            edits.append((block.first, block.last, f"{' ' * block.indent}{_SORRY}"))
    if top_edits:
        cut = min(first for first, _ in top_edits)
        text = next(replacement for first, replacement in top_edits if first == cut)
        top_last = top.last
        if cut <= top_last:
            edits = [e for e in edits if e[1] < cut]
            edits.append((cut, top_last, text))
        else:
            edits.append((cut, cut - 1, text))
    if not edits:
        return None
    out: list[str] = []
    cursor = 1
    for first, last, text in sorted(edits):
        if first < cursor:
            continue
        out.extend(lines[cursor - 1 : first - 1])
        out.append(text)
        cursor = last + 1
    out.extend(lines[cursor - 1 :])
    result = "\n".join(out)
    return result if result != lean_code else None


def normalize_header(lean_code: str) -> str | None:
    """`import Mathlib` instead of focused imports, plus `open` lines for scoped notation."""
    lines = lean_code.split("\n")
    body = [line for line in lines if not line.startswith("import ")]
    text = "\n".join(_mask(body))
    opened = " ".join(line for line in body if line.startswith("open "))
    needed: list[str] = []
    for token, namespace in SCOPED_NOTATION:
        if token in text and namespace not in opened and namespace not in needed:
            needed.append(namespace)
    imports = [line for line in lines if line.startswith("import ")]
    if imports == ["import Mathlib"] and not needed:
        return None
    header = ["import Mathlib"]
    if needed:
        header.append("open " + " ".join(needed))
    while body and not body[0].strip():
        body.pop(0)
    result = "\n".join([*header, "", *body])
    return result if result != lean_code else None


@dataclass(frozen=True, slots=True)
class SketchRepair:
    lean_code: str
    steps: tuple[str, ...]
    rechecks: int
    elapsed_ms: int
    verification: VerificationResult


def repair_sketch(
    lean_code: str,
    first: VerificationResult,
    verify: Callable[[str], VerificationResult],
    *,
    max_rechecks: int = 3,
) -> SketchRepair | None:
    """Try the mechanical repairs in order; return the first Sketch that passes the check."""
    steps: list[str] = []
    elapsed = 0
    current, result = lean_code, first
    for _ in range(max_rechecks):
        header = normalize_header(current) if "header" not in steps else None
        candidate: str | None = header
        step = "header"
        if candidate is None:
            candidate = sorry_failing_leaves(current, list(result.diagnostics))
            step = "sorry"
        if candidate is None:
            return None
        steps.append(step)
        current = candidate
        result = verify(current)
        elapsed += result.elapsed_ms
        if result.success:
            return SketchRepair(current, tuple(steps), len(steps), elapsed, result)
    return None
