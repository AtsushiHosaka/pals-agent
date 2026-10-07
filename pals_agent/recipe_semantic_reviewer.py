"""Dedicated RPCS reviewer actor. It has no candidate-worker API credential.

The queue-owning worker only requests a review by job/candidate identity. All proof
content is fetched through the reviewer-only API, in an independent model session.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import socket
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pals_agent.api_client import (
    PalsApiClient,
    PalsApiError,
    _canonical_claim_id,
    _path_segment,
    _validate_recipe_semantic_review_evidence,
)
from pals_agent.explanations import (
    LeanProofSemanticReviewer,
    ProofSemanticReviewer,
    ProofSemanticReviewUnavailable,
)
from pals_agent.http_transport import HardDeadlineHttpTransport, HttpTransport
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.linked_chat import linked_chat_scope
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.settings import validate_release_generation_environment
from pals_agent.worker import _recipe_semantic_review_evidence, _semantic_review_unavailable_payload

_HEADER = "X-PALS-Recipe-Semantic-Reviewer-Secret"
_REQUESTER_HEADER = "X-PALS-Recipe-Review-Requester-Secret"
_INPUT_KEYS = {
    "id",
    "state",
    "verification_candidate_id",
    "mutation_claim_id",
    "result_artifact_uri",
    "attempt_source",
    "source_binding_sha256",
    "theorem_statement",
    "formal_statement",
    "lean_code",
    "target_declaration",
}


@dataclass(frozen=True, slots=True)
class RecipeSemanticReviewApiClient:
    base_url: str
    reviewer_secret: str = field(repr=False)
    timeout_seconds: float = 15
    transport: HttpTransport = field(default_factory=HardDeadlineHttpTransport, repr=False)
    attachment_transport: HttpTransport = field(
        default_factory=lambda: HardDeadlineHttpTransport(max_response_bytes=28_000_000),
        repr=False,
    )

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.reviewer_secret.strip():
            raise ValueError("Dedicated reviewer credential is required")
        # Reuse transport/error handling; this object never contains a worker credential.
        return PalsApiClient(self.base_url, "", self.timeout_seconds, self.transport)._request(
            method, path, payload, headers={_HEADER: self.reviewer_secret}
        )

    def get_input(self, proof_job_id: str, candidate_id: str) -> dict[str, Any]:
        result = self._request(
            "GET",
            f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}"
            f"/semantic-review-input?candidate_id={_canonical_claim_id(candidate_id)}",
        )
        if (
            set(result) not in (_INPUT_KEYS, _INPUT_KEYS | {"chat_input_available"})
            or type(result.get("chat_input_available", False)) is not bool
            or result.get("id") != proof_job_id
            or result.get("verification_candidate_id") != candidate_id
            or result.get("attempt_source") not in {"recipe", "model"}
        ):
            raise ValueError("Dedicated reviewer input is not bound to the requested candidate")
        return result

    def get_chat_input(self, proof_job_id: str, candidate_id: str) -> dict[str, Any]:
        client = PalsApiClient(
            self.base_url, "", self.timeout_seconds,
            self.attachment_transport,
        )
        return client._request(
            "GET", f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}"
            f"/chat-input?candidate_id={_canonical_claim_id(candidate_id)}",
            headers={_HEADER: self.reviewer_secret},
        )

    def settle(self, proof_job_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        _validate_recipe_semantic_review_evidence(evidence)
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}/semantic-reviews",
            evidence,
        )

    def settle_unavailable(self, proof_job_id: str, failure: dict[str, Any]) -> dict[str, Any]:
        if failure.get("source_binding_sha256") is None:
            raise ValueError("Dedicated review requires an immutable source binding")
        return self._request(
            "POST",
            f"/v1/internal/proof-jobs/{_path_segment(proof_job_id)}/semantic-review-unavailable",
            failure,
        )


class ReviewBusyError(RuntimeError):
    pass


class RecipeReviewActor:
    def __init__(
        self,
        api: RecipeSemanticReviewApiClient,
        reviewer_factory: Callable[[], ProofSemanticReviewer],
        *,
        timeout_seconds: float = 90,
    ) -> None:
        self.api, self.reviewer_factory = api, reviewer_factory
        self.timeout_seconds = timeout_seconds
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def review(self, proof_job_id: str, candidate_id: str) -> dict[str, Any]:
        _path_segment(proof_job_id)
        _canonical_claim_id(candidate_id)
        with self._lock:
            if proof_job_id in self._active or len(self._active) >= 4:
                raise ReviewBusyError("Review is already active")
            self._active.add(proof_job_id)
        try:
            content = self.api.get_input(proof_job_id, candidate_id)
            if content["state"] in {"verified", "failed", "canceled"}:
                return content
            if content["state"] != "semantic_review":
                raise ValueError("Candidate is not ready for review")
            source = content["lean_code"]
            target = extract_single_target_declaration(source)
            if target is None or target.as_dict() != content["target_declaration"]:
                raise ValueError("Review target differs from exact source")
            try:
                chat_payload = (
                    self.api.get_chat_input(proof_job_id, candidate_id)
                    if content.get("chat_input_available") is True else None
                )
                chat_context = {
                    "chat_route": chat_payload["chat_route"],
                    "generation_model": chat_payload["request"]["generation_model"],
                } if chat_payload is not None else {}
                with linked_chat_scope(chat_context, chat_payload):
                    review = self.reviewer_factory().review_proof(
                        theorem_statement=content["theorem_statement"],
                        formal_statement=content["formal_statement"],
                        target_declaration=target,
                        lean_code=source,
                        timeout_seconds=self.timeout_seconds,
                    )
                evidence = _recipe_semantic_review_evidence(
                    candidate_id=candidate_id,
                    theorem_statement=content["theorem_statement"],
                    formal_statement=content["formal_statement"],
                    lean_code=source,
                    target_declaration=target,
                    source_binding_sha256=content["source_binding_sha256"],
                    review=review,
                )
            except Exception as exc:
                self.api.settle_unavailable(proof_job_id, _semantic_review_unavailable_payload(
                    candidate_id=candidate_id, mutation_claim_id=content["mutation_claim_id"],
                    theorem_statement=content["theorem_statement"],
                    formal_statement=content["formal_statement"], lean_code=source,
                    target_declaration=target, result_artifact_uri=content["result_artifact_uri"],
                    source_binding_sha256=content["source_binding_sha256"],
                    failure_kind=(
                        exc.failure_kind if isinstance(exc, ProofSemanticReviewUnavailable)
                        else "internal"
                    ),
                ))
            else:
                self.api.settle(proof_job_id, evidence)
            settled = self.api.get_input(proof_job_id, candidate_id)
            if settled["state"] not in {"verified", "failed"}:
                raise ValueError("Review did not reach durable settlement")
            return settled
        finally:
            with self._lock:
                self._active.remove(proof_job_id)


class BoundedReviewServer(ThreadingHTTPServer):
    """Bound connections before allocating a handler thread or parsing headers."""

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        max_requests: int = 16,
        request_timeout_seconds: float = 5,
    ) -> None:
        if max_requests < 1 or request_timeout_seconds <= 0:
            raise ValueError("HTTP capacity and timeout must be positive")
        self._slots = threading.BoundedSemaphore(max_requests)
        self._request_timeout = request_timeout_seconds
        super().__init__(address, handler)

    def get_request(self) -> tuple[socket.socket, Any]:
        connection, address = super().get_request()
        connection.settimeout(self._request_timeout)
        return connection, address

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            with suppress(OSError):
                request.sendall(
                    b"HTTP/1.0 503 Service Unavailable\r\nConnection: close\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def create_server(
    actor: RecipeReviewActor,
    requester_secret: str,
    *,
    host: str = "0.0.0.0",
    port: int = 18119,
    max_http_requests: int = 16,
    request_timeout_seconds: float = 5,
) -> BoundedReviewServer:
    if not requester_secret.strip() or requester_secret == actor.api.reviewer_secret:
        raise ValueError("Requester and reviewer credentials must be distinct")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Never log request bodies, authorization headers, or proof content.

        def do_POST(self) -> None:
            secrets = (self.headers.get_all(_REQUESTER_HEADER) or [])
            secret = secrets[0] if len(secrets) == 1 else ""
            if not hmac.compare_digest(secret.encode("utf-8"), requester_secret.encode("utf-8")):
                self._send(401, {"error": "unauthorized"})
                return
            if self.path != "/v1/reviews":
                self._send(404, {"error": "not_found"})
                return
            try:
                lengths = (self.headers.get_all("Content-Length") or [])
                types = (self.headers.get_all("Content-Type") or [])
                if (
                    len(lengths) != 1
                    or len(types) != 1
                    or self.headers.get_all("Transfer-Encoding")
                    or not re.fullmatch(r"[1-9][0-9]{0,3}", lengths[0], re.ASCII)
                    or types[0].lower()
                    not in {"application/json", "application/json; charset=utf-8"}
                ):
                    raise ValueError("ambiguous request framing")
                length = int(lengths[0])
                if not 1 <= length <= 1024:
                    raise ValueError("request length")
                payload = json.loads(self.rfile.read(length), object_pairs_hook=_closed_object)
                if not isinstance(payload, dict) or set(payload) != {
                    "proof_job_id",
                    "candidate_id",
                }:
                    raise ValueError("closed request")
                result = actor.review(payload["proof_job_id"], payload["candidate_id"])
            except ReviewBusyError:
                self._send(503, {"error": "review_busy"})
            except PalsApiError as exc:
                self._send(
                    409 if exc.status_code in {404, 409} else 503, {"error": "review_unavailable"}
                )
            except (ValueError, TypeError, KeyError, UnicodeError):
                self._send(400, {"error": "invalid_review_request"})
            except Exception:
                self._send(503, {"error": "review_unavailable"})
            else:
                self._send(200, result)

        def _send(self, code: int, value: dict[str, Any]) -> None:
            raw = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return BoundedReviewServer(
        (host, port),
        Handler,
        max_requests=max_http_requests,
        request_timeout_seconds=request_timeout_seconds,
    )


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate request key")
    return value


def main() -> None:
    # These credentials would let this process act as candidate generator/selector.
    if any(
        os.environ.get(key)
        for key in (
            "PALS_WORKER_SHARED_SECRET",
            "PALS_AGENT_WORKER_SECRET",
            "PALS_RECIPE_WORKER_SECRET",
            "PALS_RECIPE_CURATION_SECRET",
        )
    ):
        raise ValueError("Dedicated reviewer must not receive candidate/curator credentials")
    validate_release_generation_environment()
    reviewer_secret = os.environ["PALS_RECIPE_SEMANTIC_REVIEWER_SECRET"]
    requester_secret = os.environ["PALS_RECIPE_REVIEW_REQUESTER_SECRET"]
    api = RecipeSemanticReviewApiClient(os.environ["PALS_API_BASE_URL"], reviewer_secret)
    binding = fixed_model_default(ModelRole.PROOF_REVIEW)
    key = os.environ.get("PALS_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    if not key.strip():
        raise ValueError("Reviewer OpenAI credential is required")

    def reviewer() -> ProofSemanticReviewer:
        return LeanProofSemanticReviewer(
            client=OpenAIResponsesClient(
                api_key=key,
                base_url=os.environ.get("PALS_OPENAI_BASE_URL", "https://api.openai.com/v1"),
                max_output_tokens=int(os.environ.get("PALS_OPENAI_MAX_OUTPUT_TOKENS", "16384")),
            ),
            model=binding.model,
            provider=binding.provider,
            max_attempts=2,
        )

    timeout = int(os.environ.get("PALS_EXPLANATION_MODEL_TIMEOUT_SECONDS", "90"))
    if not 1 <= timeout <= 300:
        raise ValueError("Reviewer timeout must be bounded")
    server = create_server(
        RecipeReviewActor(api, reviewer, timeout_seconds=timeout), requester_secret
    )
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
