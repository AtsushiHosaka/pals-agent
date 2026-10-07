"""CHAT-003/004/007/008/009 protocol checks with isolated HTTP fixtures.

These tests exercise production routing and client serialization. They do not
claim live model intent accuracy, provider image interpretation, or integration.
"""

import base64
import copy
import hashlib
import json

import pytest

from pals_agent.chat_images import chat_input_sha256, parse_chat_images
from pals_agent.chat_runtime import ChatRuntime
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse import ProofReuseRuntime
from pals_agent.token_meter import token_meter_scope
from pals_agent.usage import usage_scope
from tests.unit.test_token_meter import setup_meter

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMz8AAAAASUVORK5CYII="
)
IMAGE = {
    "id": "44444444-4444-4444-8444-444444444444",
    "filename": "diagram.png",
    "media_type": "image/png",
    "size_bytes": len(PNG),
    "content_sha256": hashlib.sha256(PNG).hexdigest(),
    "image_sha256": hashlib.sha256(PNG).hexdigest(),
    "image_data_url": "data:image/png;base64," + base64.b64encode(PNG).decode(),
    "ocr_text": "",
}
REQUEST = {
    "statement": "Explain the meaning of this diagram",
    "context_turns": [],
    "output_language": "en",
    "chat_images": [IMAGE],
}


def route(kind="explanation", **delta):
    return {
        "route": kind,
        "rationale": "The requested purpose is clear.",
        "extracted_statement": "Solve x+1=2." if kind == "lean" else None,
        "question": {"text": "What would you like to do with this image?", "options": []}
        if kind == "needs_input"
        else None,
        **delta,
    }


class RecordedResponses:
    def __init__(self, outputs, *, sessions=None):
        self.outputs = iter(outputs)
        self.calls = []
        self.sessions = iter(sessions) if sessions else None

    def request(self, **kwargs):
        payload = json.loads(kwargs["body"])
        self.calls.append(payload)
        value = next(self.outputs)
        session = next(self.sessions) if self.sessions else f"resp_test_{len(self.calls)}"
        body = {
            "id": session,
            "object": "response",
            "status": "completed",
            "model": payload["model"],
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(value)}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        return HttpResponse(200, json.dumps(body).encode())


def engine(outputs, **kwargs):
    provider = RecordedResponses(outputs, **kwargs)
    client = OpenAIResponsesClient(api_key="fixture-no-network", transport=provider)
    return ChatRuntime(client, ProofReuseRuntime(client, None)), provider


def test_supplemental_image_only_answer_is_seen_by_classifier_generator_and_qa():
    metadata = {key: value for key, value in IMAGE.items() if key not in {
        "image_data_url", "ocr_text"
    }}
    request = {**REQUEST, "context_turns": [{
        "question_id": "purpose", "question": "Please show the relevant part.",
        "answer": "", "attachments": [metadata],
    }]}
    runtime, provider = engine([
        route(), {"text": "The arrow denotes a mapping."},
        {"approved": True, "rationale": "The supplementary image was interpreted accurately."},
    ])
    result = runtime.answer(request)
    assert result.outcome == "answered"
    for call in provider.calls:
        assert call["input"][0]["content"][1]["image_url"] == IMAGE["image_data_url"]
        assert "Please show the relevant part." in call["input"][0]["content"][0]["text"]
    from pals_agent.proof_reuse import _request_input

    assert _request_input(request)[2] == request["context_turns"]


def test_explanation_three_real_client_calls_are_visual_independent_and_metered():
    runtime, provider = engine(
        [
            route(),
            {"text": "The arrow denotes a mapping $f$."},
            {"approved": True, "rationale": "The visual meaning is accurately described."},
        ]
    )
    usage = []
    with usage_scope(usage.append):
        answer = runtime.answer(REQUEST)
    assert answer.outcome == "answered"
    assert answer.answer["evidence_kind"] == "reviewed_explanation"
    assert "lean" not in answer.answer
    assert [call["model"] for call in provider.calls] == [
        "gpt-6.1-sol",
        "gpt-6-luna",
        "gpt-6-luna",
    ]
    assert [item["model"] for item in usage] == [call["model"] for call in provider.calls]
    assert all(call["store"] is False for call in provider.calls)
    assert all(
        call["input"][0]["content"][1]
        == {
            "type": "input_image",
            "image_url": IMAGE["image_data_url"],
            "detail": "high",
        }
        for call in provider.calls
    )
    routing = answer.private_evidence["chat_route"]
    qa = answer.private_evidence["chat_explanation_qa"]
    assert routing["input_sha256"] == qa["input_sha256"] == chat_input_sha256(REQUEST)
    assert routing["session_id"] != qa["session_id"]
    assert qa["answer_sha256"] == hashlib.sha256(answer.answer["text"].encode()).hexdigest()
    assert "decide correctness" in provider.calls[0]["input"][0]["content"][0]["text"]
    assert "hidden solve/prove/correctness" in provider.calls[2]["input"][0]["content"][0]["text"]


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra"])
def test_selected_generation_model_never_changes_fixed_intent_or_qa(model):
    runtime, provider = engine(
        [
            route(),
            {"text": "An arrow connects objects."},
            {"approved": True, "rationale": "Faithful explanation."},
        ]
    )
    assert runtime.answer(dict(REQUEST, generation_model=model)).outcome == "answered"
    assert [call["model"] for call in provider.calls] == ["gpt-6.1-sol", model, "gpt-6-luna"]


def test_qa_rejection_never_publishes_or_falls_back_to_a_proof_route():
    runtime, provider = engine(
        [
            route(),
            {"text": "The answer is correct."},
            {"approved": False, "rationale": "This is a correctness verdict."},
        ]
    )
    result = runtime.answer(REQUEST)
    assert result.outcome == "failed" and result.answer is None
    assert result.error_code == "chat_explanation_review_failed"
    assert len(provider.calls) == 3


def test_same_generation_and_review_session_cannot_be_accepted():
    runtime, _ = engine(
        [
            route(),
            {"text": "An arrow connects objects."},
            {"approved": True, "rationale": "Faithful explanation."},
        ],
        sessions=["resp_intent", "resp_reused", "resp_reused"],
    )
    assert runtime.answer(REQUEST).outcome == "failed"


def test_image_only_ambiguous_route_returns_purpose_question_without_generation():
    runtime, provider = engine([route("needs_input")])
    result = runtime.answer(dict(REQUEST, statement=""))
    assert result.outcome == "needs_input" and result.question["id"]
    assert len(provider.calls) == 1


def test_lean_route_cannot_enter_historical_unverified_answer_branch():
    runtime, provider = engine([route("lean")])
    result = runtime.answer(dict(REQUEST, statement="Solve this"))
    assert result.outcome == "failed" and result.error_code == "lean_verification_required"
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        route("bogus"),
        route(question={"text": "why?", "options": []}),
        route("lean", extracted_statement=""),
        route(rationale=True),
    ],
)
def test_malformed_classification_is_closed_without_an_explanation_fallback(value):
    runtime, provider = engine([value])
    result = runtime.answer(REQUEST)
    assert result.outcome == "failed" and result.answer is None
    assert len(provider.calls) == 1


def test_claim_manifest_rejects_missing_reordered_or_changed_pixels():
    payload = {"attachments": [IMAGE]}
    assert parse_chat_images(payload, [IMAGE["id"]]) == [IMAGE]
    for invalid in [
        {"attachments": []},
        {"attachments": [dict(IMAGE, image_sha256="0" * 64)]},
        {"attachments": [dict(IMAGE, image_data_url="https://example.test/p.png")]},
    ]:
        with pytest.raises(ValueError):
            parse_chat_images(invalid, [IMAGE["id"]])


def test_input_sha_binds_text_context_ocr_and_source_and_visual_digest():
    digest = chat_input_sha256(REQUEST)
    changes = [
        dict(REQUEST, statement="Is this correct?"),
        dict(REQUEST, context_turns=[{"question_id": "q", "question": "why", "answer": "solve"}]),
    ]
    for key in ["content_sha256", "image_sha256", "ocr_text"]:
        request = copy.deepcopy(REQUEST)
        request["chat_images"][0][key] = "changed"
        changes.append(request)
    assert all(chat_input_sha256(item) != digest for item in changes)


def test_multimodal_token_count_uses_same_exact_images_before_the_permit():
    events, api, provider, meter, client = setup_meter()
    with token_meter_scope(meter):
        client.generate(
            model="gpt-6.1-sol",
            prompt="Explain this",
            images=(IMAGE["image_data_url"],),
            store=False,
        )
    assert events == ["count", "permit", "generate", "receipt"]
    counted = json.loads(provider.calls[0]["body"])
    generated = json.loads(provider.calls[1]["body"])
    assert counted["input"] == generated["input"]
    assert api.permits[0]["model"] == "gpt-6.1-sol"
    assert api.receipts[0]["status"] == "success"


def test_remote_image_input_never_reaches_count_or_provider():
    events, _, _, meter, client = setup_meter()
    with token_meter_scope(meter), pytest.raises(ValueError):
        client.generate(model="gpt-6.1-sol", prompt="Explain this", images=("https://x.test/i",))
    assert not events


def test_related_history_and_prior_images_remain_in_every_model_input_and_input_binding():
    request = dict(
        REQUEST,
        statement="Tell me more about that arrow.",
        chat_history=[
            {
                "role": "user",
                "text": "Explain the diagram",
                "attachment_ids": [IMAGE["id"]],
                "context_turns": [
                    {"question_id": "q", "question": "Which arrow?", "answer": "The top one"}
                ],
            }
        ],
    )
    runtime, provider = engine(
        [
            route(),
            {"text": "The top arrow maps the first object."},
            {"approved": True, "rationale": "Matches the prior image and context."},
        ]
    )
    result = runtime.answer(request)
    assert result.outcome == "answered"
    assert result.private_evidence["chat_route"]["input_sha256"] != chat_input_sha256(REQUEST)
    for call in provider.calls:
        text = call["input"][0]["content"][0]["text"]
        assert "Tell me more about that arrow." in text
        assert "The top one" in text
        assert IMAGE["id"] in text


@pytest.mark.parametrize(
    "sessions",
    [
        ["resp_reused", "resp_reused", "resp_review"],
        ["resp_reused", "resp_generate", "resp_reused"],
    ],
)
def test_classifier_session_cannot_be_reused_for_generation_or_review(sessions):
    runtime, _ = engine(
        [
            route(),
            {"text": "An arrow connects objects."},
            {"approved": True, "rationale": "Faithful explanation."},
        ],
        sessions=sessions,
    )
    assert runtime.answer(REQUEST).outcome == "failed"


def test_worker_attachment_client_has_a_bounded_dedicated_large_response_transport():
    from pals_agent.api_client import PalsApiClient

    client = PalsApiClient("https://api.example.test", "fixture")
    assert client.transport.max_response_bytes == 1_048_576
    assert client.attachment_transport.max_response_bytes == 28_000_000
