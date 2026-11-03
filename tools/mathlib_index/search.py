"""Model-free candidate search over the Mathlib statement index.

Results are unverified candidates. They never establish that a theorem applies or that two
statements agree: only Lean can decide that.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mathlib_index.build_index import name_tokens
from tools.mathlib_index.tiers import SEARCHABLE_CORE, SEARCHABLE_FULL

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "over",
        "such",
        "that",
        "the",
        "then",
        "there",
        "this",
        "to",
        "with",
        "let",
        "any",
        "every",
        "each",
        "all",
        "has",
        "have",
        "than",
        "which",
        "when",
        "where",
        "we",
        "show",
        "prove",
        "given",
    ]
)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_LEAN_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_'.]*")
_LEAN_KEYWORDS = frozenset(
    [
        "example",
        "theorem",
        "lemma",
        "fun",
        "by",
        "exact",
        "have",
        "let",
        "at",
        "in",
        "from",
        "show",
        "calc",
        "Type",
        "Sort",
        "Prop",
    ]
)
_NOTATION_WORDS = {
    "∫": "integral",
    "∑": "sum",
    "∏": "product",
    "≤": "le",
    "<": "lt",
    "∣": "dvd",
    "⊆": "subset",
    "∩": "inter",
    "∪": "union",
    "∘": "comp",
    "√": "sqrt",
    "⁻¹": "inv",
    "•": "smul",
    "ℝ": "real",
    "ℂ": "complex",
    "ℚ": "rat",
    "ℤ": "int",
    "ℕ": "nat",
}
DEFAULT_WEIGHTS = (8.0, 3.0, 1.0)
COMMON_CONSTANT_IDF = 2.5


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    score: float


def natural_query_terms(text: str) -> list[str]:
    terms = [word.lower() for word in _WORD.findall(text)]
    return [term for term in terms if len(term) > 1 and term not in STOPWORDS]


def lean_query_terms(source: str) -> list[str]:
    terms: list[str] = []
    for identifier in _LEAN_IDENT.findall(source):
        if identifier not in _LEAN_KEYWORDS and len(identifier) > 1:
            terms.extend(name_tokens(identifier).split())
    for symbol, word in _NOTATION_WORDS.items():
        if symbol in source:
            terms.append(word)
    return [term for term in terms if term not in STOPWORDS]


class MathlibIndex:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    @staticmethod
    def _tiers(scope: str) -> frozenset[str]:
        return SEARCHABLE_CORE if scope == "core" else SEARCHABLE_FULL

    def text_search(
        self,
        terms: list[str],
        *,
        k: int = 20,
        scope: str = "core",
        weights: tuple[float, float, float] = DEFAULT_WEIGHTS,
    ) -> list[Candidate]:
        unique = list(dict.fromkeys(terms))
        if not unique:
            return []
        match = " OR ".join('"' + term.replace('"', "") + '"' for term in unique)
        tiers = sorted(self._tiers(scope))
        marks = ",".join("?" * len(tiers))
        rows = self._db.execute(
            f"SELECT d.name, bm25(decl_fts, ?, ?, ?) AS rank FROM decl_fts "
            f"JOIN decl d ON d.id = decl_fts.rowid "
            f"WHERE decl_fts MATCH ? AND d.tier IN ({marks}) ORDER BY rank LIMIT ?",
            (*weights, match, *tiers, k),
        ).fetchall()
        return [Candidate(name, -rank) for name, rank in rows]

    @cached_property
    def _symbols(
        self,
    ) -> tuple[list[str], list[str], list[float], dict[str, list[tuple[int, bool]]]]:
        names: list[str] = []
        tiers: list[str] = []
        mass_input: list[set[str]] = []
        postings: dict[str, list[tuple[int, bool]]] = defaultdict(list)
        rows = self._db.execute(
            "SELECT name, tier, conclusion_constants, hypothesis_constants FROM decl"
        )
        for doc_id, (name, tier, conclusion, hypotheses) in enumerate(rows):
            names.append(name)
            tiers.append(tier)
            conclusion_set = set(json.loads(conclusion))
            hypothesis_set = set(json.loads(hypotheses)) - conclusion_set
            for constant in conclusion_set:
                postings[constant].append((doc_id, True))
            for constant in hypothesis_set:
                postings[constant].append((doc_id, False))
            mass_input.append(conclusion_set | hypothesis_set)
        total = len(names)
        self._idf = {constant: math.log(total / len(docs)) for constant, docs in postings.items()}
        masses = [sum(self._idf[c] for c in constants) for constants in mass_input]
        return names, tiers, masses, postings

    def symbol_search(
        self,
        conclusion_constants: list[str],
        hypothesis_constants: list[str],
        *,
        k: int = 20,
        scope: str = "core",
        hypothesis_weight: float = 0.5,
    ) -> list[Candidate]:
        """Rank by IDF-weighted overlap of constants taken from the Lean-elaborated statement."""
        names, tiers, masses, postings = self._symbols
        allowed = self._tiers(scope)
        conclusion = set(conclusion_constants)
        hypotheses = set(hypothesis_constants) - conclusion
        overlap: dict[int, float] = defaultdict(float)
        query_mass = 0.0
        for constant, weight in [(c, 1.0) for c in conclusion] + [
            (c, hypothesis_weight) for c in hypotheses
        ]:
            idf = self._idf.get(constant)
            if idf is None:
                continue
            query_mass += idf * weight
            # Constants as common as `Eq` barely discriminate and dominate the running time.
            if idf < COMMON_CONSTANT_IDF:
                continue
            for doc_id, in_conclusion in postings[constant]:
                overlap[doc_id] += idf * weight * (1.0 if in_conclusion else 0.5)
        scored = [
            Candidate(names[doc_id], value / (query_mass + masses[doc_id] - value + 1e-9))
            for doc_id, value in overlap.items()
            if tiers[doc_id] in allowed
        ]
        scored.sort(key=lambda candidate: (-candidate.score, candidate.name))
        return scored[:k]

    def describe(self, names: list[str]) -> list[dict[str, str | None]]:
        results = []
        for name in names:
            row = self._db.execute(
                "SELECT name, type, module, doc FROM decl WHERE name = ?", (name,)
            ).fetchone()
            if row:
                results.append({"name": row[0], "type": row[1], "module": row[2], "doc": row[3]})
        return results


def reciprocal_rank_fusion(
    rankings: list[list[Candidate]], *, k: int = 20, constant: float = 60.0
) -> list[Candidate]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, candidate in enumerate(ranking):
            scores[candidate.name] += 1.0 / (constant + rank + 1)
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [Candidate(name, score) for name, score in ordered[:k]]
