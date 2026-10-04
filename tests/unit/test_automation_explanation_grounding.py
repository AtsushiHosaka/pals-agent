"""Exercise the public generation/review paths and their correspondence contract.

Clients are scripted, so these checks prove prompt wiring and exact source grounding,
not that a live model will always obey the mathematical review rubric.
"""

import json

import pytest

from pals_agent.explanations import (
    _SOURCE_CORRESPONDENCE_INSTRUCTION,
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
)

AUTOMATED_SOURCE = """import Mathlib
theorem square_expansion (x y : ℝ) :
    (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by
  ring"""
EXPLICIT_SOURCE = """import Mathlib
theorem reverse_sum (x y z : ℝ) : (x + y) + z = (z + y) + x := by
  calc
    (x + y) + z = x + (y + z) := add_assoc x y z
    _ = x + (z + y) := congrArg (x + ·) (add_comm y z)
    _ = (z + y) + x := add_comm x (z + y)"""


class CapturingClient:
    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, *, model, prompt, timeout_seconds=None):
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


def section(source, line, section_id, summary):
    return {
        "id": section_id,
        "title": "Equality justification",
        "summary": summary,
        "references": [{
            "start_line": line,
            "end_line": line,
            "excerpt": source.splitlines()[line - 1],
        }],
    }


@pytest.mark.parametrize(
    ("source", "statement", "sections", "conclusion"),
    [
        (
            AUTOMATED_SOURCE,
            "Expand the square of the sum of two real numbers.",
            [section(
                AUTOMATED_SOURCE, 4, "expand-square",
                "By the definition of squaring and distributivity, "
                "$(x+y)^2=x^2+xy+yx+y^2$. Commutativity gives $yx=xy$, "
                "so the two mixed terms add to $2xy$.",
            )],
            "Therefore $(x+y)^2=x^2+2xy+y^2$.",
        ),
        (
            EXPLICIT_SOURCE,
            "Reverse the order of three summands over the reals.",
            [
                section(EXPLICIT_SOURCE, 4, "regroup",
                        "Associativity gives $(x+y)+z=x+(y+z)$."),
                section(EXPLICIT_SOURCE, 5, "swap-inner",
                        "Commutativity gives $y+z=z+y$, hence $x+(y+z)=x+(z+y)$."),
                section(EXPLICIT_SOURCE, 6, "swap-outer",
                        "Commutativity also allows exchanging $x$ and $z+y$."),
            ],
            "Thus $(x+y)+z=(z+y)+x$.",
        ),
    ],
)
def test_source_granularity_survives_generation_clarification_and_independent_review(
    source, statement, sections, conclusion,
):
    payload = {
        "overview": "Fix arbitrary real numbers $x,y,z$.",
        "sections": sections,
        "conclusion": conclusion,
    }
    if source == AUTOMATED_SOURCE:
        payload["overview"] = "Fix arbitrary real numbers $x,y$."
    selected = sections[-1]
    clarification_payload = {
        "section_id": selected["id"],
        "answer": (
            "Addition and multiplication of real numbers satisfy associativity, "
            "commutativity and distributivity. Applying the relevant equality to "
            "these real numbers preserves the value of the expression. This "
            "mathematical justification uses no additional assumptions."
        ),
        "key_points": ["The variables are real numbers.", "The equality preserves the value."],
        "references": selected["references"],
    }
    generator_client = CapturingClient(payload, clarification_payload)
    explainer = LeanProofExplainer(
        client=generator_client, model="generator", provider="test",
    )
    explanation = explainer.explain(
        theorem_statement=statement, lean_code=source, verified=True, language="en",
    )
    clarification = explainer.clarify(
        theorem_statement=statement, lean_code=source, verified=True,
        explanation=explanation, section_id=selected["id"], language="en",
        question="Why does this equality preserve the expression?",
    )
    # Supplementary mathematics with a coarse automation anchor remains publishable;
    # explicit steps keep separate exact line references. No schema rewrite is needed.
    assert [
        [(r.start_line, r.end_line, r.excerpt) for r in item.references]
        for item in explanation.sections
    ] == [
        [(r["start_line"], r["end_line"], r["excerpt"]) for r in item["references"]]
        for item in sections
    ]
    assert clarification.references == explanation.sections[-1].references

    reviewer_client = CapturingClient(
        {"approved": True, "rationale": "The mathematical derivation is grounded."},
        {"approved": True, "rationale": "The clarification explains the selected equality."},
    )
    reviewer = LeanGroundedOutputReviewer(
        client=reviewer_client, model="reviewer", provider="independent-test",
    )
    review = reviewer.review_explanation(
        theorem_statement=statement, lean_code=source, explanation=explanation, language="en",
    )
    clarification_review = reviewer.review_clarification(
        theorem_statement=statement, lean_code=source, explanation=explanation,
        clarification=clarification, language="en",
    )
    assert review.kind == "explanation"
    assert clarification_review.kind == "clarification"
    for prompt in [*generator_client.prompts, *reviewer_client.prompts]:
        assert _SOURCE_CORRESPONDENCE_INSTRUCTION in prompt
        assert source in prompt
    for prompt in reviewer_client.prompts:
        assert (
            "A valid mathematical\nderivation with a coarse automation reference remains "
            "acceptable when it makes no such claim."
        ) in prompt
        assert selected["references"][0]["excerpt"] == json.loads(
            prompt.split("are not shown):\n", 1)[1]
        )["explanation"]["sections"][-1]["references"][0]["excerpt"]
