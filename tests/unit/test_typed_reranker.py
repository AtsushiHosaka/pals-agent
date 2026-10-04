"""Typed selection wire-contract tests. Provider doubles do not prove semantic quality."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import rfc8785

from pals_agent.http_transport import HttpResponse
from pals_agent.models import ProofDraft
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateResult,
    DraftEmbeddingFingerprint,
)
from pals_agent.proof_flow_evidence import DraftEvidence
from pals_agent.proof_flow_reranker import (
    DraftRerankerInvalidError,
    DraftRerankerUnavailableError,
    OpenAIDraftReranker,
    build_draft_reranker_request,
)
from pals_agent.typed_local_catalog import load_typed_local_catalog_manifest
from pals_agent.typed_reranker import (
    CONTRACT_VERSION,
    PROMPT,
    PROMPT_SHA256,
    build_typed_draft_reranker_request,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def arguments():
    manifest = load_typed_local_catalog_manifest(
        ROOT / "docs/typed-math-matrix-v1-authoring-manifest.proposal.json",
        repository_root=ROOT,
    )
    candidates = tuple(
        DraftCandidate(
            ProofDraft(
                id=card.card_id,
                matched_prompt=card.canonical_statement,
                openmath_xml=card.canonical_openmath_xml,
                proof_strategy=card.proof_strategy,
                sketch_steps=card.sketch_steps,
            ),
            cosine_distance=0.125 + i / 100,
        )
        for i, card in enumerate(manifest.cards[:2])
    )
    population = DraftCandidateResult(
        generation_id="11111111-1111-4111-8111-111111111111",
        manifest_sha256="sha256:" + "a" * 64,
        seed_count=2,
        runtime_provenance_sha256="b" * 64,
        fingerprint=DraftEmbeddingFingerprint(
            provider="openai",
            model="text-embedding-3-small",
            endpoint="https://api.openai.com/v1",
            deployment="text-embedding-3-small",
            revision="openai-release-2024-01-25",
            dimension=384,
        ),
        candidates=candidates,
    )
    return dict(
        natural_statement=candidates[0].draft.matched_prompt + "\nOriginal literal input: α, 2.",
        query_openmath=candidates[0].draft.openmath_xml,
        evidence=tuple(DraftEvidence(c, 0.75, 0.5, i == 0) for i, c in enumerate(candidates)),
        candidates=population,
    )


def test_typed_contract_is_distinct_and_preserves_all_original_evidence(arguments):
    generic = build_draft_reranker_request(**arguments)
    typed = build_typed_draft_reranker_request(**arguments)
    original, subject = json.loads(generic.subject_jcs), json.loads(typed.subject_jcs)
    assert subject["schema_version"] == "pals.typed-draft-proof-support-request.v1"
    assert CONTRACT_VERSION == "pals.typed-draft-proof-support.v1"
    assert hashlib.sha256(PROMPT.encode()).hexdigest() == PROMPT_SHA256
    assert typed.compatibility["reranker_contract_version"] == CONTRACT_VERSION
    assert typed.compatibility["reranker_prompt_sha256"] == PROMPT_SHA256
    assert generic.compatibility["reranker_contract_version"] == "pals.draft-relevance-reranker.v1"
    assert generic.compatibility["reranker_prompt_sha256"] == (
        "ee3210814e58edab5fa2a5878100b310d7811df23e3c5f2d09d93d8f3cc03d00"
    )
    for field in ("natural_statement", "query_openmath", "candidates"):
        assert subject[field] == original[field]
    assert subject["natural_statement"] == arguments["natural_statement"]
    assert subject["query_openmath"] == arguments["query_openmath"]
    assert subject["compatibility"] == typed.compatibility
    typed_body, generic_body = json.loads(typed.body_jcs), json.loads(generic.body_jcs)
    assert typed_body.pop("input") == PROMPT + "\nREQUEST_JCS\n" + typed.subject_jcs.decode()
    generic_body.pop("input")
    assert typed_body == generic_body  # model, deadline transport, schema, token and store policy
    assert typed.subject_jcs == rfc8785.dumps(subject)
    assert build_draft_reranker_request(**arguments) == generic  # no shared-input mutation


class ProviderBoundary:
    """Only isolates the Responses API envelope; no proof or model-quality assertion."""

    def __init__(self, selection, *, status=200):
        self.selection, self.status, self.calls = selection, status, []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        body = json.loads(kwargs["body"])
        envelope = dict(
            object="response",
            status="completed",
            error=None,
            incomplete_details=None,
            model=body["model"],
            usage=dict(
                input_tokens=10,
                input_tokens_details=dict(cached_tokens=0),
                output_tokens=3,
                output_tokens_details=dict(reasoning_tokens=0),
                total_tokens=13,
            ),
            output=[
                dict(
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        dict(type="output_text", annotations=[], text=json.dumps(self.selection))
                    ],
                )
            ],
        )
        return HttpResponse(status_code=self.status, body=json.dumps(envelope).encode())


@pytest.mark.parametrize("count", [0, 1, 2])
def test_same_closed_response_grammar_accepts_empty_or_multiple_supplied_ids(arguments, count):
    request = build_typed_draft_reranker_request(**arguments)
    ids = [c.draft.id for c in arguments["candidates"].candidates][:count]
    transport = ProviderBoundary({"selected_draft_ids": ids})
    assert OpenAIDraftReranker("unit-key", transport).rerank(request) == tuple(ids)
    assert len(transport.calls) == 1
    assert transport.calls[0]["body"] == request.body_jcs
    assert transport.calls[0]["timeout_seconds"] == 90.0


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "extra-field", "wrong-type", "too-many"])
def test_invalid_typed_selection_fails_closed(arguments, kind):
    draft_id = arguments["candidates"].candidates[0].draft.id
    selection = {
        "unknown": {"selected_draft_ids": ["not_supplied"]},
        "duplicate": {"selected_draft_ids": [draft_id, draft_id]},
        "extra-field": {"selected_draft_ids": [], "success": True},
        "wrong-type": {"selected_draft_ids": "none"},
        "too-many": {"selected_draft_ids": [draft_id] * 5},
    }[kind]
    with pytest.raises(DraftRerankerInvalidError):
        OpenAIDraftReranker("unit-key", ProviderBoundary(selection)).rerank(
            build_typed_draft_reranker_request(**arguments)
        )


def test_provider_failure_is_not_empty_no_match(arguments):
    with pytest.raises(DraftRerankerUnavailableError):
        OpenAIDraftReranker("unit-key", ProviderBoundary({}, status=503)).rerank(
            build_typed_draft_reranker_request(**arguments)
        )


def test_invalid_inputs_and_oversized_request_fail_before_transport(arguments):
    with pytest.raises(DraftRerankerInvalidError):
        build_typed_draft_reranker_request(**{**arguments, "natural_statement": "x" * 16385})
    with pytest.raises(DraftRerankerInvalidError):
        build_typed_draft_reranker_request(**{**arguments, "evidence": arguments["evidence"][:1]})
    # A request can fit the generic byte ceiling but exceed it after the larger typed prompt.
    base_generic = build_draft_reranker_request(**arguments)
    base_typed = build_typed_draft_reranker_request(**arguments)
    extra = 262_144 - len(base_typed.body_jcs) + 1
    first = arguments["candidates"].candidates[0]
    longer = replace(
        first, draft=replace(first.draft, proof_strategy=first.draft.proof_strategy + "x" * extra)
    )
    changed_candidates = (longer, *arguments["candidates"].candidates[1:])
    modified = {
        **arguments,
        "candidates": replace(arguments["candidates"], candidates=changed_candidates),
        "evidence": (
            replace(arguments["evidence"][0], candidate=longer),
            *arguments["evidence"][1:],
        ),
    }
    assert len(base_typed.body_jcs) > len(base_generic.body_jcs)
    assert len(build_draft_reranker_request(**modified).body_jcs) <= 262_144
    with pytest.raises(DraftRerankerInvalidError, match="Typed reranker request exceeds"):
        build_typed_draft_reranker_request(**modified)


def test_prompt_binding_drift_is_rejected_before_build(arguments, monkeypatch):
    import pals_agent.typed_reranker as module

    monkeypatch.setattr(module, "PROMPT", module.PROMPT + " drift")
    with pytest.raises(DraftRerankerInvalidError, match="prompt binding changed"):
        module.build_typed_draft_reranker_request(**arguments)
