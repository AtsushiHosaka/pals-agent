from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpDeadlineExceeded,
    HttpResponse,
    HttpResponseTooLarge,
    HttpTransport,
    HttpTransportError,
)
from pals_agent.model_roles import (
    ESCALATION_MODEL,
    RELEASE_MODEL,
    ReasoningEffort,
)
from pals_agent.openai_diagnostics import (
    http_failure_diagnostics,
    response_failure_diagnostics,
    sanitize_openai_diagnostics,
)
from pals_agent.token_meter import active_token_meter
from pals_agent.usage import report_usage

# Transient provider statuses. Anything else (400/401/403/404/...) is a request defect.
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_MAX_RETRY_AFTER_SECONDS = 10.0
_MIN_RETRY_WINDOW_SECONDS = 5.0


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
    reasoning_effort: ReasoningEffort | None = None
    # Total tries per generation request (1 disables retries). A transport failure or a
    # 408/429/5xx is retried after retry_delays[n], all within the one `timeout_seconds` budget;
    # a request that hit the hard deadline is never retried.
    max_attempts: int = 3
    retry_delays: tuple[float, ...] = (1.0, 3.0)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
        response_schema: dict[str, Any] | None = None,
        images: tuple[str, ...] = (),
        response_callback: Callable[[str], None] | None = None,
        store: bool | None = None,
    ) -> str:
        from pals_agent import step_timing

        arguments: dict[str, Any] = dict(
            model=model, prompt=prompt, timeout_seconds=timeout_seconds,
            response_schema=response_schema, images=images,
            response_callback=response_callback, store=store,
        )
        if not step_timing.enabled():
            return self._generate(**arguments)
        # Opt-in per-step timing: the call below is unchanged, only observed.
        from pals_agent.runtime_latency import current_role_label
        from pals_agent.usage import capture_usage

        with (
            step_timing.step(current_role_label(), model=model) as record,
            capture_usage() as usage_rows,
        ):
            if record is not None:
                record.model_call = True
            try:
                return self._generate(**arguments)
            except OpenAIError as error:
                if record is not None:
                    record.set_outcome(
                        step_timing.classify_openai_error(error.private_diagnostics)
                    )
                    status = error.private_diagnostics.get("http_status")
                    record.http_status = status if type(status) is int else None
                raise
            finally:
                if record is not None:
                    for row in usage_rows:
                        record.set_usage(row)

    def _generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None,
        response_schema: dict[str, Any] | None,
        images: tuple[str, ...],
        response_callback: Callable[[str], None] | None,
        store: bool | None,
    ) -> str:
        from pals_agent.chat_images import current_chat_images
        from pals_agent.linked_chat import linked_chat_prompt

        bound_prompt = linked_chat_prompt(prompt)
        images = images or current_chat_images()
        if images or bound_prompt != prompt:
            store = False
        prompt = bound_prompt
        if not self.api_key.strip():
            raise OpenAIError(
                "OPENAI_API_KEY is required when PALS_LLM_PROVIDER=openai.",
                private_diagnostics={"stage": "configuration"},
            )

        endpoint = self.base_url.rstrip("/") + "/responses"
        payload: dict[str, Any] = {
            "model": model,
            "input": responses_input(prompt, images),
            "max_output_tokens": self.max_output_tokens,
        }
        if store is not None:
            payload["store"] = store
        if model in {RELEASE_MODEL, ESCALATION_MODEL, "gpt-6.1-sol", "gpt-5.6-terra"}:
            # Reasoning models reject temperature/top_p; effort is the only
            # sampling-related control. Never retry with a different model here.
            payload["service_tier"] = "default"
            effort = self.reasoning_effort or (
                "low" if model == RELEASE_MODEL else "medium"
            )
            if effort not in {"none", "low", "medium", "high", "xhigh", "max"} or (
                model == "gpt-6.1-sol" and effort == "none"
            ):
                raise ValueError("Unsupported reasoning effort for the selected model")
            payload["reasoning"] = {"effort": effort}
            from pals_agent import step_timing

            step_timing.annotate_effort(effort)
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
        if meter is not None:
            # The meter owns count -> permit -> one provider request -> receipt; the provider
            # is never retried behind a spent permit.
            try:
                response = meter.request(
                    transport=self.transport, endpoint=endpoint, headers=headers,
                    payload=payload, data=data, timeout_seconds=timeout, call_id=call_id,
                )
            except HardDeadlineHttpError as error:
                raise _transport_failure(error, attempts=1) from None
            tries = 1
        else:
            response, tries = self._post_with_retry(
                endpoint=endpoint, headers=headers, data=data, timeout=timeout
            )
        if not 200 <= response.status_code < 300:
            raise OpenAIError(
                f"OpenAI generation failed with HTTP {response.status_code}",
                private_diagnostics={
                    **http_failure_diagnostics(response.status_code, response.body),
                    **({"attempts": tries} if tries > 1 else {}),
                },
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
            if meter is None:
                # Preserve incurred known-model usage even when identity checking
                # rejects this response. Never invent a price for an unknown model.
                report_usage(
                    call_id, str(body.get("model", "")), body.get("usage"),
                    provider_request_id=body.get("id"),
                )
            raise OpenAIError(
                "OpenAI response model does not match the requested release model.",
                private_diagnostics={"stage": "model"},
            )

        if meter is None:
            report_usage(call_id, model, body.get("usage"), provider_request_id=body.get("id"))
        generated = (
            _extract_structured_response_text(body)
            if response_schema is not None
            else _extract_response_text(body)
        )
        if not generated.strip():
            # Attribute the cause (e.g. status=incomplete / incomplete_reason=max_output_tokens
            # when reasoning consumed the output budget) without retaining any text.
            raise OpenAIError(
                "OpenAI response did not contain text.",
                private_diagnostics=response_failure_diagnostics(body, "empty_text"),
            )
        if response_callback is not None:
            response_id = body.get("id")
            if (
                not isinstance(response_id, str) or not response_id.startswith("resp_")
                or not 6 <= len(response_id) <= 256
            ):
                raise OpenAIError("OpenAI response session identity was malformed")
            response_callback(response_id)
        return generated

    def _post_with_retry(
        self, *, endpoint: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> tuple[HttpResponse, int]:
        """Retry transient failures inside the caller's one wall-clock budget.

        `timeout` bounds the whole call, retries included, so a retry can never extend the
        hard deadline. A request that already hit that deadline is never retried.
        """
        started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            remaining = timeout - (time.monotonic() - started)
            try:
                response = self.transport.request(
                    method="POST", url=endpoint, headers=headers, body=data,
                    timeout_seconds=timeout if attempts == 1 else remaining,
                )
            except HardDeadlineHttpError as error:
                retry = isinstance(error, HttpTransportError) and self._may_retry(
                    attempts, started, timeout, None
                )
                if not retry:
                    raise _transport_failure(error, attempts=attempts) from None
                continue
            if (
                response.status_code in _RETRYABLE_STATUSES
                and not _quota_exhausted(response)
                and self._may_retry(attempts, started, timeout, _retry_after(response))
            ):
                continue
            return response, attempts

    def _may_retry(
        self, attempts: int, started: float, timeout: float, retry_after: float | None
    ) -> bool:
        """Sleep and return True when another try fits the budget."""
        if attempts >= self.max_attempts:
            return False
        delays = self.retry_delays
        base = delays[min(attempts, len(delays)) - 1] if delays else 0.0
        # Jitter keeps parallel workers from retrying a shared outage in lockstep.
        delay = max(base, retry_after or 0.0) * (1.0 + 0.25 * random.random())
        remaining = timeout - (time.monotonic() - started)
        if remaining < delay + _MIN_RETRY_WINDOW_SECONDS:
            return False
        self.sleep(delay)
        return True


def _transport_failure(error: HardDeadlineHttpError, *, attempts: int) -> OpenAIError:
    kind = (
        "deadline"
        if isinstance(error, HttpDeadlineExceeded)
        else "response_too_large"
        if isinstance(error, HttpResponseTooLarge)
        else "transport_error"
    )
    return OpenAIError(
        "OpenAI generation request failed",
        private_diagnostics={
            "stage": "transport",
            "transport_kind": kind,
            **({"attempts": attempts} if attempts > 1 else {}),
        },
    )


def _quota_exhausted(response: HttpResponse) -> bool:
    # A 429 for an exhausted quota is permanent; retrying only delays the failure.
    diagnostics = http_failure_diagnostics(response.status_code, response.body)
    return (
        diagnostics.get("provider_code") == "insufficient_quota"
        or diagnostics.get("provider_type") == "insufficient_quota"
    )


def _retry_after(response: HttpResponse) -> float | None:
    for name, value in response.headers:
        if name.lower() == "retry-after":
            try:
                seconds = float(value)
            except ValueError:
                return None
            if math.isfinite(seconds) and seconds > 0:
                return min(seconds, _MAX_RETRY_AFTER_SECONDS)
    return None


def responses_input(prompt: str, images: tuple[str, ...]) -> str | list[dict[str, Any]]:
    """Inline only validated image derivatives; never fetch provider supplied URLs."""
    if not images:
        return prompt
    from pals_agent.chat_images import validate_image_data_url

    if len(images) > 330:
        raise ValueError("too many chat images")
    total_bytes = 0
    for item in images:
        total_bytes += len(validate_image_data_url(item))
        if total_bytes > 20_000_000:
            raise ValueError("chat visual context exceeds limits")
    return [{"role": "user", "content": [
        {"type": "input_text", "text": prompt},
        *({"type": "input_image", "image_url": item, "detail": "high"} for item in images),
    ]}]


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
