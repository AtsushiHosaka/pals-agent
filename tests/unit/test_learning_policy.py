"""Exercise production prompt seams without replacing model or compiler boundaries."""

from pals_agent.curriculum_guidance import CURRICULUM_GUIDANCE_VERSION
from pals_agent.explanations import (
    ExplanationSection,
    LeanLineReference,
    ProofExplanation,
    _clarification_prompt,
    _explanation_prompt,
    _output_review_prompt,
)
from pals_agent.generator import _draft_prompt_for
from pals_agent.math_task import ANSWER_SCOPE_REVIEW, PREFLIGHT_TASK_INSTRUCTION
from pals_agent.models import ProofRequest

STATEMENT = (
    "For an England KS3 problem, prove the interior-angle sum of a convex polygon "
    "using triangulation and degrees."
)
# Source data for prompt serialization only; these checks make no compiler claim.
SOURCE = "theorem angle_model (a b : Real) (h : a = b) : b = a := h.symm"


def test_draft_keeps_pedagogical_constraints_before_formalization():
    prompt = _draft_prompt_for(ProofRequest(id="curriculum", prompt=STATEMENT))
    assert STATEMENT in prompt
    assert CURRICULUM_GUIDANCE_VERSION in prompt
    assert "Preserve these\nconstraints in any extracted/resolved task" in prompt
    assert "Internally Lean may still use radians" in prompt
    assert "Output language is not evidence of country" in prompt


def test_explanation_and_followup_and_independent_review_share_policy():
    reference = LeanLineReference(start_line=1, end_line=1, excerpt=SOURCE)
    section = ExplanationSection(
        id="triangulate", title="Triangulation", summary="Draw diagonals from one vertex.",
        references=(reference,),
    )
    explanation = ProofExplanation(
        overview="Fix a convex polygon.", sections=(section,), conclusion="The sum follows.",
        model="", provider="", prompt="", raw_model_output="", elapsed_ms=0,
    )
    prompts = (
        _explanation_prompt(theorem_statement=STATEMENT, lean_code=SOURCE, language="en",
                            require_epsilon_delta=False),
        _clarification_prompt(theorem_statement=STATEMENT, lean_code=SOURCE,
                              explanation=explanation, selected=section,
                              question="Why are there n-2 triangles?", language="en"),
        _output_review_prompt(theorem_statement=STATEMENT, lean_code=SOURCE,
                              explanation=explanation, language="en"),
    )
    for prompt in prompts:
        assert STATEMENT in prompt
        assert CURRICULUM_GUIDANCE_VERSION in prompt
        assert "degree presentation\nmust actually explain the reasoning in degrees" in prompt
        assert "never silently change definitions" in prompt
        assert SOURCE in prompt


def test_scope_review_distinguishes_equivalent_target_from_suitable_stored_answer():
    assert "preserve explicit units" in PREFLIGHT_TASK_INSTRUCTION
    assert "If an answer needs rewriting" in ANSWER_SCOPE_REVIEW
    assert "answer_qa/approved=false" in ANSWER_SCOPE_REVIEW
    assert "Advanced internal Lean lemmas are not themselves" in ANSWER_SCOPE_REVIEW
