"""Observe the teaching policy at the actual generation and repair model boundary."""

import pytest

from pals_agent.generator import HybridLeanGenerator
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
    RepairRoute,
)

DRAFT = "Expand the square, distribute both products, then collect like terms."
SKETCH = """import Mathlib
example (x y : ℝ) : (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by
  calc
    (x + y) ^ 2 = (x * x + x * y) + (y * x + y * y) := by
      sorry
    _ = x ^ 2 + 2 * x * y + y ^ 2 := by
      sorry"""
PROOF = """import Mathlib
example (x y : ℝ) : (x + y) ^ 2 = x ^ 2 + 2 * x * y + y ^ 2 := by
  calc
    (x + y) ^ 2 = (x * x + x * y) + (y * x + y * y) := by
      rw [pow_two, add_mul, mul_add, mul_add]
    _ = x ^ 2 + 2 * x * y + y ^ 2 := by
      ring"""


class RecordingClient:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        assert self.responses, "unexpected model call"
        return self.responses.pop(0)


def algebra_request() -> ProofRequest:
    return ProofRequest(id="algebra", prompt="Prove (x + y)^2 = x^2 + 2*x*y + y^2 over ℝ.")


def assert_learner_policy(prompt: str) -> None:
    assert "expose the main transformations as `calc`" in prompt
    assert "such as `pow_two`, `add_mul`, and `mul_add`" in prompt
    assert "Do not replace the whole mathematical argument with a single `by ring`" in prompt
    assert "These tactics remain allowed for a small local arithmetic obligation" in prompt
    assert "Do not add vacuous intermediate equalities" in prompt


def test_new_proof_receives_explicit_algebra_policy_at_every_generation_stage() -> None:
    client = RecordingClient(DRAFT, SKETCH, PROOF)
    generated = HybridLeanGenerator(model="model", client=client).generate(algebra_request())

    assert len(client.prompts) == 3
    for prompt in client.prompts:
        assert_learner_policy(prompt)
    assert "Preserve valid substantive `calc` steps" in client.prompts[2]
    assert DRAFT in client.prompts[1]
    assert SKETCH in client.prompts[2]
    # Local ring is accepted and the returned model code is never rewritten by policy.
    assert generated.lean_code == PROOF


@pytest.mark.parametrize("route", ["draft", "sketch", "prove"])
def test_repair_keeps_policy_across_each_selected_resume_route(route: RepairRoute) -> None:
    stages = {"draft": (DRAFT, SKETCH, PROOF), "sketch": (SKETCH, PROOF), "prove": (PROOF,)}
    client = RecordingClient(
        '{"instruction":"Repair the failed distribution rewrite locally."}', *stages[route]
    )
    feedback = GenerationFeedback(
        attempt=1,
        previous_lean_code=PROOF.replace("pow_two", "unknown_power_lemma"),
        diagnostics=(Diagnostic("error", "Unknown identifier `unknown_power_lemma`"),),
        repair_route=route,
        previous_draft=GeneratedDraft(DRAFT, "model", DRAFT),
        previous_sketch=GeneratedSketch(SKETCH, "model", SKETCH, has_gaps=True),
    )
    generator = HybridLeanGenerator(model="model", client=client)
    generated = generator.repair(algebra_request(), feedback)

    assert len(client.prompts) == len(stages[route]) + 1
    for prompt in client.prompts:
        assert_learner_policy(prompt)
    assert "Repair invalid steps locally while retaining valid intermediate reasoning" in (
        client.prompts[0]
    )
    assert generated.lean_code == PROOF
