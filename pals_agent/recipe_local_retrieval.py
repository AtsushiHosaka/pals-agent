"""Bounded local candidate ranking, never mathematical correspondence evidence.

Fresh full catalog statements define the vocabulary. No topic aliases, question
patterns, model calls, cache or proof/answer changes are part of retrieval.
"""

from __future__ import annotations

import collections
import math
import unicodedata
from typing import Any

K = 5


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _features(text: str) -> collections.Counter[str]:
    return collections.Counter(
        text[i : i + n] for n in (2, 3, 4) for i in range(max(0, len(text) - n + 1))
    )


def _norm(vector: dict[str, float]) -> float:
    return math.sqrt(math.fsum(value * value for value in vector.values()))


def rank(rows: list[dict[str, Any]], original_question: str) -> tuple[str, ...]:
    """Return up to five entry pins from already validated complete catalog rows.

    Normalization affects ranking only: reviewers receive the untouched original
    question, all selected mathematical fields, Lean source and stored answer.
    """
    if not 1 <= len(rows) <= 32:
        raise ValueError("local_retrieval_count_invalid")
    ordered = sorted(rows, key=lambda row: row["entry_sha256"])
    pins = [row["entry_sha256"] for row in ordered]
    if len(set(pins)) != len(pins):
        raise ValueError("local_retrieval_duplicate_entry")
    for row in ordered:
        pin = row["entry_sha256"]
        if (
            not isinstance(pin, str)
            or len(pin) != 64
            or any(c not in "0123456789abcdef" for c in pin)
            or not isinstance(row["statement"], str)
            or not row["statement"].strip()
            or len(row["statement"].encode()) > 80000
        ):
            raise ValueError("local_retrieval_input_invalid")
    if (
        not isinstance(original_question, str)
        or not original_question.strip()
        or len(original_question.encode()) > 20000
    ):
        raise ValueError("local_retrieval_query_invalid")
    counts = [_features(_normalize(row["statement"])) for row in ordered]
    frequency = collections.Counter(term for count in counts for term in count)
    idf = {term: math.log((len(rows) + 1) / (count + 1)) + 1 for term, count in frequency.items()}
    vectors = [{term: count * idf[term] for term, count in row.items()} for row in counts]
    norms = [_norm(vector) for vector in vectors]
    # Single-character statements are valid catalog text but have no 2–4-grams.
    # They receive zero scores and the same deterministic entry-hash tie break.
    query_counts = _features(_normalize(original_question))
    query = {term: count * idf[term] for term, count in query_counts.items() if term in idf}
    query_norm = _norm(query)
    scores = []
    for pin, vector, norm in zip(pins, vectors, norms, strict=True):
        score = (
            math.fsum(value * vector.get(term, 0) for term, value in query.items())
            / (query_norm * norm)
            if query_norm and norm
            else 0.0
        )
        if not math.isfinite(score):
            raise ValueError("local_retrieval_score_invalid")
        scores.append((pin, score))
    scores.sort(key=lambda row: (-row[1], row[0]))
    return tuple(pin for pin, _ in scores[: min(K, len(rows))])
