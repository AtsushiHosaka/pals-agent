from __future__ import annotations

import json
from typing import Any

import pytest

from pals_agent import explanations
from pals_agent.explanations import ExplanationDeadlineExceeded, LeanProofExplainer
from pals_agent.http_transport import HttpResponse
from pals_agent.ollama import OllamaClient
from pals_agent.openai import OpenAIResponsesClient

LEAN_CODE = "example : True := by\n  trivial"


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class TimedClient:
    def __init__(
        self,
        clock: FakeClock,
        responses: list[str],
        delays: list[float],
    ) -> None:
        self.clock = clock
        self.responses = responses
        self.delays = delays
        self.timeouts: list[float] = []

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
    ) -> str:
        _ = (model, prompt)
        assert timeout_seconds is not None
        self.timeouts.append(timeout_seconds)
        self.clock.advance(self.delays.pop(0))
        return self.responses.pop(0)


def _valid_payload() -> str:
    return json.dumps(
        {
            "overview": "証明の概要です。",
            "sections": [
                {
                    "id": "finish",
                    "title": "証明を閉じる",
                    "summary": "目標である True は、定義からすぐに成り立ちます。",
                    "references": [
                        {"start_line": 2, "end_line": 2, "excerpt": "  trivial"}
                    ],
                }
            ],
            "conclusion": "したがって True が証明されました。",
        },
        ensure_ascii=False,
    )


def _explainer(client: TimedClient, clock: FakeClock) -> LeanProofExplainer:
    return LeanProofExplainer(
        client=client,
        model="model",
        provider="provider",
        max_attempts=3,
        monotonic=clock,
    )


def test_pae_015_each_attempt_uses_minimum_of_ceiling_and_remaining_time() -> None:
    clock = FakeClock()
    client = TimedClient(clock, ["invalid", _valid_payload()], [70.0, 0.0])

    _explainer(client, clock).explain(
        theorem_statement="True を証明せよ",
        lean_code=LEAN_CODE,
        verified=True,
        deadline=100.0,
        timeout_seconds=90,
    )

    assert client.timeouts == [90.0, 30.0]


def test_pae_015_zero_remaining_time_starts_no_transport() -> None:
    clock = FakeClock(10.0)
    client = TimedClient(clock, [_valid_payload()], [0.0])

    with pytest.raises(ExplanationDeadlineExceeded):
        _explainer(client, clock).explain(
            theorem_statement="True を証明せよ",
            lean_code=LEAN_CODE,
            verified=True,
            deadline=10.0,
            timeout_seconds=1,
        )

    assert client.timeouts == []


def test_pae_015_output_returned_at_deadline_is_discarded_before_parse() -> None:
    clock = FakeClock()
    client = TimedClient(clock, [_valid_payload()], [3.0])

    with pytest.raises(ExplanationDeadlineExceeded):
        _explainer(client, clock).explain(
            theorem_statement="True を証明せよ",
            lean_code=LEAN_CODE,
            verified=True,
            deadline=3.0,
            timeout_seconds=3,
        )


def test_pae_015_deadline_crossed_during_parser_discards_valid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock(9.0)
    client = TimedClient(clock, [_valid_payload()], [0.0])
    original = explanations._parse_json_object

    def delayed_parse(raw_output: str) -> dict[str, Any]:
        parsed = original(raw_output)
        clock.advance(1.0)
        return parsed

    monkeypatch.setattr(explanations, "_parse_json_object", delayed_parse)

    with pytest.raises(ExplanationDeadlineExceeded):
        _explainer(client, clock).explain(
            theorem_statement="True を証明せよ",
            lean_code=LEAN_CODE,
            verified=True,
            deadline=10.0,
            timeout_seconds=1,
        )


class FakeHttpTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.timeouts: list[float] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.timeouts.append(kwargs["timeout_seconds"])
        return HttpResponse(
            status_code=200,
            body=json.dumps(self.payload).encode("utf-8"),
        )


@pytest.mark.parametrize("client_kind", ["openai", "ollama"])
def test_pae_015_http_model_transport_honors_per_attempt_override(
    client_kind: str,
) -> None:
    payload = (
        {"model": "model", "output_text": "generated"}
        if client_kind == "openai"
        else {"response": "generated"}
    )
    transport = FakeHttpTransport(payload)

    client: OpenAIResponsesClient | OllamaClient
    if client_kind == "openai":
        client = OpenAIResponsesClient(
            api_key="test",
            timeout_seconds=90,
            transport=transport,
        )
    else:
        client = OllamaClient(timeout_seconds=90, transport=transport)

    assert client.generate(model="model", prompt="prompt", timeout_seconds=1.25) == "generated"
    assert transport.timeouts == [1.25]
