"""Candidate ranking tests; no mathematical admission or provider behavior is simulated here."""

import hashlib

import pytest

from pals_agent.recipe_local_retrieval import rank


def rows(count):
    return [
        {
            "entry_sha256": hashlib.sha256(f"synthetic-catalog-entry-{i}".encode()).hexdigest(),
            "statement": f"定理 {i} について、コンパクト集合上の連続関数は最大値を持つ。",
        }
        for i in range(count)
    ]


@pytest.mark.parametrize("count", [1, 2, 5, 6, 20, 32])
def test_bounded_catalog_returns_unique_minimum_five_owned_pins(count):
    candidates = rows(count)
    selected = rank(candidates, candidates[-1]["statement"])
    assert len(selected) == min(5, count) and len(set(selected)) == len(selected)
    assert set(selected) <= {row["entry_sha256"] for row in candidates}
    assert selected == rank(list(reversed(candidates)), candidates[-1]["statement"])
    assert selected[0] == candidates[-1]["entry_sha256"]


def test_oov_and_single_character_zero_vectors_use_deterministic_hash_tie_break():
    candidates = rows(8)
    expected = tuple(sorted(row["entry_sha256"] for row in candidates)[:5])
    assert rank(candidates, "🦜") == expected
    assert rank([{**r, "statement": "π"} for r in candidates], "π") == expected


def test_normalization_is_only_for_retrieval_and_does_not_mutate_original_inputs():
    candidates = rows(6)
    candidates[0]["statement"] = "ＳＥＱＵＥＮＣＥ　の収束"
    query = "sequence  の収束"
    before = [dict(row) for row in candidates]
    assert rank(candidates, query)[0] == candidates[0]["entry_sha256"]
    assert candidates == before and query == "sequence  の収束"


def test_each_fresh_catalog_change_rebuilds_rank_without_cross_claim_result_cache():
    candidates = rows(6)
    question = "uniform convergence metric sequence"
    candidates[0]["statement"] = question
    assert rank(candidates, question)[0] == candidates[0]["entry_sha256"]
    candidates[0]["statement"] = "異なる定理"
    candidates[1]["statement"] = question
    assert rank(candidates, question)[0] == candidates[1]["entry_sha256"]


@pytest.mark.parametrize("count", [0, 33])
def test_out_of_contract_catalog_size_is_refused(count):
    with pytest.raises(ValueError):
        rank(rows(count), "点列の収束")


def test_duplicate_entries_and_invalid_or_oversized_text_are_refused():
    candidate = rows(1)[0]
    for changed in (
        [candidate, candidate],
        [{**candidate, "entry_sha256": "not-a-hash"}],
        [{**candidate, "statement": " "}],
        [{**candidate, "statement": "a" * 80001}],
    ):
        with pytest.raises(ValueError):
            rank(changed, "点列の収束")
    with pytest.raises(ValueError):
        rank([candidate], "a" * 20001)
