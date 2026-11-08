"""Proof-pattern exemplars for the hint A/B harness (experiment only, never production).

The production Draft prompt already carries prose strategy notes of retrieved related Drafts.
It never shows the Lean proof of a catalog Recipe.  This module selects one to three verified
catalog proofs of *other* theorems and renders them as worked examples of technique.

Leak control is the point of the module.  A selected exemplar must not be the target, a
version or reuse variant of the target, or a statement of the same general form, because then
the model could copy the answer and the measurement would say nothing about transfer.
``select_exemplars`` therefore drops, before ranking:

* the card with the target's id and every card with the same id stem (``calculus_v2_x`` and
  ``calculus_v5_x`` share the stem ``x``);
* every card whose Lean statement uses nearly the same constants as the target
  (overlap coefficient at or above ``OVERLAP_LIMIT``), or whose English statement is a
  near-duplicate of the target's;
* every card whose proof text equals one of the target's known proof texts.

These rules are deliberately broad.  They can only remove candidates, never add them.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

EXEMPLAR_HEADER = """
Verified Lean proofs of different theorems from the catalog, shown only as examples of proof
technique and Lean style. They are not the target and not a harness, and their statements differ
from yours. Adapt the technique only where it fits. Lean verification decides.
"""

# Overlap of statement constants at or above this means "same general form": excluded.
OVERLAP_LIMIT = 0.6
# English statements this similar (Jaccard on content words) are treated as the same card.
ENGLISH_DUPLICATE_LIMIT = 0.6
MAX_PROOF_CHARS = 1800

_MARKER = re.compile(r"^-- manifest card: (\S+)\s*$", re.MULTILINE)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_.']*")
_ENGLISH_WORD = re.compile(r"[a-z]{3,}")
_STEM_PREFIX = re.compile(
    r"^(?:[a-z]+(?:_[a-z]+)*?)_(?:v\d+|reuse|foundation)_|^(?:[a-z]+)_(?:v\d+|reuse|foundation)_"
)
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "then",
        "from",
        "into",
        "over",
        "under",
        "are",
        "has",
        "have",
        "all",
        "any",
        "each",
        "there",
        "such",
        "which",
        "where",
        "when",
        "only",
        "exists",
        "exist",
        "some",
        "than",
        "not",
        "its",
        "their",
        "one",
        "two",
        "let",
    }
)
# Binder and hypothesis names carry no information about the theorem's form.
_LOCAL_NAME = re.compile(r"^(?:[a-zA-Z]\d*|h[A-Za-z0-9_']*|[a-z]{1,2})$")


@dataclass(frozen=True, slots=True)
class CatalogCard:
    id: str
    statement: str
    lean: str

    @property
    def lean_statement(self) -> str:
        head, _separator, _tail = self.lean.partition(":=")
        return head

    @property
    def proof(self) -> str:
        _head, _separator, tail = self.lean.partition(":=")
        return tail.strip()


def load_catalog(docs_dir: Path) -> list[CatalogCard]:
    """Cards that have both a canonical statement (JSON) and a Lean proof (sibling .lean)."""

    cards: list[CatalogCard] = []
    for json_path in sorted(docs_dir.glob("*-batch.json")):
        lean_path = json_path.with_suffix(".lean")
        if not lean_path.exists():
            continue
        data = json.loads(json_path.read_text(encoding="utf-8"))
        listing = data["cards"] if isinstance(data, dict) else data
        statements = {card["id"]: str(card.get("canonical_statement", "")) for card in listing}
        text = lean_path.read_text(encoding="utf-8")
        markers = list(_MARKER.finditer(text))
        for position, marker in enumerate(markers):
            end = markers[position + 1].start() if position + 1 < len(markers) else len(text)
            lean = text[marker.end() : end].strip()
            card_id = marker.group(1)
            if lean and card_id in statements:
                cards.append(CatalogCard(card_id, statements[card_id], lean))
    return cards


def id_stem(card_id: str) -> str:
    return _STEM_PREFIX.sub("", card_id, count=1)


def lean_constants(lean_statement: str) -> frozenset[str]:
    """Identifiers of a Lean statement, minus binder and hypothesis names."""

    names = {token for token in _WORD.findall(lean_statement) if not _LOCAL_NAME.match(token)}
    return frozenset(names - {"example", "theorem", "lemma", "by", "fun", "True", "False"})


def english_words(text: str) -> frozenset[str]:
    return frozenset(w for w in _ENGLISH_WORD.findall(text.lower()) if w not in _STOP)


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True, slots=True)
class Target:
    id: str
    statement: str
    formal_statement: str
    known_proofs: tuple[str, ...] = ()


def _normalized(text: str) -> str:
    return " ".join(text.split())


def exclusion_reason(target: Target, card: CatalogCard) -> str | None:
    """Why ``card`` may not be shown for ``target``; ``None`` when it is acceptable."""

    if card.id == target.id:
        return "same_id"
    target_stem = id_stem(target.id)
    if target_stem and id_stem(card.id) == target_stem:
        return "same_stem"
    target_constants = lean_constants(target.formal_statement)
    card_constants = lean_constants(card.lean_statement)
    limit = OVERLAP_LIMIT
    if min(len(target_constants), len(card_constants)) < 3:
        # Too few constants to compare by overlap: a small set is easily contained in another.
        if _jaccard(target_constants, card_constants) >= limit:
            return "same_form"
    elif _overlap(target_constants, card_constants) >= limit:
        return "same_form"
    if (
        _jaccard(english_words(target.statement), english_words(card.statement))
        >= ENGLISH_DUPLICATE_LIMIT
    ):
        return "same_statement"
    proof = _normalized(card.proof)
    if proof and any(proof == _normalized(known) for known in target.known_proofs):
        return "same_proof"
    return None


def _vector(constants: frozenset[str], words: frozenset[str]) -> Counter[str]:
    vector: Counter[str] = Counter()
    for name in constants:
        vector["L:" + name] += 2.0
    for word in words:
        vector["E:" + word] += 1.0
    return vector


def select_exemplars(
    target: Target, catalog: list[CatalogCard], *, k: int = 2
) -> list[CatalogCard]:
    """The ``k`` most similar acceptable cards, most similar first."""

    document_frequency: Counter[str] = Counter()
    vectors: dict[str, Counter[str]] = {}
    for card in catalog:
        vector = _vector(lean_constants(card.lean_statement), english_words(card.statement))
        vectors[card.id] = vector
        document_frequency.update(vector.keys())
    total = len(catalog)

    def weight(vector: Counter[str]) -> dict[str, float]:
        return {
            term: count * math.log((1 + total) / (1 + document_frequency[term]) + 1.0)
            for term, count in vector.items()
        }

    query = weight(
        _vector(lean_constants(target.formal_statement), english_words(target.statement))
    )
    query_norm = math.sqrt(sum(value * value for value in query.values())) or 1.0
    scored: list[tuple[float, str, CatalogCard]] = []
    for card in catalog:
        if exclusion_reason(target, card) is not None:
            continue
        document = weight(vectors[card.id])
        norm = math.sqrt(sum(value * value for value in document.values())) or 1.0
        dot = sum(value * document.get(term, 0.0) for term, value in query.items())
        scored.append((dot / (query_norm * norm), card.id, card))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [card for _score, _id, card in scored[:k]]


def render_exemplars(cards: list[CatalogCard]) -> str:
    if not cards:
        return ""
    blocks = []
    for number, card in enumerate(cards, start=1):
        lean = card.lean
        if len(lean) > MAX_PROOF_CHARS:
            lean = lean[:MAX_PROOF_CHARS] + "\n-- (truncated)"
        blocks.append(f"Example {number}: {card.statement}\n```lean\n{lean}\n```")
    return EXEMPLAR_HEADER + "\n" + "\n\n".join(blocks) + "\n"
