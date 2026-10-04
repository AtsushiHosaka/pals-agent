import json

import pytest

from pals_agent.openai import OpenAIError, OpenAIResponsesClient
from pals_agent.typed_openmath_ast import response_schema
from tests.unit.test_openai import RecordingTransport

MODEL = "gpt-5.4-mini-2026-03-17"


def envelope():
    return {
        "object": "response",
        "status": "completed",
        "model": MODEL,
        "error": None,
        "incomplete_details": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": '{"root":{}}', "annotations": []}],
            },
        ],
    }


def test_opt_in_sends_exact_schema_and_preserves_max_tokens_and_remaining_timeout():
    transport = RecordingTransport(json.dumps(envelope()).encode())
    result = OpenAIResponsesClient(
        api_key="key", transport=transport, max_output_tokens=12000
    ).generate(
        model=MODEL,
        prompt="exact prompt",
        timeout_seconds=17,
        response_schema=response_schema("typed-math-matrix-v1"),
    )
    assert result == '{"root":{}}'
    body = json.loads(transport.calls[0]["body"])
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "pals_typed_openmath",
        "strict": True,
        "schema": response_schema("typed-math-matrix-v1"),
    }
    assert body["max_output_tokens"] == 12000 and transport.calls[0]["timeout_seconds"] == 17
    assert len(transport.calls) == 1


def test_no_schema_preserves_existing_request_bytes_and_response_behavior():
    transport = RecordingTransport(json.dumps({"model": MODEL, "output_text": "plain"}).encode())
    client = OpenAIResponsesClient(api_key="key", transport=transport)
    assert client.generate(model=MODEL, prompt="prove") == "plain"
    assert (
        transport.calls[0]["body"]
        == json.dumps({"model": MODEL, "input": "prove", "max_output_tokens": 6000}).encode()
    )


@pytest.mark.parametrize(
    "alter",
    [
        lambda e: e.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
        lambda e: e.update(error={"message": "private"}),
        lambda e: e.update(output=[]),
        lambda e: e["output"].append(e["output"][-1]),
        lambda e: e["output"][-1]["content"][0].update(type="refusal", refusal="private"),
        lambda e: e["output"].append({"type": "function_call", "arguments": "private"}),
        lambda e: e.update(model="different"),
    ],
)
def test_opt_in_rejects_noncomplete_refused_ambiguous_or_tool_output(alter):
    value = envelope()
    alter(value)
    value["output_text"] = "do not bypass validation"
    with pytest.raises(OpenAIError) as caught:
        OpenAIResponsesClient(
            api_key="key", transport=RecordingTransport(json.dumps(value).encode())
        ).generate(
            model=MODEL,
            prompt="exact prompt",
            response_schema=response_schema("typed-math-matrix-v1"),
        )
    assert "private" not in str(caught.value)


def test_opt_in_rejects_duplicate_envelope_members():
    body = (
        json.dumps(envelope())
        .replace('"status": "completed"', '"status":"completed","status":"completed"', 1)
        .encode()
    )
    with pytest.raises(OpenAIError):
        OpenAIResponsesClient(api_key="key", transport=RecordingTransport(body)).generate(
            model=MODEL,
            prompt="exact prompt",
            response_schema=response_schema("typed-math-matrix-v1"),
        )
