import copy
import json
from pathlib import Path

import pytest

from pals_agent.evals.manifest import (
    BANNED_PATTERNS,
    assign_splits,
    split_checksum,
    stratum_counts,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[2] / "testdata" / "generation-eval-v1"


@pytest.fixture(scope="module")
def manifest():
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def frozen():
    return (ROOT / "SPLIT.sha256").read_text(encoding="utf-8").strip()


def test_manifest_is_valid_and_matches_frozen_checksum(manifest, frozen):
    assert validate_manifest(manifest, frozen) == []


def test_size_and_split(manifest):
    items = manifest["problems"]
    assert len(items) == 100
    assert len({p["id"] for p in items}) == 100
    counts = stratum_counts(manifest)
    assert counts["split"]["held_out"] == 30 and counts["split"]["tuning"] == 70


def test_every_stratum_axis_is_populated(manifest):
    counts = stratum_counts(manifest)
    assert set(counts["tier"]) == {"easy", "medium", "hard"}
    assert counts["tier"]["easy"] <= 30, "easy problems must not dominate"
    assert set(counts["language"]) == {"ja", "en"}
    assert len(counts["field"]) >= 12
    assert counts["history"]["exhausted-repairs"] >= 5
    assert counts["history"]["statement-mismatch"] >= 5


def test_held_out_has_every_tier_and_hard_problems(manifest):
    held = [p for p in manifest["problems"] if p["split"] == "held_out"]
    assert {p["tier"] for p in held} == {"easy", "medium", "hard"}
    assert any("exhausted-repairs" in p["history"] for p in held)


def test_banned_squared_binomial_is_absent(manifest):
    for p in manifest["problems"]:
        text = p["statement"] + (p.get("fixed_lean_statement") or "")
        assert not any(b.search(text) for b in BANNED_PATTERNS), p["id"]
        assert "binomial_square" not in p["id"]


def test_banned_pattern_catches_the_known_form():
    assert any(b.search("(x + y)^2 = x^2 + 2xy + y^2") for b in BANNED_PATTERNS)
    assert not any(b.search("x^2 + y^2 >= 2xy") for b in BANNED_PATTERNS)


def test_shared_prompt_quality_subset(manifest):
    shared = [p for p in manifest["problems"] if p.get("shared")]
    assert len(shared) == 18
    codex = json.loads((ROOT / "codex_shared_problems.json").read_text(encoding="utf-8"))[
        "problems"
    ]
    by_id = {c["id"]: c for c in codex}
    for p in shared:
        c = by_id[p["shared"]["prompt_quality_id"]]
        assert p["shared"]["fixture_sha256"] == c["fixture_sha256"]
        assert p["statement"] == c["statement"]
        assert p["id"] == f"pq-{c['id']}"
    assert {c["id"] for c in codex if str(c["requires_lean"]).lower() != "true"} == {
        "continuity-quantifier-meaning",
        "pointwise-uniform-quantifier-meaning",
    }


def test_expected_answers_only_on_decision_items(manifest):
    with_answer = [p for p in manifest["problems"] if p["expected_answer"]]
    assert with_answer and all("computation" in p["tags"] for p in with_answer)


def test_changing_a_split_breaks_the_freeze(manifest, frozen):
    bad = copy.deepcopy(manifest)
    p = next(p for p in bad["problems"] if p["split"] == "tuning")
    p["split"] = "held_out"
    errors = validate_manifest(bad, frozen)
    assert any("frozen" in e or "deterministic" in e or "held-out size" in e for e in errors)


def test_editing_a_statement_is_detected(manifest, frozen):
    bad = copy.deepcopy(manifest)
    bad["problems"][0]["statement"] += " (edited)"
    assert any("statement_sha256" in e for e in validate_manifest(bad, frozen))


def test_duplicate_id_and_banned_material_are_rejected(manifest):
    bad = copy.deepcopy(manifest)
    bad["problems"].append(copy.deepcopy(bad["problems"][0]))
    assert any("duplicate id" in e for e in validate_manifest(bad))
    worse = copy.deepcopy(manifest)
    worse["problems"][0]["statement"] = "Show (x + y)^2 = x^2 + 2xy + y^2."
    assert any("banned" in e for e in validate_manifest(worse))


def test_split_assignment_is_deterministic_and_stratified(manifest):
    a = [dict(p) for p in manifest["problems"]]
    b = [dict(p) for p in reversed(manifest["problems"])]
    assign_splits(a)
    assign_splits(b)
    assert {p["id"]: p["split"] for p in a} == {p["id"]: p["split"] for p in b}
    assert split_checksum(a) == manifest["split_checksum"]
