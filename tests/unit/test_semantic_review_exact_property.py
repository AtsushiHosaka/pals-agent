import json

import pytest

from pals_agent.explanations import LeanProofSemanticReviewer, _proof_semantic_review_prompt
from pals_agent.lean_target import LeanTargetDeclaration


def test_review_compares_exported_property_and_preserves_specific_inverse_witness():
    statement = "For every field K, the exchange matrix P is a two-sided inverse of itself."
    source = "theorem weak (P : Matrix (Fin 2) (Fin 2) K) : IsUnit P := by\n  exact existing"
    prompt = _proof_semantic_review_prompt(
        theorem_statement=statement,
        formal_statement=None,
        target_declaration=LeanTargetDeclaration(
            kind="theorem", name="weak", proposition="IsUnit P"
        ),
        lean_code=source,
    )
    assert statement in prompt and source in prompt
    assert '"proposition": "IsUnit P"' in prompt
    assert "Reject a strictly weaker top-level proposition" in prompt
    assert "intermediate proof step" in prompt
    assert "A * B = I and B * A = I for that same B" in prompt
    assert "self-inverse\nrequest must preserve the matrix itself" in prompt


def test_rank_identity_review_keeps_exact_target_and_does_not_guess_library_signature():
    source = (
        "import Mathlib\n\n"
        "theorem identity_rank (K : Type) [Field K] :\n"
        "    Matrix.rank (1 : Matrix (Fin 2) (Fin 2) K) = 2 := by\n"
        "  simpa using (Matrix.rank_one (R := K) (n := Fin 2))"
    )
    target = LeanTargetDeclaration(
        kind="theorem",
        name="identity_rank",
        proposition="Matrix.rank (1 : Matrix (Fin 2) (Fin 2) K) = 2",
    )
    prompt = _proof_semantic_review_prompt(
        theorem_statement="Over any field K, the 2 by 2 identity matrix has rank 2.",
        formal_statement=None,
        target_declaration=target,
        lean_code=source,
    )
    assert source in prompt
    assert json.dumps(target.as_dict(), ensure_ascii=False, sort_keys=True) in prompt
    assert "do not second-guess\na library lemma's type" in prompt
    assert "invent an unseen signature" in prompt
    assert "binder types,\nquantifiers, assumptions, definitions, notation and conclusion" in prompt
    assert "added assumptions, vacuous reformulations or misleading local redefinitions" in prompt
    assert "Lean compilation alone is not approval" in prompt


def test_a_stated_convention_is_part_of_the_claim_but_unstated_restrictions_are_not():
    prompt = _proof_semantic_review_prompt(
        theorem_statement=(
            "自然数は1から始まるものとする。"
            "すべての自然数 n について n ≥ 1 であることを示せ。"
        ),
        formal_statement=None,
        target_declaration=LeanTargetDeclaration(
            kind="theorem", name="t", proposition="∀ n : {n : ℕ // 1 ≤ n}, 1 ≤ (n : ℕ)"
        ),
        lean_code="theorem t : ∀ n : {n : ℕ // 1 ≤ n}, 1 ≤ (n : ℕ) := fun n => n.property",
    )
    assert "A convention stated in the learner request itself" in prompt
    assert "neither an\nadded assumption nor a weaker claim" in prompt
    assert "A\nrestriction that the request does not state remains an added assumption." in prompt
    assert "added assumptions, vacuous reformulations or misleading local redefinitions" in prompt


@pytest.mark.parametrize(
    "proposition,rationale",
    [
        ("IsUnit P", "The exported proposition loses the requested self-inverse witness."),
        ("True", "The exported proposition does not express the requested matrix rank."),
    ],
)
def test_compiled_candidate_semantic_rejection_stays_terminal_without_re_vote(
    proposition, rationale
):
    class RejectingClient:
        calls = 0

        def generate(self, *, model, prompt):
            self.calls += 1
            assert self.calls == 1, "A valid rejection must not be re-voted."
            assert "Lean compilation of these exact source bytes has already succeeded" in prompt
            return json.dumps({"approved": False, "rationale": rationale})

    client = RejectingClient()
    reviewer = LeanProofSemanticReviewer(client=client, model="test-model", provider="openai")
    review = reviewer.review_proof(
        theorem_statement="The given matrix P is self-inverse and has rank 2.",
        formal_statement=None,
        target_declaration=LeanTargetDeclaration(
            kind="theorem", name="weak", proposition=proposition
        ),
        lean_code=f"theorem weak : {proposition} := by exact existing",
    )
    assert review.decision == "rejected"
    assert review.rationale == rationale
    assert client.calls == 1
