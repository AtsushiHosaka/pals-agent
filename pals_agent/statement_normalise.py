"""Safe normalisations that recover statements the allow-list grammar refuses, without loosening it.

* ``rename_reserved_variable``: a bound variable named like a Lean keyword (``λ``) is renamed, but
  only if every occurrence is a variable (never a lambda: not followed by ``=>`` or ``↦``) and the
  new name is unused.  Purely syntactic alpha-renaming; Lean still elaborates the result.
* ``hoist_lets``: ``∀ …, let p := E; body`` becomes ``∀ …, body[p := E]`` by substitution in
  Python.  The hoisted statement goes through the normal grammar.  For CATALOG statements only,
  ``equivalence_source`` builds a Lean check that the two are the same ``Prop``
  (``Iff.rfl`` inside the sandbox); the original text with ``let`` never reaches the grammar and
  never reaches Lean unless a caller explicitly runs that check on a catalog card.
"""

from __future__ import annotations

import re
from typing import Final

_LAMBDA_AS_LAMBDA: Final = re.compile(r"λ[^,;:()\[\]{}]*(?:=>|↦)")
_IDENT_CHAR: Final = r"[\w'.!?]"


def rename_reserved_variable(text: str, name: str = "λ", replacement: str = "lam") -> str | None:
    """Rename ``name`` when every occurrence is a variable; None when it cannot be done safely."""
    if name not in text:
        return text
    if name == "λ" and _LAMBDA_AS_LAMBDA.search(text):
        return None  # used as a lambda: renaming would change the meaning
    if re.search(rf"(?<!{_IDENT_CHAR}){re.escape(replacement)}(?!{_IDENT_CHAR})", text):
        return None  # the new name is already in use
    return text.replace(name, replacement)


def _depth_zero(text: str, token: str, start: int = 0) -> int | None:
    depth = 0
    for index in range(start, len(text)):
        ch = text[index]
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif depth == 0 and text.startswith(token, index):
            return index
    return None


_LET: Final = re.compile(r"(?<![\w'.])let\s+([^\W\d][\w'!?]*)\s*:=\s*")


def hoist_lets(text: str) -> str | None:
    """Substitute a chain ``let x := e; …`` into its body; None if the shape is not recognised."""
    out = text
    for _ in range(8):
        match = _LET.search(out)
        if match is None:
            return out if "let" not in re.sub(r"[\w'.]*let[\w'.]*", "", out).split() else None
        end = _depth_zero(out, ";", match.end())
        if end is None:
            return None
        name, value = match.group(1), out[match.end() : end].strip()
        body = out[end + 1 :]
        # a following "." is field access on the variable (`p.comp q`), so it is allowed
        pattern = re.compile(rf"(?<![\w'.]){re.escape(name)}(?![\w'!?])")
        if re.search(rf"(?<![\w'.])(fun|∀|∃)\s[^,=]*\b{re.escape(name)}\b", body):
            return None  # the name is rebound inside: substitution could capture
        body = pattern.sub(f"({value})", body)
        out = out[: match.start()] + body.lstrip()
    return None


def equivalence_source(original: str, hoisted: str) -> str:
    """Lean text checking the two statements are the same ``Prop`` (catalog statements only)."""
    # `Type*` in the two statements would be two different universe parameters
    original, hoisted = (re.sub(r"\b(Type|Sort)\*", r"\1", t) for t in (original, hoisted))
    return (
        "set_option autoImplicit false\nset_option relaxedAutoImplicit false\n"
        "set_option maxHeartbeats 100000 in\n"
        f"theorem _pals_hoist : ({original}) ↔ ({hoisted}) := Iff.rfl\n"
        "#print axioms _pals_hoist\n"
    )
