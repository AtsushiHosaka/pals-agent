from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)


class OpenAIError(RuntimeError):
    pass


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
    ) -> str:
        if not self.api_key.strip():
            raise OpenAIError("OPENAI_API_KEY is required when PALS_LLM_PROVIDER=openai.")

        endpoint = self.base_url.rstrip("/") + "/responses"
        data = json.dumps(
                {
                    "model": model,
                    "input": prompt,
                    "max_output_tokens": self.max_output_tokens,
                }
            ).encode("utf-8")
        headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        timeout = _transport_timeout(timeout_seconds, self.timeout_seconds)
        try:
            response = self.transport.request(
                method="POST",
                url=endpoint,
                headers=headers,
                body=data,
                timeout_seconds=timeout,
            )
        except HardDeadlineHttpError:
            raise OpenAIError("OpenAI generation request failed") from None
        if not 200 <= response.status_code < 300:
            raise OpenAIError(
                f"OpenAI generation failed with HTTP {response.status_code}"
            )
        try:
            body = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OpenAIError("OpenAI response was malformed") from None
        if not isinstance(body, dict):
            raise OpenAIError("OpenAI response was malformed")
        if body.get("model") != model:
            raise OpenAIError("OpenAI response model does not match the requested release model.")

        generated = _extract_response_text(body)
        if not generated.strip():
            raise OpenAIError("OpenAI response did not contain text.")
        return generated


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
