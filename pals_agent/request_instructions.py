"""Separate presentation, language and format instructions from a mathematical claim.

A learner request, or the statement the router rewrites it into, can end with an instruction such
as "Write the proposition and the entire proof in English."  The independent proof review judges
the mathematical claim and whether the Lean proof establishes it; it must not treat the
instruction as part of the claim (a Lean artifact is never an English proof).  This module removes
such instructions by a closed table (``presentation-instructions-v1.json``) and returns them
separately.  Nothing outside the table is removed, and a method the learner requires (epsilon-delta,
induction, ...) is part of the claim.

The split is deterministic and idempotent.  The explanation stage keeps receiving the full
request, so the instructions still reach it (its output language is ``output_language``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Final

SCHEMA_VERSION: Final = "pals.presentation-instructions.v1"
_MIN_CLAIM_CHARS: Final = 3


@dataclass(frozen=True, slots=True)
class SplitStatement:
    """The claim without its instructions, and the instructions that were removed (in order)."""

    claim: str
    instructions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Table:
    patterns: tuple[tuple[str, re.Pattern[str], str], ...]
    lexicon_en: frozenset[str] = frozenset()
    lexicon_cjk: tuple[str, ...] = ()
    anchors_en: frozenset[str] = frozenset()
    anchors_cjk: tuple[str, ...] = ()


def build_table(payload: dict[str, Any]) -> _Table:
    """Compile a table (the packaged one, or one a test supplies)."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("presentation instruction table has an unexpected schema version")
    english = _alternation(payload["language_names_en"])
    cjk = _alternation(payload["language_names_cjk"])
    compiled: list[tuple[str, re.Pattern[str], str]] = []
    seen: set[str] = set()
    for row in payload["patterns"]:
        identifier = row["id"]
        if identifier in seen:
            raise RuntimeError("duplicate presentation instruction pattern id")
        seen.add(identifier)
        expanded = row["re"].replace("{LANG_EN}", english).replace("{LANG_CJK}", cjk)
        pattern = re.compile(expanded, re.IGNORECASE)
        if pattern.search("") is not None:
            raise RuntimeError("a presentation instruction pattern must not match the empty text")
        compiled.append((identifier, pattern, row.get("join", " ")))
    lexicon = payload.get("sentence_lexicon", {})
    return _Table(
        patterns=tuple(compiled),
        lexicon_en=frozenset(word.lower() for word in lexicon.get("en", ())),
        lexicon_cjk=tuple(sorted(set(lexicon.get("cjk", ())), key=len, reverse=True)),
        anchors_en=frozenset(word.lower() for word in lexicon.get("anchors_en", ())),
        anchors_cjk=tuple(lexicon.get("anchors_cjk", ())),
    )


def _alternation(names: list[str]) -> str:
    return "|".join(re.escape(name) for name in sorted(set(names), key=len, reverse=True))


@lru_cache(maxsize=1)
def _table() -> _Table:
    return build_table(
        json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("presentation-instructions-v1.json")
            .read_text(encoding="utf-8")
        )
    )


def split_presentation_instructions(
    statement: str, *, table: _Table | None = None
) -> SplitStatement:
    """``statement`` without its presentation/language/format instructions.

    When nothing would remain of the claim, the statement is returned unchanged.
    """
    if not isinstance(statement, str):
        raise TypeError("statement must be text")
    table = table or _table()
    # Whole instruction sentences first, then the instructions inside a sentence that also
    # carries the claim.
    text, removed = _strip_instruction_sentences(statement, table)
    for _identifier, pattern, join in table.patterns:
        for match in pattern.finditer(text):
            piece = _clean_instruction(match.group(0))
            if piece:
                removed.append(piece)
        text = pattern.sub(join, text)
    if not removed:
        return SplitStatement(claim=statement, instructions=())
    claim = _tidy(text)
    if len(re.sub(r"[\W_]", "", claim)) < _MIN_CLAIM_CHARS:
        return SplitStatement(claim=statement, instructions=())
    return SplitStatement(claim=claim, instructions=tuple(removed))


_SENTENCE = re.compile(r"[^.!?。！？\n]+(?:[.!?。！？]+|(?=\n)|$)|\n+")
# Anything that can carry mathematics: digits, operators, relations, brackets, set symbols.
_MATH_CHARACTER = re.compile(r"[0-9=^²³⁴-⁹+*/<>≤≥≠|√∑∫∞\[\]{}⟨⟩ℝℕℤℚℂ→↦∈∉∀∃∧∨¬×÷·∘′'`$\\_~]")
_GREEK = re.compile(r"[α-ωΑ-Ω]")
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ー]")


def _strip_instruction_sentences(text: str, table: _Table) -> tuple[str, list[str]]:
    """Remove whole sentences that only say how to present the answer.

    A sentence qualifies when it holds nothing but presentation vocabulary (the table's
    ``sentence_lexicon``), no digit, symbol or variable letter, and at least one anchor word
    (a language name, 'write', 'proof', '説明', ...).  A word outside the lexicon (a negation,
    a property, 'but', 'only', 'except') keeps the sentence.  At least one other sentence
    must remain, so a request that is only an instruction is left as it is.
    """
    if not table.lexicon_en and not table.lexicon_cjk:
        return text, []
    spans = [match for match in _SENTENCE.finditer(text) if match.group(0).strip()]
    flags = [_is_instruction_sentence(match.group(0), table) for match in spans]
    if not any(flags) or all(flags):
        return text, []
    pieces: list[str] = []
    removed: list[str] = []
    cursor = 0
    for match, is_instruction in zip(spans, flags, strict=True):
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
        if is_instruction:
            removed.append(_clean_instruction(match.group(0)))
            pieces.append(" ")
        else:
            pieces.append(match.group(0))
    pieces.append(text[cursor:])
    return "".join(pieces), removed


def _is_instruction_sentence(sentence: str, table: _Table) -> bool:
    body = sentence.strip().lower()
    if not body or _MATH_CHARACTER.search(body) or _GREEK.search(body):
        return False
    body = re.sub(r"(?<=[a-z])-(?=[a-z])", "", body)  # step-by-step
    cjk_hit = False
    for word in table.lexicon_cjk:
        if word in body:
            body = body.replace(word, " ")
            cjk_hit = cjk_hit or any(word == anchor for anchor in table.anchors_cjk)
    if _CJK.search(body):
        return False  # a CJK character outside the lexicon: part of a claim
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", body)
    if any(len(token) == 1 and token not in {"a", "i"} for token in tokens):
        return False  # a single-letter variable
    if any(token not in table.lexicon_en for token in tokens):
        return False
    return cjk_hit or any(token in table.anchors_en for token in tokens)


def _clean_instruction(piece: str) -> str:
    return re.sub(r"\s+", " ", piece).strip(" \t,;、，")


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+([.,;:!?。、，！？])", r"\1", text)
    # An instruction between two sentences leaves a stranded mark behind the first one.
    text = re.sub(r"([.!?。！？])[ \t]*[.,;、，。]+", r"\1", text)
    text = re.sub(r"(?m)^[ \t]*[.,;:、，：；]+[ \t]*", "", text)
    text = re.sub(r"[ \t]*[,;、，]+[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text.strip()
