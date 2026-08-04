from __future__ import annotations

import json
import math
import re
import struct
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import rfc8785

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.models import ProofDraft
from pals_agent.openmath import validate_canonical_retrieval_openmath_xml

_PATH = "/v1/internal/proof-flow-index/candidates"
_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v4"
_MAX_BODY_BYTES = 262_144
_MAX_CANDIDATE_BYTES = 16_384
_MAX_TEXT_CODE_POINTS = 20_000
_MAX_STEPS = 256
_MAX_CANDIDATES = 8
_ELIGIBLE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# The runtime validates these values before it spends the embedding/API budget.  Keep the exact
# DTO normalization here too so the runtime and the private-port boundary cannot drift apart.
CANONICALIZER_VERSION = _CANONICALIZER_VERSION


class DraftCandidateCompatibilityError(RuntimeError):
    """The private API response cannot represent the admitted active catalog."""


class DraftCandidateLimitError(DraftCandidateCompatibilityError):
    """The private API returned more than eight candidates or duplicate Draft IDs."""


class DraftCandidateUnavailableError(RuntimeError):
    """The private API cannot be reached within its fixed retrieval budget."""


@dataclass(frozen=True, slots=True)
class DraftEmbeddingFingerprint:
    provider: str
    model: str
    endpoint: str
    deployment: str
    revision: str
    dimension: int
    canonicalizer_version: str = _CANONICALIZER_VERSION

    def as_json(self) -> dict[str, str | int]:
        return {
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "revision": self.revision,
            "dimension": self.dimension,
            "canonicalizer_version": self.canonicalizer_version,
        }


@dataclass(frozen=True, slots=True)
class DraftCandidate:
    draft: ProofDraft
    cosine_distance: float


@dataclass(frozen=True, slots=True)
class DraftCandidateResult:
    generation_id: str
    manifest_sha256: str
    seed_count: int
    runtime_provenance_sha256: str
    fingerprint: DraftEmbeddingFingerprint
    candidates: tuple[DraftCandidate, ...]


def validate_draft_embedding_fingerprint(
    fingerprint: DraftEmbeddingFingerprint,
) -> DraftEmbeddingFingerprint:
    """Return the exact PFI fingerprint or reject it before any provider/API call."""
    if not isinstance(fingerprint, DraftEmbeddingFingerprint):
        raise ValueError("embedding fingerprint is invalid")
    return _fingerprint_from_value(fingerprint.as_json())


def normalize_draft_embedding(
    embedding: object,
    *,
    fingerprint: DraftEmbeddingFingerprint,
) -> list[float]:
    """Validate the exact binary32 request vector at the shared Agent boundary."""
    normalized_fingerprint = validate_draft_embedding_fingerprint(fingerprint)
    return _embedding(embedding, dimension=normalized_fingerprint.dimension)


@dataclass(frozen=True, slots=True)
class PrivateDraftCandidateClient:
    """The only Agent-side path to active Draft candidates.

    The client deliberately knows no catalog, database, retry, or fallback behavior.  It owns one
    bounded worker-authenticated HTTP call and rejects a response before exposing any Draft row.
    """

    base_url: str
    worker_secret: str
    transport: HttpTransport = field(
        default_factory=lambda: HardDeadlineHttpTransport(max_response_bytes=_MAX_BODY_BYTES),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_api_base_url(self.base_url)
        if (
            not self.worker_secret.strip()
            or "\n" in self.worker_secret
            or "\r" in self.worker_secret
        ):
            raise ValueError("PFI worker secret is invalid")

    def find_candidates(
        self,
        *,
        embedding: list[float],
        fingerprint: DraftEmbeddingFingerprint,
    ) -> DraftCandidateResult:
        try:
            payload = _request_payload(embedding=embedding, fingerprint=fingerprint)
        except (TypeError, ValueError, struct.error):
            raise DraftCandidateCompatibilityError(
                "Draft retrieval input is incompatible."
            ) from None
        body = rfc8785.dumps(cast(Any, payload))
        if len(body) > _MAX_BODY_BYTES:
            raise DraftCandidateCompatibilityError("Draft retrieval input is incompatible.")

        try:
            response = self.transport.request(
                method="POST",
                url=self.base_url.rstrip("/") + _PATH,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-PALS-Worker-Secret": self.worker_secret,
                },
                body=body,
                timeout_seconds=10.0,
            )
        except HardDeadlineHttpError:
            raise DraftCandidateUnavailableError("Draft retrieval is unavailable.") from None

        if len(response.body) > _MAX_BODY_BYTES:
            raise DraftCandidateCompatibilityError("Draft catalog is incompatible.")
        if response.status_code != 200:
            _raise_api_error(response.status_code, response.body)
        if _header_values(response.headers, "content-type") != ("application/json",):
            raise DraftCandidateCompatibilityError("Draft catalog is incompatible.")
        try:
            decoded = _decode_json(response.body)
            return _candidate_result(decoded, expected_fingerprint=fingerprint)
        except DraftCandidateLimitError:
            raise
        except (TypeError, ValueError):
            raise DraftCandidateCompatibilityError("Draft catalog is incompatible.") from None


class _JsonPairs(list[tuple[str, Any]]):
    pass


def _validate_api_base_url(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() or ord(character) < 0x20 for character in value)
    ):
        raise ValueError("PFI API base URL must be an absolute origin")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("PFI API base URL must be an absolute origin") from exc
    if (
        parts.scheme not in {"http", "https"}
        or parts.hostname is None
        or port is not None and not 1 <= port <= 65_535
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("PFI API base URL must be an absolute origin")


def _request_payload(
    *,
    embedding: list[float],
    fingerprint: DraftEmbeddingFingerprint,
) -> dict[str, object]:
    normalized_fingerprint = validate_draft_embedding_fingerprint(fingerprint)
    normalized_embedding = normalize_draft_embedding(
        embedding,
        fingerprint=normalized_fingerprint,
    )
    return {
        "schema_version": "pals.draft-candidate-query.v1",
        "embedding": normalized_embedding,
        "fingerprint": normalized_fingerprint.as_json(),
    }


def _candidate_result(
    value: object,
    *,
    expected_fingerprint: DraftEmbeddingFingerprint,
) -> DraftCandidateResult:
    root = _exact_object(
        value,
        {
            "schema_version",
            "generation_id",
            "manifest_sha256",
            "seed_count",
            "runtime_provenance_sha256",
            "fingerprint",
            "candidates",
        },
    )
    if root["schema_version"] != "pals.draft-candidate-result.v1":
        raise ValueError("candidate result schema is invalid")
    generation_id = _uuid4(root["generation_id"])
    manifest_sha256 = _manifest(root["manifest_sha256"])
    seed_count = _bounded_int(root["seed_count"], minimum=0, maximum=4096)
    runtime_provenance_sha256 = _hex64(root["runtime_provenance_sha256"])
    fingerprint = _fingerprint_from_value(root["fingerprint"])
    if fingerprint != expected_fingerprint:
        raise ValueError("candidate result fingerprint does not match the request")
    raw_candidates = root["candidates"]
    if not isinstance(raw_candidates, list):
        raise ValueError("candidate collection is invalid")
    if len(raw_candidates) > _MAX_CANDIDATES:
        raise DraftCandidateLimitError("candidate collection exceeds the retrieval limit")
    candidates = tuple(_candidate(item) for item in raw_candidates)
    identities = [candidate.draft.id for candidate in candidates]
    if len(identities) != len(set(identities)):
        raise DraftCandidateLimitError("candidate IDs are not unique")
    if len(candidates) > seed_count:
        raise ValueError("candidate collection exceeds the active seed count")
    if len(candidates) != min(_MAX_CANDIDATES, seed_count):
        raise ValueError("candidate collection is incomplete for the active seed count")
    expected_order = tuple(
        sorted(
            candidates,
            key=lambda item: (item.cosine_distance, item.draft.id.encode("utf-8")),
        )
    )
    if expected_order != candidates:
        raise ValueError("candidate order is invalid")
    return DraftCandidateResult(
        generation_id=generation_id,
        manifest_sha256=manifest_sha256,
        seed_count=seed_count,
        runtime_provenance_sha256=runtime_provenance_sha256,
        fingerprint=fingerprint,
        candidates=candidates,
    )


def _candidate(value: object) -> DraftCandidate:
    root = _exact_object(value, {"draft", "cosine_distance"})
    draft_value = _exact_object(
        root["draft"],
        {"id", "canonical_statement", "openmath_xml", "proof_strategy", "sketch_steps"},
    )
    draft_id = draft_value["id"]
    if not isinstance(draft_id, str) or not _ELIGIBLE_ID.fullmatch(draft_id):
        raise ValueError("candidate Draft ID is invalid")
    canonical_statement = _text(draft_value["canonical_statement"])
    openmath_xml = validate_canonical_retrieval_openmath_xml(
        _text(draft_value["openmath_xml"])
    )
    proof_strategy = _text(draft_value["proof_strategy"])
    sketch_steps_value = draft_value["sketch_steps"]
    if not isinstance(sketch_steps_value, list) or len(sketch_steps_value) > _MAX_STEPS:
        raise ValueError("candidate sketch steps are invalid")
    sketch_steps = tuple(_text(item) for item in sketch_steps_value)
    draft = ProofDraft(
        id=draft_id,
        matched_prompt=canonical_statement,
        openmath_xml=openmath_xml,
        proof_strategy=proof_strategy,
        sketch_steps=sketch_steps,
    )
    candidate_projection = {
        "canonical_statement": canonical_statement,
        "id": draft_id,
        "openmath_xml": openmath_xml,
        "proof_strategy": proof_strategy,
        "sketch_steps": list(sketch_steps),
    }
    if len(rfc8785.dumps(candidate_projection)) > _MAX_CANDIDATE_BYTES:
        raise ValueError("candidate exceeds the aggregate byte bound")
    return DraftCandidate(draft=draft, cosine_distance=_finite_number(root["cosine_distance"]))


def _fingerprint_from_value(value: object) -> DraftEmbeddingFingerprint:
    root = _exact_object(
        value,
        {
            "provider",
            "model",
            "endpoint",
            "deployment",
            "revision",
            "dimension",
            "canonicalizer_version",
        },
    )
    canonicalizer_version = root["canonicalizer_version"]
    if canonicalizer_version != _CANONICALIZER_VERSION:
        raise ValueError("fingerprint canonicalizer is invalid")
    return DraftEmbeddingFingerprint(
        provider=_text(root["provider"]),
        model=_text(root["model"]),
        endpoint=_text(root["endpoint"]),
        deployment=_text(root["deployment"]),
        revision=_text(root["revision"]),
        dimension=_bounded_int(root["dimension"], minimum=1, maximum=4096),
        canonicalizer_version=canonicalizer_version,
    )


def _embedding(value: object, *, dimension: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise ValueError("embedding dimension is invalid")
    normalized: list[float] = []
    for component in value:
        numeric = _finite_number(component)
        try:
            binary32 = struct.unpack("!f", struct.pack("!f", numeric))[0]
        except OverflowError as exc:
            raise ValueError("embedding is not finite binary32") from exc
        if not math.isfinite(binary32):
            raise ValueError("embedding is not finite binary32")
        normalized.append(binary32)
    if not any(component != 0.0 for component in normalized):
        raise ValueError("embedding has zero norm")
    return normalized


def _decode_json(raw: bytes) -> object:
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_JsonPairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate response is not valid JSON") from exc
    return _reject_duplicate_members(decoded)


def _reject_duplicate_members(value: object) -> object:
    if isinstance(value, _JsonPairs):
        result: dict[str, object] = {}
        for key, child in value:
            if key in result:
                raise ValueError("candidate response has duplicate members")
            result[key] = _reject_duplicate_members(child)
        return result
    if isinstance(value, list):
        return [_reject_duplicate_members(item) for item in value]
    return value


def _exact_object(value: object, expected: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected or not all(
        isinstance(key, str) for key in value
    ):
        raise ValueError("candidate object does not match the closed DTO")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT_CODE_POINTS:
        raise ValueError("candidate text is invalid")
    return value


def _bounded_int(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("candidate integer is invalid")
    return value


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("candidate number is invalid")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("candidate number is invalid")
    return 0.0 if numeric == 0.0 else numeric


def _uuid4(value: object) -> str:
    if not isinstance(value, str) or not _UUID4.fullmatch(value):
        raise ValueError("candidate generation ID is invalid")
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("candidate generation ID is invalid")
    return value


def _manifest(value: object) -> str:
    if not isinstance(value, str) or not _MANIFEST.fullmatch(value):
        raise ValueError("candidate manifest digest is invalid")
    return value


def _hex64(value: object) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError("candidate provenance digest is invalid")
    return value


def _header_values(headers: tuple[tuple[str, str], ...], name: str) -> tuple[str, ...]:
    return tuple(value for key, value in headers if key.lower() == name)


def _raise_api_error(status_code: int, raw: bytes) -> None:
    code = _api_error_code(raw)
    if status_code == 409 and code == "draft_catalog_incompatible":
        raise DraftCandidateCompatibilityError("Draft catalog is incompatible.")
    if status_code == 503 and code == "draft_retrieval_unavailable":
        raise DraftCandidateUnavailableError("Draft retrieval is unavailable.")
    raise DraftCandidateCompatibilityError("Draft catalog is incompatible.")


def _api_error_code(raw: bytes) -> str | None:
    try:
        value = _decode_json(raw)
    except ValueError:
        return None
    if not isinstance(value, dict) or set(value) != {"error"}:
        return None
    error = value["error"]
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None
