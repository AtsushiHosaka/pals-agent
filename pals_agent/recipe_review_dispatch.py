"""Ask the isolated reviewer to act; this client cannot settle a semantic review."""

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from pals_agent.http_transport import HardDeadlineHttpTransport, HttpTransport


@dataclass(frozen=True, slots=True)
class RecipeReviewDispatcher:
    base_url: str
    requester_secret: str = field(repr=False)
    transport: HttpTransport = field(default_factory=HardDeadlineHttpTransport, repr=False)

    def __post_init__(self) -> None:
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or (
                url.scheme == "http"
                and url.hostname
                not in {"pals-recipe-reviewer", "recipe-reviewer", "localhost", "127.0.0.1", "::1"}
            )
            or not self.requester_secret
            or not self.requester_secret.isascii()
            or any(ord(c) < 33 or ord(c) > 126 for c in self.requester_secret)
        ):
            raise ValueError("Recipe reviewer dispatch configuration is invalid")

    def request(self, *, proof_job_id: str, candidate_id: str, timeout_seconds: float) -> None:
        # The reviewer fetches all source/evidence from the API, never from this caller.
        payload = {"proof_job_id": str(UUID(proof_job_id)), "candidate_id": str(UUID(candidate_id))}
        response = self.transport.request(
            method="POST",
            url=self.base_url.rstrip("/") + "/v1/reviews",
            headers={
                "Content-Type": "application/json",
                "X-PALS-Recipe-Review-Requester-Secret": self.requester_secret,
            },
            body=json.dumps(payload, separators=(",", ":")).encode(),
            timeout_seconds=timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError("Recipe reviewer did not complete the request")
        result: Any = json.loads(response.body)
        if not isinstance(result, dict) or result.get("id") != proof_job_id:
            raise RuntimeError("Recipe reviewer returned a malformed response")
        # A 200 is only a dispatch acknowledgement. The worker must independently read
        # terminal state from its authoritative API before acknowledging its SQS receipt.
