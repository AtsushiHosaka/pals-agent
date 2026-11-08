"""Leak control of the proof-exemplar selection used by the hint A/B harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.mathlib_index.exemplars import (
    CatalogCard,
    Target,
    exclusion_reason,
    id_stem,
    load_catalog,
    render_exemplars,
    select_exemplars,
)

DERIV = "example (f : ℝ → ℝ) (a u : ℝ) (hf : HasDerivAt f u a) (hm : Monotone f) : 0 ≤ u"
TARGET = Target(
    id="calculus_v5_convex_derivative_monotone",
    statement="A convex differentiable real function has a monotone derivative.",
    formal_statement=(
        "theorem pals_card_target (f : ℝ → ℝ) (hc : ConvexOn ℝ Set.univ f) "
        "(hf : Differentiable ℝ f) : Monotone (deriv f)"
    ),
)


def card(card_id: str, statement: str, lean: str) -> CatalogCard:
    return CatalogCard(card_id, statement, lean)


UNRELATED = card(
    "calculus_v2_nonnegative_derivative_monotone",
    "If f has derivative g and g is nonnegative everywhere then f is monotone.",
    "example (f g : ℝ → ℝ) (hg : ∀ x, HasDerivAt f (g x) x) (h : ∀ x, 0 ≤ g x) : Monotone f := by\n"
    "  exact monotone_of_deriv_nonneg (fun x => (hg x).differentiableAt) (fun x => by simpa"
    " [(hg x).deriv] using h x)",
)


def test_target_itself_is_never_selected() -> None:
    own = card(
        TARGET.id,
        TARGET.statement,
        "example (f : ℝ → ℝ) (hc : ConvexOn ℝ Set.univ f) (hf : Differentiable ℝ f) : "
        "Monotone (deriv f) := by\n  exact answer",
    )
    assert exclusion_reason(TARGET, own) == "same_id"
    chosen = select_exemplars(TARGET, [own, UNRELATED], k=2)
    assert [c.id for c in chosen] == [UNRELATED.id]
    assert "answer" not in render_exemplars(chosen)


def test_other_version_of_the_same_card_is_excluded() -> None:
    older = card(
        "calculus_v3_convex_derivative_monotone",
        "Convex differentiable functions have monotone derivatives (older wording).",
        "example : True := by\n  trivial",
    )
    assert id_stem(older.id) == id_stem(TARGET.id) == "convex_derivative_monotone"
    assert exclusion_reason(TARGET, older) == "same_stem"


def test_same_form_with_renamed_variables_and_new_id_is_excluded() -> None:
    twin = card(
        "analysis_v9_slope_monotonicity",
        "Slopes of a convex smooth map increase.",
        "example (g : ℝ → ℝ) (k : ConvexOn ℝ Set.univ g) (d : Differentiable ℝ g) : "
        "Monotone (deriv g) := by\n  exact twin_proof",
    )
    assert exclusion_reason(TARGET, twin) == "same_form"
    chosen = select_exemplars(TARGET, [twin, UNRELATED], k=2)
    assert twin.id not in [c.id for c in chosen]
    assert "twin_proof" not in render_exemplars(chosen)


def test_english_duplicate_with_different_lean_is_excluded() -> None:
    reworded = card(
        "other_v1_duplicate",
        "A convex differentiable real function has a monotone derivative!",
        "example (f : ℝ → ℝ) : True := by\n  trivial",
    )
    assert exclusion_reason(TARGET, reworded) == "same_statement"


def test_identical_known_proof_is_excluded() -> None:
    target = Target(
        TARGET.id,
        TARGET.statement,
        TARGET.formal_statement,
        known_proofs=("by  exact   shared",),
    )
    shared = card(
        "zz_v1_unrelated", "Something else entirely.", "example : 1 = 1 := by exact shared"
    )
    assert exclusion_reason(target, shared) == "same_proof"


def test_unrelated_card_is_acceptable_and_ranked_by_similarity() -> None:
    near = card(
        "calculus_v4_deriv_monotone_converse",
        "Nondecreasing maps with a pointwise slope have a nonnegative slope.",
        DERIV + " := by\n  simpa only [hf.deriv] using hm.deriv_nonneg",
    )
    far = card(
        "la_v1_trace_cyclic",
        "Trace of a matrix product is cyclic.",
        "example (A B : Matrix (Fin 2) (Fin 2) ℝ) : (A * B).trace = (B * A).trace := by\n"
        "  exact Matrix.trace_mul_comm A B",
    )
    assert exclusion_reason(TARGET, near) is None
    assert [c.id for c in select_exemplars(TARGET, [far, near], k=2)][0] == near.id


def test_selection_is_deterministic_and_bounded_by_k() -> None:
    catalog = [
        card(
            f"zz_v1_card{i}",
            f"Statement number {i} about monotone derivative.",
            DERIV + " := by\n  simp",
        )
        for i in range(5)
    ]
    first = select_exemplars(TARGET, catalog, k=2)
    assert len(first) == 2
    assert first == select_exemplars(TARGET, list(reversed(catalog)), k=2)


def test_render_is_empty_without_cards_and_truncates_long_proofs() -> None:
    assert render_exemplars([]) == ""
    long_card = card("zz_v1_long", "Long.", "example : True := by\n" + "  trivial\n" * 1000)
    assert "(truncated)" in render_exemplars([long_card])


def test_load_catalog_pairs_json_statements_with_lean_blocks(tmp_path: Path) -> None:
    (tmp_path / "x-batch.json").write_text(
        json.dumps({"cards": [{"id": "x_v1_a", "canonical_statement": "A."}, {"id": "x_v1_b"}]}),
        encoding="utf-8",
    )
    (tmp_path / "x-batch.lean").write_text(
        "import Mathlib\n\n-- manifest card: x_v1_a\nexample : True := by trivial\n\n"
        "-- manifest card: x_v1_b\nexample : 1 = 1 := rfl\n",
        encoding="utf-8",
    )
    (tmp_path / "orphan-batch.json").write_text(json.dumps({"cards": []}), encoding="utf-8")
    loaded = {c.id: c for c in load_catalog(tmp_path)}
    assert set(loaded) == {"x_v1_a", "x_v1_b"}
    assert loaded["x_v1_a"].statement == "A."
    assert loaded["x_v1_a"].lean == "example : True := by trivial"


DOCS = Path(__file__).resolve().parents[2] / "docs"


@pytest.mark.skipif(
    not (DOCS / "calculus-v5-batch.lean").exists(), reason="parent docs not present"
)
def test_real_catalog_never_offers_the_target_or_its_siblings() -> None:
    catalog = load_catalog(DOCS)
    assert len(catalog) > 100
    for target_card in catalog[:: max(1, len(catalog) // 40)]:
        target = Target(target_card.id, target_card.statement, target_card.lean_statement)
        for chosen in select_exemplars(target, catalog, k=3):
            assert chosen.id != target.id
            assert id_stem(chosen.id) != id_stem(target.id)
            assert exclusion_reason(target, chosen) is None
