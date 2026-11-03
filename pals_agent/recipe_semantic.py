"""Claim-bound dual review of the API-owned retrieved Recipe window."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from pals_agent.math_conventions import known_readings, parse_claim
from pals_agent.model_roles import RECIPE_SEMANTIC_MODEL, RECIPE_SEMANTIC_REASONING_EFFORT
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse_usage import model_role
from pals_agent.recipe_retrieval import query_embedding
from pals_agent.recipe_semantic_contract import (
    MAX_OUTPUT_TOKENS,
    SCHEMA,
    consensus,
    fresh_plain_request,
    parse,
    prompts,
    read_batch,
    uuid,
)
from pals_agent.runtime_latency import latency_stage
from pals_agent.usage import capture_usage

RecipeBatch = Callable[[list[float] | None], dict[str, Any]]
_ROLES = {"assessment": "recipe_semantic_assessment", "review": "token_answer_qa"}


class SemanticReuseError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SemanticAttempt:
    answer: dict[str, Any] | None
    evidence: dict[str, Any]


def attempt(
    client: OpenAIResponsesClient,
    request: dict[str, Any],
    claim_id: str,
    batch_loader: RecipeBatch,
    *,
    deadline: float,
) -> SemanticAttempt | None:
    """Both real calls inspect the same API-ranked window; ranking never admits a match."""
    if not fresh_plain_request(request):
        return None
    if time.monotonic() >= deadline:
        raise SemanticReuseError("proof_reuse_deadline")
    batch = batch_loader(query_embedding(client, request["statement"], deadline=deadline))
    try:
        with latency_stage("recipe_batch_validate"):
            rows = read_batch(request, claim_id, batch)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise SemanticReuseError("proof_reuse_recipe_invalid") from error
    if rows is None:
        return None
    conventions = parse_claim(request.get("math_conventions"))
    if conventions is None:
        raise SemanticReuseError("proof_reuse_input_invalid")
    known = known_readings(conventions)
    sessions = {key: str(uuid4()) for key in _ROLES}
    try:
        with latency_stage("recipe_prompt_build"):
            inputs = prompts(
                request,
                batch,
                known,
                assessment_session=sessions["assessment"],
                review_session=sessions["review"],
            )
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise SemanticReuseError("proof_reuse_recipe_invalid") from error
    fixed_client = replace(
        client,
        reasoning_effort=RECIPE_SEMANTIC_REASONING_EFFORT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    def judge(position: str) -> dict[str, Any]:
        remaining = min(45.0, deadline - time.monotonic())
        if remaining < 1:
            raise SemanticReuseError("proof_reuse_deadline")
        provider_ids: list[str] = []
        with model_role(_ROLES[position]), capture_usage() as records:
            raw = fixed_client.generate(
                model=RECIPE_SEMANTIC_MODEL,
                prompt=inputs[position],
                response_schema=SCHEMA,
                timeout_seconds=remaining,
                response_callback=provider_ids.append,
                store=False,
            )
        # Metadata comes from the actual response/usage producer, never a model's
        # generated JSON or an invented provider/session approval.
        if len(records) != 1 or len(provider_ids) != 1:
            raise SemanticReuseError("proof_reuse_token_accounting_failed")
        record = records[0]
        if (
            not uuid(record.get("call_id"))
            or record.get("model") != RECIPE_SEMANTIC_MODEL
            or record.get("provider") != "openai"
            or record.get("provider_request_id") != provider_ids[0]
            or re.fullmatch(r"resp_[A-Za-z0-9_-]+", provider_ids[0]) is None
        ):
            raise SemanticReuseError("proof_reuse_token_accounting_failed")
        try:
            with latency_stage("recipe_response_parse"):
                result = parse(raw, batch, known)
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise SemanticReuseError("proof_reuse_invalid_response") from error
        return {
            "session_id": sessions[position],
            "call_id": record["call_id"],
            "provider_request_id": provider_ids[0],
            "result": result,
        }

    # Separate Context objects preserve the role, image, billing and reporter
    # boundaries. Pool shutdown joins BOTH requests and their receipts on error.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="pals-semantic-recipe") as pool:
        left = pool.submit(copy_context().run, judge, "assessment")
        right = pool.submit(copy_context().run, judge, "review")
        assessment, review = left.result(), right.result()
    if any(
        assessment[key] == review[key]
        for key in (
            "session_id",
            "call_id",
            "provider_request_id",
        )
    ):
        raise SemanticReuseError("proof_reuse_invalid_response")
    selected = consensus(assessment["result"], review["result"], batch)
    diagnostic = {
        "batch_sha256": batch["batch_sha256"],
        "assessment": assessment,
        "review": review,
    }
    if selected is None:
        return SemanticAttempt(None, {"recipe_semantic_attempt": diagnostic})
    pins = {
        key: selected[key]
        for key in (
            "entry_sha256",
            "lean_sha256",
            "answer_sha256",
            "compiler_receipt_sha256",
            "toolchain_sha256",
        )
    }
    receipt = {
        "schema_version": "pals.recipe-semantic-correspondence.v1",
        "request_id": request["id"],
        "claim_id": claim_id,
        "request_revision": request["revision"],
        "request_context_sha256": batch["request_context_sha256"],
        "batch_sha256": batch["batch_sha256"],
        **pins,
        "target_sha256": hashlib.sha256(selected["target_source"].encode()).hexdigest(),
        "assessment": assessment,
        "review": review,
    }
    lean = {
        "source": "catalog",
        **pins,
        "recipe_id": selected["recipe_id"],
        "recipe_revision": selected["recipe_revision"],
    }
    return SemanticAttempt(
        {"text": selected["answer"], "evidence_kind": "lean_catalog", "sources": [], "lean": lean},
        {
            "schema_version": "pals.proof-reuse-assessment.v1",
            "phase": "recipe_semantic_review",
            "lean_route": "catalog_reuse_semantic",
            "recipe_semantic_correspondence": receipt,
            "applied_conventions": [
                {"id": key, "choice": known[key]}
                for key in sorted(assessment["result"]["relevant_conventions"])
            ],
            "token_qa": {
                "approved": True,
                "answer_sha256": selected["answer_sha256"],
                "call_id": review["call_id"],
            },
        },
    )
