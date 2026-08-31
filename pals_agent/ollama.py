from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OllamaClient:
    host: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 60.0
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
        endpoint = self.host.rstrip("/") + "/api/generate"
        data = json.dumps(
                {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 900},
                }
            ).encode("utf-8")
        timeout = _transport_timeout(timeout_seconds, self.timeout_seconds)
        try:
            response = self.transport.request(
                method="POST",
                url=endpoint,
                headers={"Content-Type": "application/json"},
                body=data,
                timeout_seconds=timeout,
            )
        except HardDeadlineHttpError:
            raise OllamaError("Ollama generation request failed") from None
        if not 200 <= response.status_code < 300:
            raise OllamaError(
                f"Ollama generation failed with HTTP {response.status_code}"
            )
        try:
            body = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OllamaError("Ollama response was malformed") from None
        if not isinstance(body, dict):
            raise OllamaError("Ollama response was malformed")

        generated = body.get("response")
        if not isinstance(generated, str) or not generated.strip():
            raise OllamaError("Ollama response did not contain text.")
        return generated


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
