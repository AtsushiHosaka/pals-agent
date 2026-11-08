"""Lexical statement shape: which constants a source-level signature mentions.

The Mathlib index reads constants from the elaborated type. Without a built environment the
Stacks index approximates that from the source text: identifiers that are not bound by a
binder or quantifier are taken to be constants, as written (so `Flat` and `Module.Flat` stay
distinct). The same function is applied to the query, so both sides share the approximation.
"""

from __future__ import annotations

import re

from tools.stacks_index.extract import _WORD_BOUND, split_binders

_IDENT = re.compile(r"[A-Za-z_À-￿][A-Za-z0-9_'!?À-￿]*(?:\.[A-Za-z_À-￿][A-Za-z0-9_'!?À-￿]*)*")
_QUANTIFIED = re.compile(r"(?:∀|∃!?|fun|λ|⨆|⨅|∑|∏|⋃|⋂)\s*([^,:↦⇒∈∣]*?)\s*(?:,|:|↦|=>|∈|∣)")
RESERVED = frozenset(
    {
        "fun", "by", "if", "then", "else", "let", "in", "at", "with", "from", "have", "show",
        "match", "do", "where", "forall", "exists", "Type", "Sort", "Prop", "theorem", "lemma",
        "def", "instance", "example", "structure", "class", "inductive", "extends", "deriving",
        "open", "namespace", "section", "end", "variable", "universe", "private", "protected",
        "noncomputable", "public", "id", "u", "v", "w",
    }
)  # fmt: skip


def _split_at_colon(signature: str) -> tuple[str, str]:
    depth = 0
    for index, char in enumerate(signature):
        if char in "([{⟨⦃":
            depth += 1
        elif char in ")]}⟩⦄":
            depth -= 1
        elif char == ":" and depth == 0 and signature[index + 1 : index + 2] != "=":
            return signature[:index], signature[index + 1 :]
    return "", signature


def _bound_names(text: str) -> set[str]:
    bound: set[str] = set()
    for binder in split_binders(text, bare=False):
        bound.update(binder.names)
    for match in _QUANTIFIED.finditer(text):
        bound.update(_WORD_BOUND.findall(match.group(1)))
    return bound


def _constants(text: str, bound: set[str]) -> list[str]:
    seen: dict[str, None] = {}
    for match in _IDENT.finditer(text):
        token = match.group()
        head, _, tail = token.partition(".")
        if head in bound:
            token = tail.rsplit(".", 1)[-1] if tail else ""
        if len(token) < 2 or token in RESERVED or token in bound:
            continue
        seen.setdefault(token)
    return list(seen)


def statement_shape(signature: str, context: str = "") -> dict[str, list[str]]:
    """Constants in the conclusion (after the first top-level colon) and in the hypotheses."""
    binders, conclusion = _split_at_colon(signature)
    bound = _bound_names(binders) | _bound_names(context) | _bound_names(conclusion)
    conclusion_constants = _constants(conclusion, bound)
    hypothesis_constants = [
        constant
        for constant in _constants(f"{context} {binders}", bound)
        if constant not in conclusion_constants
    ]
    return {
        "conclusion_constants": conclusion_constants,
        "hypothesis_constants": hypothesis_constants,
    }


def query_shape(lean_source: str) -> dict[str, list[str]]:
    """Shape of a Lean statement written as `theorem name ... : ...` or a bare signature."""
    text = re.sub(
        r"^\s*(?:@\[[^\]]*\]\s*)*(?:theorem|lemma|example)\s+[^\s(){}\[\]:]*", "", lean_source
    )
    text = re.sub(r":=.*$", "", text, flags=re.DOTALL)
    return statement_shape(text.strip())
