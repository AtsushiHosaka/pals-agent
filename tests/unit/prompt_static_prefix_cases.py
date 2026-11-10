"""Representative inputs for the generation-prompt builders (shared by golden + prefix tests)."""

from __future__ import annotations

from pals_agent import generator as g
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
    RelatedDraftContext,
)

DRAFT = GeneratedDraft("Step 1: split into cases.\nStep 2: conclude.", "m", "raw")
SKETCH = GeneratedSketch("import Mathlib\ntheorem t : True := by\n  sorry", "m", "raw")


def _ctx(tag: str) -> RelatedDraftContext:
    return RelatedDraftContext(
        f"draft-{tag}", (f"note {tag}",), (f"step {tag}",)
    )


REQUESTS = {
    "plain": ProofRequest(
        id="a",
        prompt="Prove that the sum of two even integers is even.",
        related_draft_contexts=(_ctx("a1"), _ctx("a2")),
    ),
    "harness": ProofRequest(
        id="b",
        prompt="Show that the square root of 2 is irrational.",
        formal_statement="theorem foo : Irrational (Real.sqrt 2) := by sorry",
    ),
    "continuity": ProofRequest(
        id="c",
        prompt="x^3 は連続であることを示せ (continuous)",
        related_draft_contexts=(_ctx("c"),),
    ),
    "matrix": ProofRequest(
        id="d", prompt="Show the matrix [[1,2],[3,4]] is invertible over a field."
    ),
}
FEEDBACKS = {
    "none": None,
    "unknown": GenerationFeedback(
        2, "import Mathlib\ntheorem t : False := by\n  foo",
        (Diagnostic("error", "Unknown identifier foo; use an available declaration.",
                    code="lean.unknown_identifier", line=3, column=2),),
        "prove", "local tactic error", DRAFT, SKETCH,
    ),
    "plain_error": GenerationFeedback(
        1, "theorem t : True := by\n  bad",
        (Diagnostic("error", "unexpected token", line=2),), "sketch", "r", DRAFT, SKETCH,
    ),
}


def all_prompts(variant: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for rn, req in REQUESTS.items():
        for fn, fb in FEEDBACKS.items():
            key = f"{rn}/{fn}"
            out[f"draft/{key}"] = g._draft_prompt_for(req, fb)
            out[f"sketch/{key}"] = g._sketch_prompt_for(req, DRAFT, fb)
            out[f"prove/{key}"] = g._prove_prompt_for(req, DRAFT, SKETCH, fb)
            out[f"compat/{key}"] = g._prompt_for(req, fb)
            if fb is not None:
                out[f"route/{key}"] = g._repair_route_prompt_for(req, fb)
                out[f"repair_instruction/{key}"] = g._repair_instruction_prompt_for(req, fb)
    return out
