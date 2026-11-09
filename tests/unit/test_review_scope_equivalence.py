"""Real reviewer wire and fail-closed contracts; scripted clients are not QA accuracy evidence."""

from __future__ import annotations

import json
from typing import Any

import pytest

from pals_agent.explanations import (
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReviewError,
)

SOURCE = """import Mathlib

theorem interval_fixed_point (f : ℝ → ℝ) (a b : ℝ) (hab : a ≤ b)
    (hf : ContinuousOn f (Set.Icc a b))
    (hmaps : Set.MapsTo f (Set.Icc a b) (Set.Icc a b)) :
    ∃ c ∈ Set.Icc a b, f c = c := by
  have ha : 0 ≤ f a - a := sub_nonneg.mpr (hmaps ⟨le_rfl, hab⟩).1
  have hb : f b - b ≤ 0 := sub_nonpos.mpr (hmaps ⟨hab, le_rfl⟩).2
  have hg : ContinuousOn (fun x => f x - x) (Set.Icc a b) :=
    hf.sub continuousOn_id
  obtain ⟨c, hc, heq⟩ := intermediate_value_Icc' hab hg ⟨hb, ha⟩
  exact ⟨c, hc, sub_eq_zero.mp heq⟩
"""
STATEMENT = (
    "For real a≤b, f:ℝ→ℝ is continuous only on [a,b] and maps [a,b] into itself. "
    "Prove that some c∈[a,b] satisfies f(c)=c, including a=b."
)


class Boundary:
    def __init__(self, *responses: dict[str, Any] | str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        assert model == "qa-wire-test"
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        return response if isinstance(response, str) else json.dumps(response)


def candidate(*, global_continuity: bool = False) -> ProofExplanation:
    return ProofExplanation(
        overview=(
            "Let $f:\\mathbb R\\to\\mathbb R$ be globally continuous."
            if global_continuity else
            "Let $a\\le b$ and let $f$ be continuous on $[a,b]$, mapping it into itself."
        ),
        sections=(ExplanationSection(
            id="zero", title="internal source anchor",
            summary=(
                "Set $g(x)=f(x)-x$. The mapping assumption gives $g(a)\\ge0$ and "
                "$g(b)\\le0$. The function $g$ is continuous on $[a,b]$. The closed-interval "
                "intermediate value theorem gives $g(c)=0$ for some $c\\in[a,b]$, hence "
                "$f(c)=c$. If $a=b$, the endpoint inequalities already force $g(a)=0$."
            ),
            references=(LeanLineReference(7, 12, "\n".join(SOURCE.splitlines()[6:12])),),
        ),),
        conclusion="There exists $c\\in[a,b]$ with $f(c)=c$.",
        model="saved-test-draft", provider="test", prompt="not a reviewer instruction",
        raw_model_output="{}", elapsed_ms=0,
    )


def invoke(client: Boundary, item: ProofExplanation | None = None) -> None:
    LeanGroundedOutputReviewer(client, model="qa-wire-test", provider="test").review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE,
        explanation=item or candidate(), language="en",
    )


@pytest.mark.parametrize("item", [candidate(), candidate(global_continuity=True)])
def test_scope_comparison_is_sent_with_original_request_and_unchanged_candidate(item):
    client = Boundary({"approved": True, "rationale": "scripted wire response only"})
    invoke(client, item)
    prompt = client.prompts[0]
    assert f"User theorem statement:\n{STATEMENT}" in prompt
    assert "Strengthening an assumption can prove only a special case" in prompt
    assert "continuity on a specified subset is not global continuity" in prompt
    assert "quantifier order and witness dependencies" in prompt
    payload = json.loads(prompt.split("are not shown):\n", 1)[1])["explanation"]
    assert payload["overview"] == item.overview
    assert payload["conclusion"] == item.conclusion
    assert payload["sections"][0]["references"][0]["excerpt"] == (
        "\n".join(SOURCE.splitlines()[6:12])
    )
    assert item.prompt not in prompt
    assert len(client.prompts) == 1


def test_equivalent_inferences_and_real_source_line_coordinates_reach_reviewer():
    client = Boundary({"approved": True, "rationale": "scripted wire response only"})
    invoke(client)
    prompt = client.prompts[0]
    assert "symmetry and substitution of equality" in prompt
    assert "a partition into exactly two disjoint blocks" in prompt
    assert "bijection transfers the number of classes" in prompt
    assert "one-based inclusive line numbers" in prompt
    assert "Do not infer line numbers from an excerpt or from prompt delimiters" in prompt
    assert SOURCE in prompt


def test_positive_equivalence_rules_keep_negative_mathematical_and_publication_requirements():
    client = Boundary({"approved": True, "rationale": "scripted wire response only"})
    invoke(client)
    prompt = client.prompts[0]
    assert "Keep rejecting a genuinely inapplicable theorem" in prompt
    assert "an unproved quotient-group structure" in prompt
    assert "a correct conclusion\ncannot excuse an invalid body or source mismatch" in prompt
    assert "Still reject a missing essential inference" in prompt
    assert "Preserve the required response schema and checklist decision rules" in prompt


def test_valid_negative_decision_is_terminal_and_never_overridden_by_equivalence_guidance():
    client = Boundary(
        {"approved": False, "rationale": "overview strengthens the continuity hypothesis"},
        {"approved": True, "rationale": "must never be used as another vote"},
    )
    with pytest.raises(ProofOutputReviewError) as result:
        invoke(client, candidate(global_continuity=True))
    assert result.value.category == "rejected"
    assert len(client.prompts) == 1
    assert len(client.responses) == 1


def test_malformed_review_retries_only_within_unchanged_budget_and_same_request():
    client = Boundary("not JSON", {"approved": False, "rationale": "supported negative"})
    with pytest.raises(ProofOutputReviewError) as result:
        invoke(client)
    assert result.value.category == "rejected"
    assert len(client.prompts) == 2
    assert all(f"User theorem statement:\n{STATEMENT}" in p for p in client.prompts)
    assert "previous response failed schema validation" in client.prompts[1]


def test_scope_guidance_does_not_restrict_a_learners_explicit_hypothetical_clarification():
    item = candidate()
    clarification = ProofClarification(
        section_id=item.sections[0].id,
        question="If global continuity is additionally assumed, does the conclusion still hold?",
        answer="The stronger hypothesis still supplies continuity on the required closed interval.",
        key_points=("This is the question's explicit extra hypothesis.",),
        references=item.sections[0].references, model="saved-test-draft", provider="test",
        prompt="", raw_model_output="{}", elapsed_ms=0,
    )
    client = Boundary({"approved": True, "rationale": "scripted clarification wire response only"})
    LeanGroundedOutputReviewer(client, model="qa-wire-test", provider="test").review_clarification(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=item,
        clarification=clarification, language="en",
    )
    prompt = client.prompts[0]
    assert "Strengthening an assumption can prove only a special case" not in prompt
    assert "A clarification must answer the explicit learner question" in prompt
    payload = json.loads(prompt.split("are not shown):\n", 1)[1])
    assert payload["clarification"]["question"] == clarification.question
