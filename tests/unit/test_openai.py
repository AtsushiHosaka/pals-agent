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
        transport=RecordingTransport(b'{"model":"gpt-other","output_text":"generated"}'),
    )

    with pytest.raises(OpenAIError, match="does not match"):
        client.generate(model="gpt-5.4-nano", prompt="prove")


def test_extract_response_text_prefers_output_text() -> None:
    assert _extract_response_text({"output_text": "text"}) == "text"


@pytest.mark.parametrize("model,effort", [("gpt-6-luna", "low"), ("gpt-5.6-terra", "medium")])
def test_release_models_pin_standard_tier_and_reasoning_without_retry(model, effort):
    transport = RecordingTransport(json.dumps({"model": model, "output_text": "proof"}).encode())
    result = OpenAIResponsesClient(
        api_key="key", transport=transport, max_output_tokens=2000
    ).generate(
        model=model,
        prompt="statement",
        timeout_seconds=14,
        response_schema=None,
    )
    assert result == "proof"
    assert len(transport.calls) == 1
    assert transport.calls[0]["timeout_seconds"] == 14
    assert json.loads(transport.calls[0]["body"]) == {
        "model": model,
        "input": "statement",
        "max_output_tokens": 2000,
        "service_tier": "default",
        "reasoning": {"effort": effort},
    }


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-5.6-terra"])
def test_new_alias_rejects_unregistered_snapshot_without_falling_back(model):
    transport = RecordingTransport(
        json.dumps({"model": model + "-2099-01-01", "output_text": "proof"}).encode()
    )
    with pytest.raises(OpenAIError, match="does not match"):
        OpenAIResponsesClient(api_key="key", transport=transport).generate(model=model, prompt="s")
    assert len(transport.calls) == 1


# --- Transient-failure retry -------------------------------------------------------------------

from pals_agent.http_transport import (  # noqa: E402
    HttpDeadlineExceeded,
    HttpResponseTooLarge,
    HttpTransportError,
)

_OK = json.dumps({"model": "m", "output_text": "```lean\nok\n```"}).encode()


class ScriptedTransport:
    """Plays back a script of responses or exceptions, one per request."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _client(
    transport: ScriptedTransport, sleeps: list[float], **kwargs: Any
) -> OpenAIResponsesClient:
    return OpenAIResponsesClient(
        api_key="sk-test", transport=transport, sleep=sleeps.append, **kwargs
    )


def test_transport_error_is_retried_then_succeeds() -> None:
    transport = ScriptedTransport(
        HttpTransportError("reset"), HttpTransportError("reset"), HttpResponse(200, _OK)
    )
    sleeps: list[float] = []

    assert _client(transport, sleeps).generate(model="m", prompt="p") == "```lean\nok\n```"

    assert len(transport.calls) == 3
    # Same payload on every try (also what makes the provider's input cache usable).
    assert len({call["body"] for call in transport.calls}) == 1
    assert len(sleeps) == 2 and 1.0 <= sleeps[0] <= 1.25 and 3.0 <= sleeps[1] <= 3.75


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_http_status_is_retried(status: int) -> None:
    transport = ScriptedTransport(HttpResponse(status, b"{}"), HttpResponse(200, _OK))

    assert _client(transport, []).generate(model="m", prompt="p")
    assert len(transport.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_request_defects_are_not_retried(status: int) -> None:
    transport = ScriptedTransport(HttpResponse(status, b"{}"))

    with pytest.raises(OpenAIError) as caught:
        _client(transport, []).generate(model="m", prompt="p")

    assert len(transport.calls) == 1
    assert caught.value.private_diagnostics == {"stage": "http", "http_status": status}


def test_exhausted_quota_429_is_not_retried() -> None:
    body = json.dumps({"error": {"code": "insufficient_quota", "type": "insufficient_quota"}})
    transport = ScriptedTransport(HttpResponse(429, body.encode()))

    with pytest.raises(OpenAIError):
        _client(transport, []).generate(model="m", prompt="p")

    assert len(transport.calls) == 1


def test_retry_gives_up_after_max_attempts_and_reports_the_count() -> None:
    transport = ScriptedTransport(*[HttpTransportError("x")] * 3)

    with pytest.raises(OpenAIError) as caught:
        _client(transport, []).generate(model="m", prompt="p")

    assert len(transport.calls) == 3
    assert caught.value.private_diagnostics == {
        "stage": "transport", "transport_kind": "transport_error", "attempts": 3,
    }


def test_http_failure_after_retries_reports_the_count() -> None:
    transport = ScriptedTransport(*[HttpResponse(503, b"{}")] * 3)

    with pytest.raises(OpenAIError) as caught:
        _client(transport, []).generate(model="m", prompt="p")

    assert caught.value.private_diagnostics == {"stage": "http", "http_status": 503, "attempts": 3}


@pytest.mark.parametrize("error", [HttpDeadlineExceeded("x"), HttpResponseTooLarge("x")])
def test_deadline_and_oversize_are_never_retried(error: Exception) -> None:
    transport = ScriptedTransport(error)
    sleeps: list[float] = []

    with pytest.raises(OpenAIError):
        _client(transport, sleeps).generate(model="m", prompt="p")

    assert len(transport.calls) == 1 and sleeps == []


def test_max_attempts_one_disables_retry() -> None:
    transport = ScriptedTransport(HttpTransportError("x"))

    with pytest.raises(OpenAIError):
        _client(transport, [], max_attempts=1).generate(model="m", prompt="p")

    assert len(transport.calls) == 1


def test_retry_after_header_extends_the_wait_but_is_capped() -> None:
    transport = ScriptedTransport(
        HttpResponse(429, b"{}", (("Retry-After", "7"),)),
        HttpResponse(429, b"{}", (("Retry-After", "9999"),)),
        HttpResponse(200, _OK),
    )
    sleeps: list[float] = []

    _client(transport, sleeps, timeout_seconds=600).generate(model="m", prompt="p")

    assert 7.0 <= sleeps[0] <= 8.75
    assert 10.0 <= sleeps[1] <= 12.5


def test_retries_share_one_wall_clock_budget() -> None:
    transport = ScriptedTransport(HttpTransportError("x"), HttpResponse(200, _OK))
    sleeps: list[float] = []

    _client(transport, sleeps, timeout_seconds=60).generate(model="m", prompt="p")

    first, second = (call["timeout_seconds"] for call in transport.calls)
    assert first == 60 and 0 < second < 60


def test_no_retry_when_the_remaining_budget_cannot_cover_the_wait() -> None:
    # A 3 s budget is below the 5 s minimum window: fail now instead of overrunning it.
    transport = ScriptedTransport(HttpTransportError("x"))

    with pytest.raises(OpenAIError):
        _client(transport, [], timeout_seconds=3).generate(model="m", prompt="p")

    assert len(transport.calls) == 1


def test_empty_text_diagnostics_name_an_exhausted_output_budget() -> None:
    body = json.dumps({
        "model": "m", "object": "response", "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "reasoning", "summary": []}],
    }).encode()

    with pytest.raises(OpenAIError) as caught:
        _client(ScriptedTransport(HttpResponse(200, body)), []).generate(model="m", prompt="p")

    assert caught.value.private_diagnostics == {
        "stage": "empty_text", "response_status": "incomplete",
        "incomplete_reason": "max_output_tokens",
    }


def test_token_metered_requests_are_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    from pals_agent import openai as openai_module

    class Meter:
        calls = 0

        def request(self, **_: Any) -> HttpResponse:
            Meter.calls += 1
            raise HttpTransportError("x")

    monkeypatch.setattr(openai_module, "active_token_meter", lambda: Meter())
    transport = ScriptedTransport()

    with pytest.raises(OpenAIError):
        _client(transport, []).generate(model="m", prompt="p")

    assert Meter.calls == 1 and transport.calls == []


def test_prompt_cache_key_is_sent_only_when_set() -> None:
    body = json.dumps({"model": "gpt-5.4-nano", "output_text": "x"}).encode()
    for key, expected in (("pals-prove", "pals-prove"), (None, None)):
        transport = RecordingTransport(body)
        client = OpenAIResponsesClient(
            api_key="sk-test", transport=transport, prompt_cache_key=key
        )
        client.generate(model="gpt-5.4-nano", prompt="prove")
        sent = json.loads(transport.calls[0]["body"].decode("utf-8"))
        assert sent.get("prompt_cache_key") == expected
        assert ("prompt_cache_key" in sent) is (key is not None)
