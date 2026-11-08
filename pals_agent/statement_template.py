"""Fix the theorem statement: the model writes only the proof body, the system inserts the rest.

In the recorded failures with ``lean.formal_harness_mismatch`` the model never rewrote the
fixed statement. It wrote a different declaration (usually an ``example`` for a sub-claim) in
its place, so no later repair could restore the target. With this template the model returns
the imports, optional auxiliary lemmas and the tactic body after a marker line; the fixed
statement is inserted verbatim between them. The statement can then no longer differ from the
harness, and the final checks (``formal_harness`` text match, allowed axioms, kernel check)
are unchanged.

Opt-in through ``HybridLeanGenerator.fixed_statement_template``.
"""

from __future__ import annotations

import re
import textwrap

MARKER = "-- PALS-PROOF-BODY"

TEMPLATE_INSTRUCTION = f"""
Statement template mode (this replaces the output layout requested above):
The theorem statement above is fixed and the system inserts it for you. Do not write the
target theorem line, do not write `theorem`, `lemma` or `example` for the target, and do not
write `:= by` for the target. Return exactly one fenced Lean code block with this layout:
  - the `import` and `open` lines you need;
  - optionally, complete auxiliary lemmas that the proof uses;
  - a line containing exactly `{MARKER}`;
  - the tactic proof of the fixed statement, written as the lines that follow `:= by`.
Everything after the marker line is the proof body and nothing else.
"""

_STATEMENT_START = re.compile(r"^\s*(?:theorem|lemma|example)\b")
_BY_PREFIX = re.compile(r"\A\s*(?::=\s*)?by\b[ \t]*\n?")


def assemble(raw_code: str, formal_statement: str) -> str:
    """Insert the fixed statement; return ``raw_code`` unchanged when no body is found."""
    statement = formal_statement.strip()
    if not _STATEMENT_START.match(statement):
        return raw_code
    head, marker, body = raw_code.partition(MARKER)
    if marker:
        body = _BY_PREFIX.sub("", body, count=1)
    else:
        found = _body_after_target(raw_code, statement)
        if found is None:
            return raw_code
        head, body = found
    body = textwrap.dedent(body.strip("\n"))
    if not body.strip():
        return raw_code
    indented = textwrap.indent(body, "  ")
    return f"{head.rstrip()}\n\n{statement} := by\n{indented}\n".lstrip("\n")


def _name_of(statement: str) -> str | None:
    match = re.match(r"\s*(?:theorem|lemma)\s+([^\s({\[:]+)", statement)
    return match.group(1) if match else None


def _body_after_target(raw_code: str, statement: str) -> tuple[str, str] | None:
    """The model wrote the target itself: take what follows its top-level `:=`."""
    name = _name_of(statement)
    if name is None:
        return None
    start = re.search(rf"^[ \t]*(?:theorem|lemma)\s+{re.escape(name)}\b", raw_code, re.MULTILINE)
    if start is None:
        return None
    depth = 0
    index = start.end()
    while index < len(raw_code):
        char = raw_code[index]
        if char in "([{⟨":
            depth += 1
        elif char in ")]}⟩":
            depth -= 1
        elif depth <= 0 and raw_code.startswith(":=", index):
            body = raw_code[index + 2 :]
            if not re.match(r"\s*by\b", body):
                return None  # a term-mode proof cannot be placed after `:= by`
            return raw_code[: start.start()], _BY_PREFIX.sub("", body, count=1)
        index += 1
    return None
