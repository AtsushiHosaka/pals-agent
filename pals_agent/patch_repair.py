"""Apply a line-range patch to a failed Lean source (the output of a patch-style repair).

The model answers with edits against a numbered listing instead of a whole file::

    REPLACE 12-14
    nlinarith [sq_nonneg (a - b)]
    END

``REPLACE n`` or ``REPLACE n-m`` swaps those lines for the body (an empty body deletes them).
Application is deterministic and strict: a malformed, out-of-range, overlapping or oversized
patch is rejected as a whole (``None``), so the caller falls back to the full repair path. The
result is only a candidate; it still passes the harness preflight and real Lean compilation.
"""

from __future__ import annotations

import re

# A patch edits the proof, never the statement, imports or declarations around it, and may not
# introduce anything that changes what Lean trusts or what the file declares.
FORBIDDEN_IN_BODY = re.compile(
    r"\b(?:axiom|set_option|native_decide|sorry|admit|import|unsafe|implemented_by|extern|macro|"
    r"syntax|elab|notation|run_cmd|opaque|constant)\b|#|^\s*(?:theorem|lemma|def|abbrev|instance|"
    r"structure|inductive|class)\b",
    re.MULTILINE,
)
_DECLARATION = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:theorem|lemma|example)\b")


def protected_through(lean_code: str) -> int:
    """Last line (1-based) a patch may not touch: imports, `open`s, the declaration header and the
    line where its proof starts (`:=`). When no declaration is found, every line is protected."""
    lines = lean_code.splitlines()
    for index, line in enumerate(lines):
        if _DECLARATION.match(line):
            for end in range(index, len(lines)):
                if ":=" in lines[end]:
                    return end + 1
            break
    return len(lines)


MAX_EDITS = 6
MAX_BODY_CHARS = 6000
_HEADER = re.compile(r"^REPLACE (\d{1,5})(?:-(\d{1,5}))?\s*$")


def numbered_listing(lean_code: str) -> str:
    """The source with 1-based line numbers, the frame of reference for the model's edits."""
    return "\n".join(f"{i:>4}| {line}" for i, line in enumerate(lean_code.splitlines(), 1))


def parse_patch(text: str) -> list[tuple[int, int, list[str]]] | None:
    """(first_line, last_line, body_lines) edits, or ``None`` when the text is not a patch."""
    edits: list[tuple[int, int, list[str]]] = []
    current: tuple[int, int] | None = None
    body: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if current is None:
            match = _HEADER.match(line.strip())
            if match is None:
                if line.strip().startswith("```") or not line.strip():
                    continue
                return None
            first = int(match.group(1))
            last = int(match.group(2) or first)
            current, body = (first, last), []
            continue
        if line.strip() == "END":
            edits.append((current[0], current[1], body))
            current = None
            continue
        body.append(line)
    if current is not None or not edits:
        return None
    return edits


def apply_patch(
    lean_code: str, patch_text: str, *, protected: int | None = None
) -> str | None:
    """The patched source, or ``None`` if the patch is not acceptable.

    ``protected`` is the last line no edit may touch (default: ``protected_through(lean_code)``).
    ``lean_code`` must be the very string the line numbers refer to (leading blank lines count)."""
    edits = parse_patch(patch_text)
    if edits is None or len(edits) > MAX_EDITS:
        return None
    if protected is None:
        protected = protected_through(lean_code)
    if any(first <= protected for first, _last, _body in edits):
        return None
    if any(
        FORBIDDEN_IN_BODY.search(re.sub(r"--[^\n]*", "", "\n".join(body)))
        for _first, _last, body in edits
    ):
        return None
    lines = lean_code.splitlines()
    if sum(len("\n".join(body)) for _first, _last, body in edits) > MAX_BODY_CHARS:
        return None
    ordered = sorted(edits, key=lambda edit: edit[0])
    previous_last = 0
    for first, last, _body in ordered:
        if first < 1 or last < first or last > len(lines) or first <= previous_last:
            return None
        previous_last = last
    for first, last, body in reversed(ordered):
        lines[first - 1 : last] = body
    patched = "\n".join(lines)
    return patched + "\n" if lean_code.endswith("\n") else patched
