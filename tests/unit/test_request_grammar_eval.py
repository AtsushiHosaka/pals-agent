"""Blind adversarial corpus for the request -> Lean proposition grammar.

The corpus (``tests/fixtures/request_grammar_eval_v1.json``) was written without reading the
grammar. Every item has a gold proposition or ``null`` (the request must be a miss). The test
reports and asserts

* ``false_positives == 0``: a non-miss whose proposition differs from gold, or any non-miss where
  gold is ``null``. This is the dangerous failure: a verified proof of a different claim.
* coverage = positives parsed correctly / positives, over the scopes in ``EVALUATED_SCOPES``.

Items carry ``scope``: ``current`` (power + continuity, the table that is deployed) or
``widened`` (exp, sin, cos, |x|, sqrt, c*x, a*x+b and the wider property set). To evaluate the
widened grammar, set ``EVALUATED_SCOPES = ("current", "widened")`` and raise the coverage floor.

Bound-variable names and whitespace are ignored when comparing propositions.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest

from pals_agent.request_proposition import parse_request

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "request_grammar_eval_v1.json"

# Flip to ("current", "widened") once the widened vocabulary is merged.
EVALUATED_SCOPES: tuple[str, ...] = ("current", "widened")
# False positives in the unambiguous categories (a_positive parsed to a different proposition,
# b_near_miss parsed at all). This must stay 0.
MAX_FALSE_POSITIVES = 0
# Accepted requests whose gold is "ambiguous" (c_ambiguous, conservative gold = miss). Baseline of
# the current grammar; drive it to 0 by tightening the variable-letter and function-name rules.
MAX_AMBIGUOUS_ACCEPTS = 0
# Positives (in EVALUATED_SCOPES) parsed to exactly the gold proposition. Measured 0.532 on the
# current grammar (58/109); raise it as the vocabulary and the filler rules widen.
MIN_COVERAGE = 0.95


def load_corpus() -> list[dict[str, Any]]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


_BINDER = re.compile(r"fun\s+(\w+)\s*:\s*ℝ\s*=>")


def canonical(proposition: str) -> str:
    """Whitespace-insensitive, alpha-equivalent form (the first binder is renamed to ``x``)."""
    text = re.sub(r"\s+", " ", proposition.strip())
    binder = _BINDER.search(text)
    if binder and binder.group(1) != "x":
        name = binder.group(1)
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", "x", text)
    return text


def evaluate(items: list[dict[str, Any]]) -> dict[str, Any]:
    false_positives: list[dict[str, Any]] = []
    ambiguous_accepts: list[dict[str, Any]] = []
    positives = parsed = 0
    by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [parsed correctly, total]
    by_subcategory: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses: list[dict[str, Any]] = []
    for item in items:
        result = parse_request(item["text"])
        produced = None if result is None else result.proposition
        gold = item["gold"]
        if produced is not None and (gold is None or canonical(produced) != canonical(gold)):
            bucket = ambiguous_accepts if item["category"] == "c_ambiguous" else false_positives
            bucket.append({**item, "produced": produced})
            continue
        if gold is None:
            continue
        in_scope = item["scope"] in EVALUATED_SCOPES
        correct = produced is not None
        if in_scope:
            positives += 1
            parsed += correct
            for table, key in (
                (by_category, item["category"]),
                (by_subcategory, item["subcategory"]),
            ):
                table[key][1] += 1
                table[key][0] += correct
        if not correct:
            misses.append(item)
    return {
        "false_positives": false_positives,
        "ambiguous_accepts": ambiguous_accepts,
        "positives": positives,
        "parsed": parsed,
        "coverage": parsed / positives if positives else 1.0,
        "by_category": dict(by_category),
        "by_subcategory": dict(by_subcategory),
        "misses": misses,
    }


def test_corpus_shape() -> None:
    items = load_corpus()
    assert len({item["id"] for item in items}) == len(items)
    assert len({item["text"] for item in items}) == len(items)
    categories = Counter(item["category"] for item in items)
    assert set(categories) == {"a_positive", "b_near_miss", "c_ambiguous"}
    for item in items:
        assert item["scope"] in {"current", "widened"}
        assert item["note"]
        if item["category"] == "a_positive":
            assert isinstance(item["gold"], str) and item["gold"]
        else:
            assert item["gold"] is None
    assert sum(1 for item in items if item["adversarial"]) >= 60


def test_grammar_has_no_false_positives_and_covers_positives(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = evaluate(load_corpus())
    with capsys.disabled():
        print(f"\nrequest grammar eval: scopes={EVALUATED_SCOPES}")
        print(f"  false_positives = {len(report['false_positives'])}")
        print(f"  ambiguous_accepts = {len(report['ambiguous_accepts'])}")
        print(f"  coverage = {report['parsed']}/{report['positives']} = {report['coverage']:.3f}")
        for name, (ok, total) in sorted(report["by_category"].items()):
            print(f"  category {name}: {ok}/{total}")
        for name, (ok, total) in sorted(report["by_subcategory"].items()):
            print(f"  subcategory {name}: {ok}/{total}")
        for fp in report["false_positives"] + report["ambiguous_accepts"]:
            print(
                f"  ACCEPTED {fp['category']} {fp['id']}: {fp['text']!r} -> {fp['produced']!r}"
                f" (gold {fp['gold']!r})"
            )
    assert len(report["false_positives"]) <= MAX_FALSE_POSITIVES, report["false_positives"]
    assert len(report["ambiguous_accepts"]) <= MAX_AMBIGUOUS_ACCEPTS, report["ambiguous_accepts"]
    assert report["coverage"] >= MIN_COVERAGE, (report["parsed"], report["positives"])
