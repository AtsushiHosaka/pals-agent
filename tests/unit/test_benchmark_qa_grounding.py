"""PQ016/17 prompt wiring and fail-closed boundaries, not live QA accuracy evidence."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from typing import Any

import pytest

from pals_agent.explanations import (
    CHECKLIST_SAMPLES,
    EPSILON_DELTA_CHECK_IDS,
    ExplanationGenerationError,
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    LeanProofExplainer,
    ProofExplanation,
    ProofOutputReviewError,
    _output_review_prompt,
)

SOURCE = "import Mathlib\n\ntheorem target : (1 : ℝ) = 1 := by\n  rfl\n"
STATEMENT = "実数において1が1に等しいことを証明してください。"
X_SQUARED_SOURCE = (
    "import Mathlib\n\ntheorem target : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity\n"
)
OPAQUE_ABS_SOURCE = (
    "import Mathlib\n\n"
    "example : ¬ DifferentiableAt ℝ (abs : ℝ → ℝ) 0 := by\n"
    "  exact not_differentiableAt_abs_zero\n"
)


class ReviewBoundary:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.lock = threading.Lock()

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        assert model == "qa-boundary"
        with self.lock:
            self.prompts.append(prompt)
            return self.responses.pop(0)


def explanation() -> ProofExplanation:
    return ProofExplanation(
        overview="実数 $1$ を考える。",
        sections=(
            ExplanationSection(
                id="identity",
                title="internal anchor",
                summary="等号の反射律により $1=1$ である。",
                references=(LeanLineReference(4, 4, "  rfl"),),
            ),
        ),
        conclusion="実数において $1=1$ が成り立つ。",
        model="generation-unchanged",
        provider="openai",
        prompt="original generator prompt",
        raw_model_output="{}",
        elapsed_ms=1,
    )


def reviewer(client: ReviewBoundary) -> LeanGroundedOutputReviewer:
    return LeanGroundedOutputReviewer(client, model="qa-boundary", provider="openai")


def prompt(candidate: ProofExplanation | None = None) -> str:
    return _output_review_prompt(
        theorem_statement=STATEMENT,
        lean_code=SOURCE,
        explanation=candidate or explanation(),
        language="ja",
    )


def test_pq016_review_call_gets_grounded_evidence_and_unchanged_candidate() -> None:
    client = ReviewBoundary('{"approved": true, "rationale": "conclusion: 1=1 is established"}')
    candidate = explanation()
    decision = reviewer(client).review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
    )
    assert decision.kind == "explanation"
    rendered = client.prompts[0]
    assert rendered.count("Ground the verdict in the actual candidate and request.") == 1
    assert "candidate JSON field path" in rendered
    assert "quote a short exact span from that field" in rendered
    assert "Before alleging repetition, identify BOTH passages" in rendered
    assert SOURCE in rendered
    assert candidate.overview in rendered
    assert candidate.sections[0].summary in rendered
    assert candidate.conclusion in rendered
    assert candidate.prompt not in rendered
    assert '"approved": true' in rendered and '"approved": false' in rendered
    assert len(client.prompts) == 1


@pytest.mark.parametrize(
    "required,guardrail",
    [
        (
            "more than one standard descriptive name",
            "Keep rejecting a true equality justified by an inapplicable law",
        ),
        (
            "an extra case split\nis not required when the uniform argument already covers it",
            "This does not excuse a false identity, an unsupported inference",
        ),
        (
            "one-sided limit of the difference quotient",
            "limits\nof the function itself do not establish derivative limits",
        ),
        (
            "not to\nordinary mathematical words",
            "for actual unformatted expressions",
        ),
        (
            "Using an established premise in a new inference",
            "same substantive derivation or complete final calculation performed again",
        ),
    ],
)
def test_pq016_false_rejection_safeguards_keep_corresponding_negative_rules(
    required: str, guardrail: str
) -> None:
    rendered = prompt()
    assert required in rendered
    assert guardrail in rendered
    assert "source and presentation requirements before approval" in rendered
    assert "Preserve the required response schema and checklist decision rules" in rendered


def test_pq017_generic_completion_text_is_presented_with_explicit_result_requirement() -> None:
    candidate = replace(explanation(), conclusion="以上で証明は完了した。")
    rendered = prompt(candidate)
    assert candidate.conclusion in rendered
    assert "inspect explanation.conclusion itself" in rendered
    assert "not merely say that the proof is complete" in rendered
    assert "A correct body cannot excuse a missing result" in rendered
    assert "a correct conclusion\ncannot excuse an invalid body or source mismatch" in rendered
    # Claim/source checking and real formatting constraints were not removed.
    assert "Still reject a missing essential inference" in rendered
    assert "Reject learner-visible mathematical expressions outside `$...$`" in rendered
    assert "Each inference must follow from the actual hypotheses" in rendered


@pytest.mark.parametrize(
    "rationale",
    [
        "No actual violation is present.",
        "explanation.conclusion says proof complete instead of the requested result.",
        "explanation.sections[0].summary asserts a false equality.",
        "explanation.sections[0].references do not match the verified source.",
    ],
)
def test_pq016_negative_decision_remains_final_without_a_revote_or_rationale_override(
    rationale: str,
) -> None:
    client = ReviewBoundary(
        json.dumps({"approved": False, "rationale": rationale}),
        '{"approved": true, "rationale": "must not be used as a second vote"}',
    )
    with pytest.raises(ProofOutputReviewError) as caught:
        reviewer(client).review_explanation(
            theorem_statement=STATEMENT,
            lean_code=SOURCE,
            explanation=explanation(),
            language="ja",
        )
    assert caught.value.category == "rejected"
    assert caught.value.rationale == rationale
    assert len(client.prompts) == 1
    assert len(client.responses) == 1


def test_pq016_invalid_review_schema_never_defaults_to_approval() -> None:
    client = ReviewBoundary(
        '{"rationale": "no boolean verdict"}',
        '{"approved": true, "rationale": "ok", "unsupported_field": true}',
        '{"approved": true, "rationale": "must not be called after the budget"}',
    )
    with pytest.raises(ProofOutputReviewError) as caught:
        reviewer(client).review_explanation(
            theorem_statement=STATEMENT,
            lean_code=SOURCE,
            explanation=explanation(),
            language="ja",
        )
    assert caught.value.category == "schema"
    assert len(client.prompts) == 2
    assert len(client.responses) == 1


def test_pq016_x_squared_checklist_still_rejects_a_missing_conclusion() -> None:
    checks = [
        {
            "id": check_id,
            "status": "missing" if check_id == "conclusion" else "ok",
            "note": "missing continuity result" if check_id == "conclusion" else "",
            "quote": "",
        }
        for check_id in EPSILON_DELTA_CHECK_IDS
    ]
    response = json.dumps({"approved": True, "rationale": "inspect the checks", "checks": checks})
    client = ReviewBoundary(*([response] * CHECKLIST_SAMPLES))
    with pytest.raises(ProofOutputReviewError) as caught:
        reviewer(client).review_explanation(
            theorem_statement="x²が連続であることを示してください。",
            lean_code=X_SQUARED_SOURCE,
            explanation=explanation(),
            language="ja",
        )
    assert caught.value.category == "rejected"
    assert "conclusion" in caught.value.rationale
    assert len(client.prompts) == CHECKLIST_SAMPLES
    for rendered in client.prompts:
        assert "Ground the verdict in the actual candidate and request." in rendered
        assert all(check_id in rendered for check_id in EPSILON_DELTA_CHECK_IDS)
        assert '"checks": [' in rendered


def test_pq016_unchanged_explainer_rejects_forged_source_references() -> None:
    payload: dict[str, Any] = {
        "overview": "実数 $1$ を考える。",
        "sections": [
            {
                "id": "identity",
                "title": "internal",
                "summary": "等号の反射律により $1=1$ である。",
                "references": [{"start_line": 4, "end_line": 4, "excerpt": "forged source"}],
            }
        ],
        "conclusion": "実数において $1=1$ が成り立つ。",
    }
    client = ReviewBoundary(*([json.dumps(payload)] * 3))
    explainer = LeanProofExplainer(client, model="qa-boundary", provider="openai")
    with pytest.raises(ExplanationGenerationError):
        explainer.explain(theorem_statement=STATEMENT, lean_code=SOURCE, verified=True)
    assert len(client.prompts) == 2
    assert all("Ground the verdict" not in rendered for rendered in client.prompts)


def opaque_explanation(summary: str) -> ProofExplanation:
    return replace(
        explanation(),
        overview=r"Let $f(x)=|x|$ on $\mathbb{R}$ and consider $0$.",
        sections=(
            ExplanationSection(
                id="one-sided-quotients",
                title="internal",
                summary=summary,
                references=(
                    LeanLineReference(
                        3,
                        4,
                        "example : ¬ DifferentiableAt ℝ (abs : ℝ → ℝ) 0 := by\n"
                        "  exact not_differentiableAt_abs_zero",
                    ),
                ),
            ),
        ),
        conclusion=r"Thus $f$ is not differentiable at $0$.",
    )


def test_pq016_opaque_lemma_review_receives_math_expansion_and_coarse_anchor_rule() -> None:
    summary = (
        r"For $h>0$, $|h|/h=1$; for $h<0$, $|h|/h=-1$. "
        r"These are the right and left limits of the difference quotient at $0$. "
        r"They differ, so its two-sided limit does not exist."
    )
    candidate = opaque_explanation(summary)
    client = ReviewBoundary(
        '{"approved": true, "rationale": "The ordinary derivation proves the exact claim."}'
    )
    decision = reviewer(client).review_explanation(
        theorem_statement="Explain why absolute value is not differentiable at zero.",
        lean_code=OPAQUE_ABS_SOURCE,
        explanation=candidate,
        language="en",
    )
    assert decision.kind == "explanation"
    rendered = client.prompts[0]
    assert OPAQUE_ABS_SOURCE in rendered
    assert summary in rendered
    assert "opaque verified library lemma" in rendered
    assert "intermediate\ncalculations are absent from the supplied Lean lines" in rendered
    assert "Attaching that coarse reference" in rendered
    assert "does NOT itself claim" in rendered
    assert "Do not demand unfolded lemma bodies" in rendered
    assert "Check every explanatory inference under the\nactual hypotheses" in rendered
    assert "A citation cannot excuse any such defect" in rendered


@pytest.mark.parametrize(
    "summary,rationale",
    [
        (
            r"For $h<0$, $|h|/h=1$, so both one-sided derivatives equal $1$.",
            "The negative-h quotient is mathematically false; opacity cannot excuse it.",
        ),
        (
            "The source records and separately Lean-verifies each intermediate quotient limit.",
            "The candidate explicitly invents separately verified source steps.",
        ),
    ],
)
def test_pq016_opaque_lemma_never_overrides_wrong_math_or_fabricated_source_rejection(
    summary: str,
    rationale: str,
) -> None:
    client = ReviewBoundary(
        json.dumps({"approved": False, "rationale": rationale}),
        '{"approved": true, "rationale": "must not become an opacity fallback"}',
    )
    with pytest.raises(ProofOutputReviewError) as caught:
        reviewer(client).review_explanation(
            theorem_statement="Explain why absolute value is not differentiable at zero.",
            lean_code=OPAQUE_ABS_SOURCE,
            explanation=opaque_explanation(summary),
            language="en",
        )
    rendered = client.prompts[0]
    assert summary in rendered
    assert "Keep rejecting wrong mathematics" in rendered
    assert "explicit claims that unseen intermediate" in rendered
    assert "steps were recorded or separately Lean-verified" in rendered
    assert caught.value.category == "rejected"
    assert len(client.prompts) == 1
    assert len(client.responses) == 1
