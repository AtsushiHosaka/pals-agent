"""Whitespace-only layout normalisation of generated Lean signatures.

The deployed verifier image still carries the statement audit that treats every line-leading ``|``
at bracket depth 0 after the type colon as a pattern-matching alternative, so a conclusion such as

    theorem t (μ m σ : ℝ) :
        |μ - m| ≤ σ := by

is restated as ``... : := sorry`` and the whole file is rejected as ``lean.statement_mismatch``
although the proof is correct. ``lean_source_policy._signature`` no longer has that flaw, but the
verifier image cannot be replaced together with the worker, so the worker must not send such a
layout. This module joins each such line to the code before it. Only whitespace between two code
tokens changes; proof bodies, equation-compiler alternatives, ``match`` arms, comments and strings
are never touched, and a bar whose preceding whitespace holds a comment is left as it is (joining
it would pull code into the comment, and moving the comment is not a whitespace change).

The signature extent comes from the current ``lean_source_policy`` parser, so a bar that parser
reads as an alternative is, by construction, outside every range this module edits.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from pals_agent.lean_source_policy import (
    _AUDITED_EXAMPLE,
    _CHAR_LITERAL,
    _COMMAND_START,
    _COMMANDS,
    _EXAMPLE,
    _SIGNATURE_CLOSING,
    _SIGNATURE_OPENING,
    _STATEMENT_COMMANDS,
    _THEOREM,
    _masked_code,
    _signature,
)


def normalise_signature_layout(source: str) -> str:
    """Return ``source`` with line-leading non-alternative ``|`` in signatures joined upward.

    Idempotent and total: any failure returns ``source`` unchanged.
    """
    try:
        return _normalise(source, None)
    except Exception:
        return source


def _normalise(source: str, steps: MutableMapping[str, int] | None) -> str:
    if "|" not in source:
        return source
    code = _masked_code(source)
    starts = [
        (match.start(), match.group("command"))
        for match in _COMMAND_START.finditer(code)
        if match.group("command") in _COMMANDS
    ]
    ends = [start for start, _ in starts[1:]] + [len(code)]
    edits: list[tuple[int, int]] = []
    for (start, command), end in zip(starts, ends, strict=False):
        segment = code[start:end]
        text = segment.strip()
        offset = start + len(segment) - len(segment.lstrip())
        head = _declaration_head(text, command)
        if head is None:
            continue
        signature = _signature(text, head)
        if signature is None:
            continue
        for bar in _joinable_bars(text, head, head + len(signature), steps):
            edit = _gap_before(source, code, offset + bar, offset + head, steps)
            if edit is not None:
                edits.append(edit)
    if not edits:
        return source
    pieces: list[str] = []
    position = 0
    for gap_start, gap_end in edits:
        pieces += [source[position:gap_start], " "]
        position = gap_end
    pieces.append(source[position:])
    return "".join(pieces)


def _declaration_head(text: str, command: str) -> int | None:
    """Offset where the signature starts, found as ``statement_reference`` finds it."""
    example = _AUDITED_EXAMPLE.search(text) or (
        _EXAMPLE.search(text) if command == "example" else None
    )
    if example is not None:
        return example.end()
    if command not in _STATEMENT_COMMANDS:
        return None
    theorem = _THEOREM.search(text)
    return None if theorem is None else theorem.end()


def _joinable_bars(
    text: str, start: int, end: int, steps: MutableMapping[str, int] | None
) -> list[int]:
    """Line-leading depth-0 bars after the type colon inside ``text[start:end]``."""
    bars: list[int] = []
    depth = 0
    has_type = False
    line_blank = False  # the signature starts after the declaration name on its own line
    index = start
    while index < end:
        if steps is not None:
            steps["scan"] = steps.get("scan", 0) + 1
        character = text[index]
        if character == "\n":
            line_blank = True
        elif character == "'" and (literal := _CHAR_LITERAL.match(text, index)):
            index = literal.end()
            line_blank = False
            continue
        elif character in _SIGNATURE_OPENING:
            depth += 1
            line_blank = False
        elif character in _SIGNATURE_CLOSING:
            depth -= 1
            line_blank = False
        elif depth == 0 and text.startswith(":=", index):
            index += 2
            line_blank = False
            continue
        elif depth == 0 and character == ":":
            has_type = True
            line_blank = False
        elif depth == 0 and character == "|" and has_type and line_blank:
            bars.append(index)
            line_blank = False
        elif not character.isspace():
            line_blank = False
        index += 1
    return bars


def _gap_before(
    source: str, code: str, bar: int, floor: int, steps: MutableMapping[str, int] | None
) -> tuple[int, int] | None:
    """The whitespace run directly before ``bar`` when it holds a line break and nothing else.

    ``code`` blanks comments and strings, so a run of blanks in it that is not whitespace in
    ``source`` is a comment or string: such a bar is left alone.
    """
    gap_start = bar
    while gap_start > floor and code[gap_start - 1].isspace():
        if steps is not None:
            steps["gap"] = steps.get("gap", 0) + 1
        gap_start -= 1
    gap = source[gap_start:bar]
    if gap_start <= floor or gap.strip() or "\n" not in gap:
        return None
    return gap_start, bar
