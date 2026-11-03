"""Exercise real DSP prompt construction and payloads without paid provider calls."""

import json
from dataclasses import asdict, replace
from typing import Any

import pytest

from pals_agent.explanations import LeanProofExplainer
from pals_agent.generator import HybridLeanGenerator
from pals_agent.http_transport import HttpResponse
from pals_agent.linked_chat import linked_chat_scope
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.models import Diagnostic, GenerationFeedback, ProofRequest
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_flow_reranker import _MODEL as RERANK_MODEL
from pals_agent.proof_reuse_usage import current_role
from pals_agent.usage import usage_scope
from pals_agent.worker import _generated_proof_from_status

PROOF = """```lean
import Mathlib
theorem natural_power_continuous (n : ℕ) : Continuous (fun x : ℝ => x ^ n) := by
  fun_prop
```"""


class DSPTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.roles: list[str] = []
        self.status = 200

    def request(self, **kwargs: Any) -> HttpResponse:
        payload = json.loads(kwargs["body"])
        self.calls.append(payload)
        self.roles.append(current_role())
        prompt = payload["input"]
        if prompt.startswith("Write an informal"):
            text = "Use continuity of the identity and closure under natural powers."
        elif "Choose where the PALS" in prompt:
            text = '{"route":"prove","rationale":"Correct the failing tactic."}'
        elif "Create the PALS repair handoff" in prompt:
            text = '{"instruction":"Use fun_prop while preserving the target."}'
        else:
            text = PROOF
        return HttpResponse(self.status, json.dumps({
            "model": payload["model"], "output_text": text,
            "usage": {
                "input_tokens": 100, "output_tokens": 80,
                "output_tokens_details": {"reasoning_tokens": 60},
            },
        }).encode())


def dsp() -> tuple[HybridLeanGenerator, DSPTransport]:
    transport = DSPTransport()
    return HybridLeanGenerator(
        model="gpt-6.1-terra", provider="openai", use_release_role_bindings=True,
        openai=OpenAIResponsesClient(api_key="test", transport=transport, max_output_tokens=16384),
    ), transport


def request() -> ProofRequest:
    return ProofRequest("power-continuity", "For every n : ℕ, prove x ↦ x^n is continuous on ℝ.")


def test_static_terra_medium_dsp_records_actual_stage_model_reasoning_and_usage() -> None:
    generator, transport = dsp()
    costs: list[dict[str, Any]] = []
    with usage_scope(costs.append):
        generated = generator.generate(request())
    assert generated.lean_code
    assert generated.draft is not None and generated.sketch is not None
    stages = (generated.draft, generated.sketch, generated)
    assert [(stage.model, stage.provider, stage.reasoning_effort) for stage in stages] == [
        ("gpt-6.1-terra", "openai", "medium"),
    ] * 3
    assert transport.roles == ["draft", "sketch", "prove"]
    assert all(call["reasoning"] == {"effort": "medium"} for call in transport.calls)
    assert all(call["max_output_tokens"] == 16384 for call in transport.calls)
    assert all("temperature" not in call and "top_p" not in call for call in transport.calls)
    assert len(costs) == 3
    assert all(cost["model"] == "gpt-6.1-terra" for cost in costs)
    assert all(cost["reasoning_output_tokens"] == 60 for cost in costs)
    assert all(cost["price_snapshot_id"] ==
               "openai-gpt-6.1-terra-standard-upper-bound-2026-11-01" for cost in costs)


@pytest.mark.parametrize("effort", ["medium", "high"])
def test_manual_static_effort_override_is_constant_across_retries(effort: Any) -> None:
    generator, transport = dsp()
    assert generator.openai is not None
    generator = replace(generator, openai=replace(generator.openai, reasoning_effort=effort))
    first = generator.generate(request())
    transport.calls.clear()
    for attempt in (1, 3, 12):
        repaired = generator.repair(request(), GenerationFeedback(
            attempt=attempt, previous_lean_code=first.lean_code,
            diagnostics=(Diagnostic("error", "unknown tactic", "lean.unknown_identifier"),),
            repair_route="prove", previous_draft=first.draft, previous_sketch=first.sketch,
        ))
        assert repaired.model == "gpt-6.1-terra"
        assert repaired.reasoning_effort == effort
    assert len(transport.calls) == 6  # one repair handoff + one proof per retry
    assert all(call["model"] == "gpt-6.1-terra" for call in transport.calls)
    assert all(call["reasoning"] == {"effort": effort} for call in transport.calls)


@pytest.mark.parametrize("selected,effort", [("gpt-6.1-sol", "medium"), ("gpt-6-luna", "low")])
def test_explicit_user_model_selection_is_preserved(selected: str, effort: str) -> None:
    generator, transport = dsp()
    with linked_chat_scope({"generation_model": selected}):
        generated = generator.generate(request())
    assert generated.model == selected
    assert all(call["model"] == selected for call in transport.calls)
    assert all(call["reasoning"] == {"effort": effort} for call in transport.calls)


def test_route_selection_remains_cheap_and_separate_from_lean_effort() -> None:
    generator, transport = dsp()
    feedback = GenerationFeedback(1, "bad", (Diagnostic("error", "syntax"),))
    decision = generator.select_repair_route(request(), feedback)
    assert (decision.model, decision.reasoning_effort) == ("gpt-6-luna", "low")
    assert transport.roles == ["route"]
    assert transport.calls[0]["reasoning"] == {"effort": "low"}


def test_lean_draft_quality_does_not_raise_retrieval_reranker_cost() -> None:
    assert fixed_model_default(ModelRole.DRAFT).model == "gpt-6.1-terra"
    assert RERANK_MODEL == "gpt-6-luna"


def test_provider_failure_does_not_silently_try_another_model() -> None:
    generator, transport = dsp()
    transport.status = 429
    generated = generator.generate(request())
    assert not generated.lean_code
    assert len(transport.calls) == 1
    assert transport.calls[0]["model"] == "gpt-6.1-terra"


def test_resume_preserves_reasoning_evidence_and_accepts_historical_missing_field() -> None:
    generator, _ = dsp()
    payload = json.loads(json.dumps(asdict(generator.generate(request()))))
    restored = _generated_proof_from_status(payload)
    assert restored is not None and restored.reasoning_effort == "medium"
    assert restored.draft is not None and restored.draft.reasoning_effort == "medium"
    assert restored.sketch is not None and restored.sketch.reasoning_effort == "medium"
    for stage in (payload, payload["draft"], payload["sketch"]):
        del stage["reasoning_effort"]
    restored = _generated_proof_from_status(payload)
    assert restored is not None and restored.reasoning_effort is None
    payload["reasoning_effort"] = "untrusted-value"
    assert _generated_proof_from_status(payload) is None


def test_lean_model_selection_does_not_raise_explanation_model_cost() -> None:
    class ExplanationTransport(DSPTransport):
        def request(self, **kwargs: Any) -> HttpResponse:
            payload = json.loads(kwargs["body"])
            self.calls.append(payload)
            output = {
                "overview": "The identity is continuous and continuity is preserved by powers.",
                "sections": [{
                    "id": "continuity", "title": "Natural powers",
                    "summary": "The tactic proves continuity using the rules for natural powers.",
                    "references": [{"start_line": 3, "end_line": 3, "excerpt": "  fun_prop"}],
                }],
                "conclusion": "Thus the real natural power function is continuous.",
            }
            return HttpResponse(200, json.dumps({
                "model": payload["model"], "output_text": json.dumps(output),
            }).encode())

    transport = ExplanationTransport()
    explainer = LeanProofExplainer(
        client=OpenAIResponsesClient(api_key="test", transport=transport),
        model="gpt-6-luna", provider="openai",
    )
    lean = PROOF.removeprefix("```lean\n").removesuffix("```")
    with linked_chat_scope({"generation_model": "gpt-6.1-terra"}):
        result = explainer.explain(
            theorem_statement=request().prompt, lean_code=lean, verified=True, language="en",
        )
    assert result.model == "gpt-6-luna"
    assert transport.calls[0]["model"] == "gpt-6-luna"
    assert transport.calls[0]["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("selected", ["gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-luna"])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_explicit_request_effort_is_used_for_all_dsp_stages_and_repairs(
    selected: str, effort: str,
) -> None:
    generator, transport = dsp()
    assert generator.openai is not None
    # The immutable request wins over a separately constructed client's default.
    generator = replace(generator, openai=replace(generator.openai, reasoning_effort="low"))
    costs: list[dict[str, Any]] = []
    with linked_chat_scope({
        "generation_model": selected, "generation_reasoning_effort": effort,
    }), usage_scope(costs.append):
        initial = generator.generate(request())
        restored = _generated_proof_from_status(json.loads(json.dumps(asdict(initial))))
        assert restored is not None
        assert restored.reasoning_effort == effort
        assert restored.draft is not None and restored.draft.reasoning_effort == effort
        assert restored.sketch is not None and restored.sketch.reasoning_effort == effort
        for attempt in (1, 3, 12):
            repaired = generator.repair(request(), GenerationFeedback(
                attempt=attempt, previous_lean_code=restored.lean_code,
                diagnostics=(Diagnostic("error", "unknown tactic", "lean.unknown_identifier"),),
                repair_route="prove", previous_draft=restored.draft,
                previous_sketch=restored.sketch,
            ))
            assert (repaired.model, repaired.reasoning_effort) == (selected, effort)
        assert all(call["model"] == selected for call in transport.calls)
        assert all(call["reasoning"] == {"effort": effort} for call in transport.calls)
        assert {cost["model"] for cost in costs} == {selected}
        assert all(cost["output_tokens"] == 80 for cost in costs)
        assert all(cost["reasoning_output_tokens"] == 60 for cost in costs)
        route = generator.select_repair_route(request(), GenerationFeedback(
            1, "bad", (Diagnostic("error", "syntax"),),
        ))
        assert (route.model, route.reasoning_effort) == ("gpt-6-luna", "low")
    transport.calls.clear()
    generator.generate(request())
    assert all(call["model"] == "gpt-6.1-terra" for call in transport.calls)
    assert all(call["reasoning"] == {"effort": "low"} for call in transport.calls)


def test_explicit_request_effort_is_not_ignored_without_release_role_bindings() -> None:
    generator, transport = dsp()
    generator = replace(generator, use_release_role_bindings=False)
    with linked_chat_scope({
        "generation_model": "gpt-6.1-sol", "generation_reasoning_effort": "high",
    }):
        generated = generator.generate(request())
    assert generated.reasoning_effort == "high"
    assert all(call["reasoning"] == {"effort": "high"} for call in transport.calls)
