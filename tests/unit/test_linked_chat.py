"""Asynchronous visual/model binding with isolated external HTTP fixtures.

These checks do not claim real provider interpretation or Lean verification.
"""

import copy
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiError
from pals_agent.chat_images import chat_input_sha256, current_chat_images
from pals_agent.explanations import (
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    LeanProofSemanticReviewer,
)
from pals_agent.generator import HybridLeanGenerator
from pals_agent.http_transport import HttpResponse
from pals_agent.linked_chat import linked_chat_scope, selected_generation_model
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_semantic_reviewer import RecipeReviewActor
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker
from tests.unit.test_chat_runtime import IMAGE
from tests.unit.test_explanations import LEAN_CODE, explanation_payload
from tests.unit.test_generator import DRAFT, PROOF, SKETCH, feedback, request
from tests.unit.test_recipe_semantic_reviewer import Api as RecipeApi
from tests.unit.test_worker import SemanticReviewApi


def binding(model="gpt-6.1-sol"):
    source = {
        "statement": "Prove the identity in this image.",
        "context_turns": [{
            "question_id": "domain", "question": "Which domain?", "answer": "Natural numbers"
        }],
        "chat_history": [],
        "attachment_ids": [IMAGE["id"]],
        "generation_model": model,
    }
    route = {
        "schema_version": "pals.chat-route.v1", "route": "lean",
        "input_sha256": chat_input_sha256({**source, "chat_images": [IMAGE]}),
        "model_role": "chat_intent", "model": "gpt-6.1-sol",
        "session_id": "resp_classifier", "rationale": "An explicit proof request.",
        "extracted_statement": "Every natural number plus zero is itself.", "question": None,
    }
    return {"generation_model": model, "chat_route": route}, {
        "request": source, "attachments": [IMAGE], "chat_route": route,
    }


class Responses:
    def __init__(self, outputs):
        self.outputs, self.calls = iter(outputs), []

    def request(self, **kwargs):
        payload = json.loads(kwargs["body"])
        self.calls.append(payload)
        value = next(self.outputs)
        body = {
            "model": payload["model"],
            "output": [{"content": [{
                "type": "output_text",
                "text": value if isinstance(value, str) else json.dumps(value)
            }]}],
            "usage": {"input_tokens": 12, "output_tokens": 5},
        }
        return HttpResponse(200, json.dumps(body).encode())


def assert_visual_calls(calls):
    for call in calls:
        assert call["store"] is False
        content = call["input"][0]["content"]
        assert content[1] == {
            "type": "input_image", "image_url": IMAGE["image_data_url"], "detail": "high"
        }
        assert "Prove the identity in this image." in content[0]["text"]
        assert "Natural numbers" in content[0]["text"]
        assert "reject a proof or explanation" in content[0]["text"]


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra"])
def test_dsp_repair_and_explainer_selected_with_fixed_routing_and_independent_qa(model):
    provider = Responses([
        DRAFT, SKETCH, PROOF, {"instruction": "Use the identity."},
        {"route": "prove", "rationale": "The sketch is usable."},
        explanation_payload(), {"approved": True, "rationale": "Source and input agree."},
    ])
    client = OpenAIResponsesClient("isolated-external-fixture", transport=provider)
    generator = HybridLeanGenerator("gpt-6-luna", provider="openai", openai=client)
    explainer = LeanProofExplainer(client, "gpt-6-luna", "openai")
    reviewer = LeanGroundedOutputReviewer(client, "gpt-6-luna", "openai")
    context, payload = binding(model)
    with linked_chat_scope(context, payload):
        result = generator.generate(request())
        assert result.model == result.draft.model == result.sketch.model == model
        generator._generate_repair_instruction(request(), feedback("prove"))
        routing = generator.select_repair_route(request(), feedback("prove"))
        assert routing.model == "gpt-6-luna"
        explanation = explainer.explain(
            theorem_statement="n + 0 = n を示せ", lean_code=LEAN_CODE, verified=True,
        )
        assert explanation.model == model
        review = reviewer.review_explanation(
            theorem_statement="n + 0 = n を示せ", lean_code=LEAN_CODE, explanation=explanation,
            language="ja",
        )
        assert review.reviewer_model == "gpt-6-luna"
    assert [call["model"] for call in provider.calls] == [
        model, model, model, "gpt-6-luna", "gpt-6-luna", model, "gpt-6-luna"
    ]
    assert_visual_calls(provider.calls)
    assert current_chat_images() == ()
    assert selected_generation_model("default") == "default"


@pytest.mark.parametrize("mutation", ["input", "pixels", "model", "route"])
def test_rejects_mutated_linked_snapshot_before_call_and_restores_scope(mutation):
    context, payload = copy.deepcopy(binding())
    if mutation == "input":
        payload["request"]["statement"] = "A different task"
    elif mutation == "pixels":
        payload["attachments"][0]["image_sha256"] = "a" * 64
    elif mutation == "model":
        payload["request"]["generation_model"] = "gpt-6-luna"
    else:
        payload["chat_route"]["route"] = "explanation"
    with pytest.raises(ValueError), linked_chat_scope(context, payload):
        pytest.fail("must not enter an invalid linked scope")
    assert current_chat_images() == ()
    assert selected_generation_model("default") == "default"


class LinkedSemanticApi(SemanticReviewApi):
    def __init__(self, *, unavailable=False):
        super().__init__()
        self.context, self.payload = binding()
        self.unavailable = unavailable

    def get_proof_job(self, proof_job_id):
        value = super().get_proof_job(proof_job_id)
        value["request_context"].update(self.context)
        return value

    def get_proof_job_chat_input(self, proof_job_id):
        if self.unavailable:
            raise PalsApiError("image deleted or expired")
        return self.payload


@pytest.mark.parametrize("unavailable", [False, True])
def test_later_semantic_review_delivery_restores_pixels_and_original_goal(unavailable):
    api = LinkedSemanticApi(unavailable=unavailable)
    provider = Responses([{"approved": True, "rationale": "Original task and theorem agree."}])
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api), pipeline=None, explainer=None,
        proof_reviewer=LeanProofSemanticReviewer(
            OpenAIResponsesClient("isolated-external-fixture", transport=provider),
            "gpt-6-luna", "openai",
        ),
    )
    assert worker.process_proof_job("job-semantic") is (not unavailable)
    if unavailable:
        assert provider.calls == api.evidence == []
    else:
        assert len(provider.calls) == len(api.evidence) == 1
        assert provider.calls[0]["model"] == "gpt-6-luna"
        assert_visual_calls(provider.calls)


def test_separate_recipe_reviewer_receives_same_visual_binding_without_worker_secret():
    class LinkedRecipeApi(RecipeApi):
        def __init__(self):
            super().__init__()
            self.content["chat_input_available"] = True

        def get_chat_input(self, job, candidate):
            assert (job, candidate) == ("proof-1", self.candidate)
            return binding()[1]

    api = LinkedRecipeApi()
    provider = Responses([{"approved": True, "rationale": "Source and visual goal agree."}])
    client = OpenAIResponsesClient("isolated-external-fixture", transport=provider)
    actor = RecipeReviewActor(
        api, lambda: LeanProofSemanticReviewer(client, "gpt-6-luna", "openai")
    )
    assert actor.review("proof-1", api.candidate)["state"] == "verified"
    assert len(provider.calls) == len(api.writes) == 1
    assert provider.calls[0]["model"] == "gpt-6-luna"
    assert_visual_calls(provider.calls)
