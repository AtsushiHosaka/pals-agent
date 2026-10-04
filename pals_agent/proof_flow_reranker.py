from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

import rfc8785

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.private_draft_candidates import DraftCandidateResult
from pals_agent.proof_flow_evidence import DraftEvidence
from pals_agent.reranker_diagnostics import response_diagnostics, sanitize_reranker_diagnostics

_ENDPOINT = "https://api.openai.com/v1/responses"
_DRAFT_ROLE_MODEL = fixed_model_default(ModelRole.DRAFT)
_MODEL = _DRAFT_ROLE_MODEL.model
_PROVIDER = _DRAFT_ROLE_MODEL.provider
_PROVIDER_API = "openai.responses.v1"
_CONTRACT_VERSION = "pals.draft-relevance-reranker.v1"
_PROMPT = (
    "You are the PALS Draft relevance reranker v1. Read REQUEST_JCS. Return only the strict JSON "
    "selection. Select zero through four unique supplied draft IDs in descending semantic "
    "usefulness for proving the exact query. Similarity, lexical overlap, exact equality, and "
    "candidate order are "
    "evidence only. Do not add facts, code, or IDs."
)
_PROMPT_SHA256 = "ee3210814e58edab5fa2a5878100b310d7811df23e3c5f2d09d93d8f3cc03d00"
_MAX_REQUEST_BYTES = 262_144
_MAX_RESPONSE_BYTES = 65_536
_MAX_SELECTION_BYTES = 512


class DraftRerankerInvalidError(RuntimeError):
    """The reranker request or a successful provider envelope is invalid."""

    def __init__(self, message: str, *, private_evidence: object = None) -> None:
        super().__init__(message)
        self.private_evidence = sanitize_reranker_diagnostics(private_evidence)


class DraftRerankerUnavailableError(RuntimeError):
    """The exact one reranker request did not complete within its hard deadline."""


@dataclass(frozen=True, slots=True)
class DraftRerankerUsage:
    input_tokens: int
    cached_input_tokens: int
    uncached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    nonreasoning_output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class DraftRerankerResponse:
    selected_draft_ids: tuple[str, ...]
    usage: DraftRerankerUsage


@dataclass(frozen=True, slots=True)
class DraftRerankerRequest:
    subject_jcs: bytes
    body_jcs: bytes
    compatibility: dict[str, str | int]


@dataclass(frozen=True, slots=True)
class OpenAIDraftReranker:
    api_key: str
    transport: HttpTransport = HardDeadlineHttpTransport(
        max_response_bytes=_MAX_RESPONSE_BYTES
    )

    def __post_init__(self) -> None:
        if not self.api_key.strip() or "\n" in self.api_key or "\r" in self.api_key:
            raise ValueError("OpenAI API key is invalid for the Draft reranker")
        if hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest() != _PROMPT_SHA256:
            raise RuntimeError("Pinned Draft reranker prompt bytes do not match the contract")

    def rerank(self, request: DraftRerankerRequest) -> tuple[str, ...]:
        return self.rerank_response(request).selected_draft_ids

    def rerank_response(self, request: DraftRerankerRequest) -> DraftRerankerResponse:
        try:
            response = self.transport.request(
                method="POST",
                url=_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body=request.body_jcs,
                timeout_seconds=90.0,
            )
        except HardDeadlineHttpError:
            raise DraftRerankerUnavailableError("Draft reranker is unavailable.") from None
        if not 200 <= response.status_code < 300 or len(response.body) > _MAX_RESPONSE_BYTES:
            raise DraftRerankerUnavailableError("Draft reranker is unavailable.")
        parse_progress = {"stage": "json"}
        try:
            return _parse_response(response.body, request=request, parse_progress=parse_progress)
        except (TypeError, ValueError, UnicodeDecodeError):
            raise DraftRerankerInvalidError(
                "Draft reranker returned an invalid response.",
                private_evidence=response_diagnostics(response.body, parse_progress["stage"]),
            ) from None


def build_draft_reranker_request(
    *,
    natural_statement: str,
    query_openmath: str,
    evidence: tuple[DraftEvidence, ...],
    candidates: DraftCandidateResult,
) -> DraftRerankerRequest:
    if not natural_statement or len(natural_statement.encode("utf-8")) > 16_384:
        raise DraftRerankerInvalidError("Draft reranker natural statement is invalid.")
    if len(evidence) != len(candidates.candidates):
        raise DraftRerankerInvalidError("Draft reranker candidates are invalid.")
    if tuple(item.candidate for item in evidence) != candidates.candidates:
        raise DraftRerankerInvalidError("Draft reranker candidate order is invalid.")

    compatibility = _compatibility(candidates)
    subject = {
        "schema_version": "pals.draft-relevance-request.v1",
        "natural_statement": natural_statement,
        "query_openmath": query_openmath,
        "candidates": [_candidate_payload(item) for item in evidence],
        "compatibility": compatibility,
    }
    subject_jcs = rfc8785.dumps(cast(Any, subject))
    provider_input = _PROMPT + "\nREQUEST_JCS\n" + subject_jcs.decode("utf-8")
    body = {
        "input": provider_input,
        "max_output_tokens": 512,
        "model": _MODEL,
        "reasoning": {"effort": "low"},
        "service_tier": "default",
        "store": False,
        "stream": False,
        "text": {
            "format": {
                "name": "pals_draft_relevance_selection_v1",
                "schema": _selection_schema(),
                "strict": True,
                "type": "json_schema",
            }
        },
    }
    body_jcs = rfc8785.dumps(cast(Any, body))
    if len(subject_jcs) > _MAX_REQUEST_BYTES or len(body_jcs) > _MAX_REQUEST_BYTES:
        raise DraftRerankerInvalidError("Draft reranker request exceeds its byte bound.")
    return DraftRerankerRequest(
        subject_jcs=subject_jcs,
        body_jcs=body_jcs,
        compatibility=compatibility,
    )


def _compatibility(candidates: DraftCandidateResult) -> dict[str, str | int]:
    fingerprint = candidates.fingerprint
    return {
        "provider": fingerprint.provider,
        "model": fingerprint.model,
        "endpoint": fingerprint.endpoint,
        "deployment": fingerprint.deployment,
        "revision": fingerprint.revision,
        "dimension": fingerprint.dimension,
        "canonicalizer_version": fingerprint.canonicalizer_version,
        "seed_manifest_sha256": candidates.manifest_sha256,
        "seed_count": candidates.seed_count,
        "runtime_provenance_sha256": candidates.runtime_provenance_sha256,
        "reranker_provider": _PROVIDER,
        "reranker_model": _MODEL,
        "reranker_provider_api": _PROVIDER_API,
        "reranker_contract_version": _CONTRACT_VERSION,
        "reranker_prompt_sha256": _PROMPT_SHA256,
    }


def _candidate_payload(evidence: DraftEvidence) -> dict[str, object]:
    draft = evidence.candidate.draft
    return {
        "draft": {
            "id": draft.id,
            "canonical_statement": draft.matched_prompt,
            "openmath_xml": draft.openmath_xml,
            "proof_strategy": draft.proof_strategy,
            "sketch_steps": list(draft.sketch_steps),
        },
        "evidence": {
            "cosine_distance": evidence.candidate.cosine_distance,
            "vector": evidence.vector_score,
            "structural": evidence.structural_score,
            "exact_equivalence": evidence.exact_equivalence,
        },
    }


def _selection_schema() -> dict[str, object]:
    return {
        "additionalProperties": False,
        "properties": {
            "selected_draft_ids": {
                "items": {"pattern": "^[a-z][a-z0-9_]{0,63}$", "type": "string"},
                "maxItems": 4,
                "type": "array",
            }
        },
        "required": ["selected_draft_ids"],
        "type": "object",
    }


class _JsonPairs(list[tuple[str, Any]]):
    pass


def _parse_response(
    body: bytes, *, request: DraftRerankerRequest,
    parse_progress: dict[str, str] | None = None,
) -> DraftRerankerResponse:
    progress = parse_progress if parse_progress is not None else {}
    progress["stage"] = "json"
    envelope = _decode_json(body)
    progress["stage"] = "envelope"
    root = _object(envelope, exact=None)
    _require(root, "object", "response")
    progress["stage"] = "status"
    _require(root, "status", "completed")
    progress["stage"] = "envelope"
    _require(root, "error", None)
    _require(root, "incomplete_details", None)
    progress["stage"] = "model"
    _require(root, "model", _MODEL)
    progress["stage"] = "usage"
    usage = _usage(root.get("usage"))
    progress["stage"] = "output"
    output = root.get("output")
    if not isinstance(output, list) or len(output) != 1:
        raise ValueError("reranker output is invalid")
    progress["stage"] = "message"
    message = _object(output[0], exact=None)
    _require(message, "type", "message")
    _require(message, "role", "assistant")
    _require(message, "status", "completed")
    for forbidden in ("refusal", "reasoning", "tool", "function", "computer", "custom"):
        if forbidden in message:
            raise ValueError("reranker message is invalid")
    progress["stage"] = "content"
    content = message.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ValueError("reranker message content is invalid")
    text_item = _object(content[0], exact=None)
    _require(text_item, "type", "output_text")
    _require(text_item, "annotations", [])
    if "refusal" in text_item:
        raise ValueError("reranker output text is invalid")
    progress["stage"] = "selection"
    text = text_item.get("text")
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_SELECTION_BYTES:
        raise ValueError("reranker selection text is invalid")
    selection = _object(_decode_json(text.encode("utf-8")), exact={"selected_draft_ids"})
    progress["stage"] = "selection_ids"
    ids = selection["selected_draft_ids"]
    if (
        not isinstance(ids, list)
        or len(ids) > 4
        or not all(isinstance(value, str) for value in ids)
    ):
        raise ValueError("reranker selection is invalid")
    subject = json.loads(request.subject_jcs)
    allowed = {candidate["draft"]["id"] for candidate in subject["candidates"]}
    if len(ids) != len(set(ids)) or any(identifier not in allowed for identifier in ids):
        raise ValueError("reranker selection IDs are invalid")
    return DraftRerankerResponse(selected_draft_ids=tuple(ids), usage=usage)


def _usage(value: object) -> DraftRerankerUsage:
    root = _required_usage_object(
        value,
        required={
            "input_tokens",
            "input_tokens_details",
            "output_tokens",
            "output_tokens_details",
            "total_tokens",
        },
    )
    input_tokens = _token_count(root["input_tokens"])
    output_tokens = _token_count(root["output_tokens"])
    total_tokens = _token_count(root["total_tokens"])
    input_details = _required_usage_object(root["input_tokens_details"], required={"cached_tokens"})
    output_details = _required_usage_object(
        root["output_tokens_details"], required={"reasoning_tokens"}
    )
    cached_input_tokens = _token_count(input_details["cached_tokens"])
    reasoning_output_tokens = _token_count(output_details["reasoning_tokens"])
    if (
        cached_input_tokens > input_tokens
        or reasoning_output_tokens > output_tokens
        or total_tokens != input_tokens + output_tokens
    ):
        raise ValueError("reranker usage is inconsistent")
    return DraftRerankerUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        uncached_input_tokens=input_tokens - cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        nonreasoning_output_tokens=output_tokens - reasoning_output_tokens,
        total_tokens=total_tokens,
    )


def _required_usage_object(value: object, *, required: set[str]) -> dict[str, object]:
    # Provider usage may add metadata. Only the required counts inform usage;
    # unknown values are not projected, retained, or used for acceptance.
    root = _object(value, exact=None)
    if not required.issubset(root):
        raise ValueError("reranker usage is missing required fields")
    return root


def _token_count(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 9_223_372_036_854_775_807:
        raise ValueError("reranker usage count is invalid")
    return value


def _decode_json(body: bytes) -> object:
    text = body.decode("utf-8")
    decoder = json.JSONDecoder(object_pairs_hook=_JsonPairs)
    start = len(text) - len(text.lstrip(" \t\r\n"))
    value, index = decoder.raw_decode(text, start)
    if text[index:].strip():
        raise ValueError("JSON has trailing data")
    return value


def _object(value: object, *, exact: set[str] | None) -> dict[str, object]:
    if not isinstance(value, _JsonPairs):
        raise ValueError("value is not a JSON object")
    keys = [key for key, _value in value]
    if len(keys) != len(set(keys)):
        raise ValueError("JSON object has duplicate keys")
    object_value = dict(value)
    if exact is not None and set(object_value) != exact:
        raise ValueError("JSON object has an invalid shape")
    return object_value


def _require(root: dict[str, object], key: str, expected: object) -> None:
    if root.get(key, object()) != expected:
        raise ValueError(f"reranker field {key} is invalid")
