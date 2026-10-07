from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpDeadlineExceeded,
    HttpResponseTooLarge,
    HttpTransport,
)
from pals_agent.input_fence import check_input_snapshot
from pals_agent.model_roles import ESCALATION_MODEL, RELEASE_MODEL
from pals_agent.openai_diagnostics import (
    http_failure_diagnostics,
    response_failure_diagnostics,
    sanitize_openai_diagnostics,
)
from pals_agent.token_meter import active_token_meter
from pals_agent.usage import report_usage


class OpenAIError(RuntimeError):
    def __init__(self, message: str, *, private_diagnostics: object = None) -> None:
        super().__init__(message)
        self.private_diagnostics = sanitize_openai_diagnostics(private_diagnostics)


@dataclass(frozen=True, slots=True)
class OpenAIResponsesClient:
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 90.0
    max_output_tokens: int = 6000
    transport: HttpTransport = field(
        default_factory=HardDeadlineHttpTransport,
        repr=False,
        compare=False,
    )

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        if not self.api_key.strip():
            raise OpenAIError(
                "OPENAI_API_KEY is required when PALS_LLM_PROVIDER=openai.",
                private_diagnostics={"stage": "configuration"},
            )

        check_input_snapshot()
        endpoint = self.base_url.rstrip("/") + "/responses"
        payload: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "max_output_tokens": self.max_output_tokens,
        }
        if model in {RELEASE_MODEL, ESCALATION_MODEL}:
            # Pin standard service for reproducible usage estimates and bound the
            # cheap first pass; Terra is invoked explicitly, never as a retry.
            payload["service_tier"] = "default"
            payload["reasoning"] = {"effort": "low" if model == RELEASE_MODEL else "medium"}
        if response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "pals_typed_openmath",
                    "strict": True,
                    "schema": response_schema,
                }
            }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = _transport_timeout(timeout_seconds, self.timeout_seconds)
        call_id = str(uuid4())
        meter = active_token_meter()
        try:
            response = meter.request(
                transport=self.transport, endpoint=endpoint, headers=headers,
                payload=payload, data=data, timeout_seconds=timeout, call_id=call_id,
            ) if meter is not None else self.transport.request(
                method="POST",
                url=endpoint,
                headers=headers,
                body=data,
                timeout_seconds=timeout,
            )
        except HardDeadlineHttpError as error:
            kind = (
                "deadline"
                if isinstance(error, HttpDeadlineExceeded)
                else "response_too_large"
                if isinstance(error, HttpResponseTooLarge)
                else "transport_error"
            )
            raise OpenAIError(
                "OpenAI generation request failed",
                private_diagnostics={"stage": "transport", "transport_kind": kind},
            ) from None
        if not 200 <= response.status_code < 300:
            raise OpenAIError(
                f"OpenAI generation failed with HTTP {response.status_code}",
                private_diagnostics=http_failure_diagnostics(response.status_code, response.body),
            )
        try:
            body = json.loads(
                response.body.decode("utf-8"),
                object_pairs_hook=_unique_object if response_schema is not None else None,
            )
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise OpenAIError(
                "OpenAI response was malformed", private_diagnostics={"stage": "json"}
            ) from None
        if not isinstance(body, dict):
            raise OpenAIError(
                "OpenAI response was malformed", private_diagnostics={"stage": "json"}
            )
        if body.get("model") != model:
            raise OpenAIError(
                "OpenAI response model does not match the requested release model.",
                private_diagnostics={"stage": "model"},
            )

        if meter is None:
            report_usage(call_id, model, body.get("usage"))
        generated = (
            _extract_structured_response_text(body)
            if response_schema is not None
            else _extract_response_text(body)
        )
        if not generated.strip():
            raise OpenAIError(
                "OpenAI response did not contain text.", private_diagnostics={"stage": "empty_text"}
            )
        return generated


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate response member")
        result[key] = value
    return result


def _extract_structured_response_text(body: dict[str, Any]) -> str:
    # Opt-in only: never accept partial JSON, refusals, tools or alternate text.
    if (
        body.get("object") != "response"
        or body.get("status") != "completed"
        or body.get("error") is not None
        or body.get("incomplete_details") is not None
    ):
        raise OpenAIError(
            "Structured response did not complete",
            private_diagnostics=response_failure_diagnostics(body, "structured_status"),
        )
    output = body.get("output")
    if not isinstance(output, list) or not 1 <= len(output) <= 32:
        raise OpenAIError(
            "Structured response output invalid",
            private_diagnostics=response_failure_diagnostics(body, "output"),
        )
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            raise OpenAIError(
                "Structured response item invalid",
                private_diagnostics=response_failure_diagnostics(body, "output"),
            )
        if item.get("type") == "reasoning":
            continue
        if (
            item.get("type") != "message"
            or item.get("role") != "assistant"
            or item.get("status") != "completed"
        ):
            raise OpenAIError(
                "Structured response item invalid",
                private_diagnostics=response_failure_diagnostics(body, "output"),
            )
        content = item.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise OpenAIError(
                "Structured response content invalid",
                private_diagnostics=response_failure_diagnostics(body, "content"),
            )
        part = content[0]
        if (
            not isinstance(part, dict)
            or part.get("type") != "output_text"
            or not isinstance(part.get("text"), str)
        ):
            raise OpenAIError(
                "Structured response text invalid or refused",
                private_diagnostics=response_failure_diagnostics(body, "content"),
            )
        texts.append(part["text"])
    if len(texts) != 1:
        raise OpenAIError(
            "Structured response must contain one text result",
            private_diagnostics=response_failure_diagnostics(body, "content"),
        )
    return texts[0]


def _extract_response_text(body: dict[str, Any]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str):
        return output_text

    parts: list[str] = []
    output = body.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts)


def _transport_timeout(override: float | None, configured: float) -> float:
    timeout = configured if override is None else override
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0
    ):
        raise ValueError("transport timeout must be a positive finite number")
    return float(timeout)
