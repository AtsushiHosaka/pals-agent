from __future__ import annotations

import json
from typing import Any

import pytest

from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIError, OpenAIResponsesClient, _extract_response_text


class RecordingTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        return HttpResponse(status_code=200, body=self.body)


def test_openai_client_requires_api_key() -> None:
    client = OpenAIResponsesClient(api_key="")

    with pytest.raises(OpenAIError, match="OPENAI_API_KEY is required"):
        client.generate(model="gpt-5.4-nano", prompt="prove")


def test_openai_client_posts_to_responses_api() -> None:
    transport = RecordingTransport(
        json.dumps(
            {
                "model": "gpt-5.4-nano",
                "output_text": "```lean\nimport Mathlib\n```",
            }
        ).encode()
    )
    client = OpenAIResponsesClient(
        api_key="sk-test",
        base_url="https://api.openai.test/v1",
        timeout_seconds=12,
        max_output_tokens=4096,
        transport=transport,
    )

    result = client.generate(model="gpt-5.4-nano", prompt="prove")

    assert result == "```lean\nimport Mathlib\n```"
    captured = transport.calls[0]
    assert captured["url"] == "https://api.openai.test/v1/responses"
    assert captured["timeout_seconds"] == 12
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert json.loads(captured["body"].decode("utf-8")) == {
        "model": "gpt-5.4-nano",
        "input": "prove",
        "max_output_tokens": 4096,
    }


def test_extract_response_text_reads_nested_output() -> None:
    body = {
        "output": [
            {
                "content": [
                    {"type": "output_text", "text": "first"},
                    {"type": "output_text", "text": "second"},
                ]
            }
        ]
    }

    assert _extract_response_text(body) == "first\nsecond"


def test_openai_client_rejects_empty_response() -> None:
    client = OpenAIResponsesClient(
        api_key="sk-test",
        transport=RecordingTransport(b'{"model":"gpt-5.4-nano"}'),
    )

    with pytest.raises(OpenAIError, match="did not contain text"):
        client.generate(model="gpt-5.4-nano", prompt="prove")


def test_openai_client_rejects_a_response_from_a_different_model() -> None:
    client = OpenAIResponsesClient(
        api_key="sk-test",
        transport=RecordingTransport(
            b'{"model":"gpt-other","output_text":"generated"}'
        ),
    )

    with pytest.raises(OpenAIError, match="does not match"):
        client.generate(model="gpt-5.4-nano", prompt="prove")


def test_extract_response_text_prefers_output_text() -> None:
    assert _extract_response_text({"output_text": "text"}) == "text"
