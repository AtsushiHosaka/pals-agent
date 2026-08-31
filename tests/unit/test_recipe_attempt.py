from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest

from pals_agent.private_recipe_selection import (
    RecipeExclusion,
    RecipeNotSelected,
    RecipeSelected,
    ToolchainFingerprintV1,
)
from pals_agent.recipe_attempt import (
    NoRecipeAttemptV1,
    RecipeAttemptPlannerV1,
    RecipeAttemptV1,
)


def _digest(character: str) -> str:
    return character * 64


_TOOLCHAIN = ToolchainFingerprintV1(
    lean_version="v4.19.0",
    lake_manifest_sha256=_digest("a"),
    verifier_sha256=_digest("b"),
    materializer_version="recipe-materializer-v1",
)
_SOURCE = "import Mathlib\n\nexample : True := by\n  trivial\n"


def _selected(*, target_sha256: str | None = None) -> RecipeSelected:
    return RecipeSelected(
        recipe_id="recipe.square-v1",
        recipe_revision=1,
        alignment_id="alignment.square-v1",
        alignment_revision=1,
        target_sha256=target_sha256 or hashlib.sha256(b"True").hexdigest(),
        materialized_source=_SOURCE,
        materialized_source_sha256=hashlib.sha256(_SOURCE.encode("utf-8")).hexdigest(),
        toolchain_fingerprint=_TOOLCHAIN,
        toolchain_fingerprint_sha256=_TOOLCHAIN.sha256,
        compiler_receipt_sha256=_digest("c"),
        source_author_principal="pals.principal.v1/recipe-author/local",
        selection_payload_sha256=_digest("d"),
        selection_receipt_sha256=_digest("e"),
    )


@dataclass
class _Selector:
    result: RecipeSelected | RecipeNotSelected
    calls: int = 0

    def select(self, query: object) -> RecipeSelected | RecipeNotSelected:
        del query
        self.calls += 1
        return self.result


def test_selected_recipe_keeps_the_exact_source_bytes_and_closed_binding() -> None:
    selector = _Selector(_selected())
    decision = RecipeAttemptPlannerV1(selector, _TOOLCHAIN).decide(
        formal_declaration="example : True := by trivial"
    )

    assert isinstance(decision, RecipeAttemptV1)
    assert selector.calls == 1
    assert decision.source_bytes == _SOURCE.encode("utf-8")
    assert decision.source == _SOURCE
    assert decision.source_sha256 == hashlib.sha256(_SOURCE.encode("utf-8")).hexdigest()
    assert decision.candidate_source_payload() == {
        "schema_version": "pals.candidate-source.v2",
        "candidate_source": "recipe",
        "recipe_id": "recipe.square-v1",
        "recipe_revision": 1,
        "alignment_id": "alignment.square-v1",
        "alignment_revision": 1,
        "selection_payload_sha256": _digest("d"),
        "selection_receipt_sha256": _digest("e"),
        "materialized_source_sha256": decision.source_sha256,
        "target_sha256": hashlib.sha256(b"True").hexdigest(),
        "toolchain_fingerprint_sha256": _TOOLCHAIN.sha256,
        "compiler_receipt_sha256": _digest("c"),
        "source_author_principal": "pals.principal.v1/recipe-author/local",
    }
    assert not {"model", "provider", "raw_model_output", "repair_route"} & set(
        decision.candidate_source_payload()
    )


def test_selected_recipe_is_rejected_before_preflight_for_wrong_source_target_digest() -> None:
    selector = _Selector(_selected(target_sha256=_digest("f")))

    with pytest.raises(ValueError, match="target digest"):
        RecipeAttemptPlannerV1(selector, _TOOLCHAIN).decide(
            formal_declaration="example : True := by trivial"
        )


def test_no_recipe_is_a_separate_non_generative_decision() -> None:
    selector = _Selector(
        RecipeNotSelected(
            exclusions=(
                RecipeExclusion(
                    reason_code="formal_target_and_draft_unavailable",
                    recipe_id=None,
                    recipe_revision=None,
                ),
            )
        )
    )
    decision = RecipeAttemptPlannerV1(selector, _TOOLCHAIN).decide(formal_declaration=None)

    assert isinstance(decision, NoRecipeAttemptV1)
    assert decision.exclusions == (("formal_target_and_draft_unavailable", None, None),)
