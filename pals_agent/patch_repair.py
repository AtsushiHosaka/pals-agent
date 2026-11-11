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
# introduce anything that changes what Lean trusts or what the file declares. Checks run on the
# text with comments and string literals blanked out, so a word in a comment or a string is not a
# command and a command cannot hide in either.
_MODIFIERS = r"(?:(?:private|protected|noncomputable|local|scoped|partial|unsafe|nonrec)\s+)*"
_ATTRIBUTES = r"(?:@\[[^\]]*\]\s*)*"
_DECLARATION = re.compile(
    rf"^\s*{_ATTRIBUTES}{_MODIFIERS}(?:theorem|lemma|example)\b"
)
_FORBIDDEN_WORD = re.compile(
    r"\b(?:axiom|set_option|native_decide|sorry|admit|import|unsafe|implemented_by|extern|"
    r"run_cmd|attribute|deriving)\b"
)
# Commands that may only begin a line (as `#eval`, `opaque x`, `syntax ...`): an identifier that
# merely contains one of these words is fine.
_FORBIDDEN_COMMAND = re.compile(
    rf"^\s*{_ATTRIBUTES}{_MODIFIERS}"
    r"(?:theorem|lemma|def|abbrev|instance|structure|inductive|class|opaque|macro|macro_rules|"
    r"syntax|elab|notation|infix|infixl|infixr|prefix|postfix|partial|namespace|section|"
    r"end|universe|variable|open|export)\b|^\s*#[A-Za-z]",
    re.MULTILINE,
)


def _char_literal_end(source: str, start: int) -> int | None:
    """Index just past a Lean char literal that begins at ``source[start] == "'"``, else None.

    Forms: ``'x'`` (any one character, including a double quote), ``'\\n'``, ``'\\''``,
    ``'\\"'``, ``'\\\\'``, ``'\\x41'``, ``'\\u{1F600}'``. A prime that continues an identifier
    (``h'``) is not a literal; the caller checks the previous character."""
    n = len(source)
    i = start + 1
    if i >= n:
        return None
    if source[i] == "\\":
        i += 1
        if i >= n:
            return None
        escape = source[i]
        i += 1
        if escape == "x":
            i += 2
        elif escape == "u" and i < n and source[i] == "{":
            close = source.find("}", i)
            if close < 0:
                return None
            i = close + 1
    else:
        i += 1
    return i + 1 if i < n and source[i] == "'" else None


def scan_source(source: str) -> tuple[str, bool]:
    """``source`` with comments, string literals and char literals replaced by spaces (newlines
    kept), plus whether the text was well formed. ``False`` means an unterminated string or block
    comment: whatever follows cannot be trusted, so callers fail closed. Handles nested ``/- -/``
    blocks."""
    out: list[str] = []
    i, n, depth = 0, len(source), 0
    while i < n:
        two = source[i : i + 2]
        if depth:
            if two == "/-":
                depth += 1
                out.append("  ")
                i += 2
            elif two == "-/":
                depth -= 1
                out.append("  ")
                i += 2
            else:
                out.append("\n" if source[i] == "\n" else " ")
                i += 1
        elif two == "/-":
            depth = 1
            out.append("  ")
            i += 2
        elif two == "--":
            while i < n and source[i] != "\n":
                out.append(" ")
                i += 1
        elif source[i] == "'" and not (i and (source[i - 1].isalnum() or source[i - 1] in "_'.!?")):
            end = _char_literal_end(source, i)
            if end is None:
                out.append(source[i])
                i += 1
            else:
                out.extend("\n" if c == "\n" else " " for c in source[i:end])
                i = end
        elif source[i] == '"':
            out.append(" ")
            i += 1
            closed = False
            while i < n:
                if source[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                if source[i] == '"':
                    out.append(" ")
                    i += 1
                    closed = True
                    break
                out.append("\n" if source[i] == "\n" else " ")
                i += 1
            if not closed:
                return "".join(out), False
        else:
            out.append(source[i])
            i += 1
    return "".join(out), depth == 0


def blank_comments_and_strings(source: str) -> str:
    return scan_source(source)[0]


def protected_through(lean_code: str) -> int:
    """Last line (1-based) a patch may not touch: imports, `open`s, the declaration header and the
    line where its proof starts. That is the first `:=` at bracket depth 0 after the declaration
    keyword, not counting the `:=` of a `let`/`have`/`set` inside the statement. When no
    declaration is found, every line is protected."""
    blanked, well_formed = scan_source(lean_code)
    lines = blanked.splitlines()
    if not well_formed:
        return len(lean_code.splitlines())
    for index, line in enumerate(lines):
        if not _DECLARATION.match(line):
            continue
        depth, binders = 0, 0
        for end in range(index, len(lines)):
            text = lines[end]
            position = 0
            while position < len(text):
                char = text[position]
                if char in "([{⟨":
                    depth += 1
                elif char in ")]}⟩":
                    depth = max(0, depth - 1)
                elif text.startswith(":=", position):
                    if depth == 0:
                        if binders:
                            binders -= 1
                        else:
                            return end + 1
                    position += 1
                elif depth == 0:
                    word = re.match(r"(?:let|have|set|show)\b", text[position:])
                    if word and (position == 0 or not text[position - 1].isalnum()):
                        binders += 1
                        position += len(word.group(0)) - 1
                position += 1
        break
    return len(lines)


def body_is_forbidden(body: str) -> bool:
    blanked, well_formed = scan_source(body)
    if not well_formed:
        return True  # an unterminated string or comment hides the rest: fail closed
    return bool(_FORBIDDEN_WORD.search(blanked) or _FORBIDDEN_COMMAND.search(blanked))


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
    if any(body_is_forbidden("\n".join(body)) for _first, _last, body in edits):
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
