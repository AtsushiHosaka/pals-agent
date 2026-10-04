from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
import rfc8785

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.http_transport import HttpResponse
from pals_agent.recipe_semantic_reviewer import RecipeSemanticReviewApiClient

LEAN_CODE = "import Mathlib\n\nexample : True := by\n  trivial\n"
CLAIM_ID = "11111111-1111-4111-8111-111111111111"
CANDIDATE_ID = "22222222-2222-4222-8222-222222222222"
LEAN_SHA256 = hashlib.sha256(LEAN_CODE.encode("utf-8")).hexdigest()
ARTIFACT_URI = "s3://pals-artifacts/proof-jobs/job-1/result.lean"


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(
            {
                **kwargs,
                "body": json.loads(kwargs["body"].decode("utf-8")),
            }
        )
        return HttpResponse(status_code=200, body=b"{}")


def _client(transport: RecordingTransport) -> PalsApiClient:
    return PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )


def test_pae_020_worker_cannot_send_a_verified_update() -> None:
    transport = RecordingTransport()

    with pytest.raises(ValueError, match="verification candidate"):
        _client(transport).update_proof_job(
            proof_job_id="job-1",
            claim_id=CLAIM_ID,
            state="verified",
            diagnostics=[],
            result_artifact_uri=ARTIFACT_URI,
            lean_code=LEAN_CODE,
            context={"attempts": 1},
        )

    assert transport.calls == []


def test_pjr_021_candidate_submission_has_only_the_closed_import_dto() -> None:
    transport = RecordingTransport()

    _client(transport).submit_verification_candidate(
        proof_job_id="job-1",
        claim_id=CLAIM_ID,
        candidate_id=CANDIDATE_ID,
        lean_code=LEAN_CODE,
        result_artifact_uri=ARTIFACT_URI,
    )

    assert transport.calls[0]["url"] == (
        "https://api.test/v1/internal/proof-jobs/job-1/verification-candidates"
    )
    assert transport.calls[0]["body"] == {
        "schema_version": "pals.proof-verification-candidate.v1",
        "candidate_id": CANDIDATE_ID,
        "claim_id": CLAIM_ID,
        "lean_code": LEAN_CODE,
        "lean_sha256": LEAN_SHA256,
        "result_artifact_uri": ARTIFACT_URI,
    }
    assert "verifier_attestation" not in transport.calls[0]["body"]


def test_candidate_submission_accepts_the_durable_model_lean_artifact() -> None:
    transport = RecordingTransport()
    artifact_uri = "s3://pals-artifacts/proof-jobs/job-1.repair-2/result.lean"

    _client(transport).submit_verification_candidate(
        proof_job_id="job-1",
        claim_id=CLAIM_ID,
        candidate_id=CANDIDATE_ID,
        lean_code=LEAN_CODE,
        result_artifact_uri=artifact_uri,
    )

    assert transport.calls[0]["body"]["result_artifact_uri"] == artifact_uri


def test_candidate_submission_rejects_a_manual_fixture_even_when_its_digest_matches() -> None:
    transport = RecordingTransport()
    fixture_uri = f"s3://manual-fixtures/manual-fixtures/{LEAN_SHA256}.lean"

    with pytest.raises(ValueError, match="canonical Lean artifact URI"):
        _client(transport).submit_verification_candidate(
            proof_job_id="job-1",
            claim_id=CLAIM_ID,
            candidate_id=CANDIDATE_ID,
            lean_code=LEAN_CODE,
            result_artifact_uri=fixture_uri,
        )

    assert transport.calls == []


def _recipe_candidate_source() -> dict[str, Any]:
    return {
        "schema_version": "pals.candidate-source.v2",
        "candidate_source": "recipe",
        "recipe_id": "recipe.square-v1",
        "recipe_revision": 1,
        "alignment_id": None,
        "alignment_revision": None,
        "selection_payload_sha256": "a" * 64,
        "selection_receipt_sha256": "b" * 64,
        "materialized_source_sha256": LEAN_SHA256,
        "target_sha256": hashlib.sha256(b"True").hexdigest(),
        "toolchain_fingerprint_sha256": "c" * 64,
        "compiler_receipt_sha256": "d" * 64,
        "source_author_principal": "pals.principal.v1/recipe-author/local",
    }


def test_recipe_candidate_submission_has_only_closed_v2_recipe_evidence() -> None:
    transport = RecordingTransport()
    artifact_uri = (
        f"s3://pals-artifacts/proof-jobs/job-1/candidates/{CANDIDATE_ID}/{LEAN_SHA256}.lean"
    )
    candidate_source = _recipe_candidate_source()

    _client(transport).submit_recipe_verification_candidate(
        proof_job_id="job-1",
        mutation_claim_id=CLAIM_ID,
        candidate_id=CANDIDATE_ID,
        lean_code=LEAN_CODE,
        result_artifact_uri=artifact_uri,
        candidate_source=candidate_source,
    )

    assert transport.calls[0]["url"] == (
        "https://api.test/v1/internal/proof-jobs/job-1/recipe-verification-candidates"
    )
    assert transport.calls[0]["body"] == {
        "schema_version": "pals.proof-verification-candidate.v2",
        "candidate_id": CANDIDATE_ID,
        "mutation_claim_id": CLAIM_ID,
        "lean_code": LEAN_CODE,
        "lean_sha256": LEAN_SHA256,
        "result_artifact_uri": artifact_uri,
        "candidate_source": candidate_source,
    }
    assert not {"provider", "model", "raw_model_output", "repair_route"} & set(
        transport.calls[0]["body"]["candidate_source"]
    )


def _semantic_review_evidence() -> dict[str, Any]:
    target_declaration: dict[str, Any] = {
        "kind": "example",
        "name": None,
        "proposition": "True",
    }
    review_input: dict[str, Any] = {
        "theorem_statement": "Show that True.",
        "formal_statement": None,
        "target_declaration": target_declaration,
        "lean_sha256": LEAN_SHA256,
    }
    evidence: dict[str, Any] = {
        "schema_version": "pals.proof-semantic-review.v2",
        "candidate_id": CANDIDATE_ID,
        "generator_session_id": CLAIM_ID,
        "lean_sha256": LEAN_SHA256,
        "target_declaration": target_declaration,
        "review_input_sha256": hashlib.sha256(rfc8785.dumps(review_input)).hexdigest(),
        "reviewer": {
            "provider": "openai",
            "model": "gpt-5.4-mini-2026-03-17",
            "session_id": "33333333-3333-4333-8333-333333333333",
        },
        "decision": "approved",
        "rationale": "The extracted target and compiled Lean source establish the request.",
    }
    return {
        **evidence,
        "evidence_sha256": hashlib.sha256(rfc8785.dumps(evidence)).hexdigest(),
    }


def test_semantic_review_settlement_sends_the_closed_evidence_dto() -> None:
    transport = RecordingTransport()
    evidence = _semantic_review_evidence()

    _client(transport).settle_proof_semantic_review(
        proof_job_id="job-1",
        evidence=evidence,
    )

    assert transport.calls[0]["url"] == (
        "https://api.test/v1/internal/proof-jobs/job-1/semantic-reviews"
    )
    assert transport.calls[0]["body"] == evidence


def test_recipe_semantic_review_omits_model_and_source_author_provenance() -> None:
    transport = RecordingTransport()
    evidence = {
        "schema_version": "pals.proof-semantic-review.v3",
        "candidate_id": CANDIDATE_ID,
        "source_binding_sha256": "b" * 64,
        "lean_sha256": LEAN_SHA256,
        "target_declaration": {"kind": "example", "name": None, "proposition": "True"},
        "review_input_sha256": "e" * 64,
        "decision": "approved",
        "rationale": "The exact Recipe source proves the stated target.",
    }

    with pytest.raises(PalsApiError, match="dedicated reviewer"):
        _client(transport).settle_recipe_semantic_review(proof_job_id="job-1", evidence=evidence)
    assert transport.calls == []

    RecipeSemanticReviewApiClient(
        base_url="https://api.test",
        reviewer_secret="REVIEWER-ONLY-SECRET",
        transport=transport,
    ).settle("job-1", evidence)

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://api.test/v1/internal/proof-jobs/job-1/semantic-reviews"
    assert call["method"] == "POST"
    assert call["body"] == evidence
    assert call["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-PALS-Recipe-Semantic-Reviewer-Secret": "REVIEWER-ONLY-SECRET",
    }
    assert not {
        "generator_session_id",
        "reviewer",
        "reviewer_principal",
        "source_author_principal",
        "model",
        "provider",
    } & set(call["body"])
    assert call["body"]["source_binding_sha256"] == "b" * 64


@pytest.mark.parametrize(
    "mutate",
    [
        lambda evidence: evidence.pop("evidence_sha256"),
        lambda evidence: evidence.__setitem__("decision", "failed"),
        lambda evidence: evidence["reviewer"].pop("session_id"),
        lambda evidence: evidence.__setitem__("candidate_id", "not-a-uuid"),
        lambda evidence: evidence["target_declaration"].__setitem__("kind", "def"),
    ],
)
def test_semantic_review_settlement_rejects_noncanonical_evidence_before_transport(
    mutate: Any,
) -> None:
    transport = RecordingTransport()
    evidence = _semantic_review_evidence()
    mutate(evidence)

    with pytest.raises(ValueError, match="semantic review"):
        _client(transport).settle_proof_semantic_review(
            proof_job_id="job-1",
            evidence=evidence,
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    ("candidate_id", "lean_code", "artifact_uri"),
    [
        ("not-a-uuid", LEAN_CODE, ARTIFACT_URI),
        (CANDIDATE_ID, " \n", ARTIFACT_URI),
        (CANDIDATE_ID, LEAN_CODE, "s3://bucket/proof-jobs/job-1/result.json"),
        (CANDIDATE_ID, LEAN_CODE, "s3://manual-fixtures/manual-fixtures/" + ("0" * 64) + ".lean"),
    ],
)
def test_pjr_021_candidate_submission_rejects_unbound_input_before_transport(
    candidate_id: str,
    lean_code: str,
    artifact_uri: str,
) -> None:
    transport = RecordingTransport()

    with pytest.raises(ValueError, match="claim_id|candidate|fixture|URI|Lean"):
        _client(transport).submit_verification_candidate(
            proof_job_id="job-1",
            claim_id=CLAIM_ID,
            candidate_id=candidate_id,
            lean_code=lean_code,
            result_artifact_uri=artifact_uri,
        )

    assert transport.calls == []


@pytest.mark.parametrize("status", ["linked", "already_linked"])
def test_no_recipe_trace_forwards_only_authenticated_digest_and_live_claim(status: str) -> None:
    class TraceTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> HttpResponse:
            super().request(**kwargs)
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "schema_version": "pals.recipe-attempt-trace-response.v1",
                        "status": status,
                    }
                ).encode(),
            )

    transport = TraceTransport()
    result = _client(transport).record_no_recipe_attempt(
        proof_job_id="job-1",
        mutation_claim_id=CLAIM_ID,
        request_sha256="a" * 64,
    )
    assert result["status"] == status
    assert transport.calls[0]["body"] == {
        "schema_version": "pals.recipe-attempt-trace-request.v1",
        "mutation_claim_id": CLAIM_ID,
        "request_sha256": "a" * 64,
    }
    assert transport.calls[0]["url"].endswith("/proof-jobs/job-1/recipe-selection-traces")


def test_no_recipe_trace_rejects_unacknowledged_response() -> None:
    with pytest.raises(ValueError):
        _client(RecordingTransport()).record_no_recipe_attempt(
            proof_job_id="job-1",
            mutation_claim_id=CLAIM_ID,
            request_sha256="a" * 64,
        )


def test_candidate_binding_get_is_private_and_sends_no_mutation_body() -> None:
    class ReadTransport:
        calls: list[dict[str, Any]] = []

        def request(self, **kwargs: Any) -> HttpResponse:
            self.calls.append(kwargs)
            return HttpResponse(status_code=200, body=b"{}")

    transport = ReadTransport()
    client = PalsApiClient(base_url="https://api.test", worker_secret="test-secret",
                           transport=transport)
    assert client.get_verification_candidate_binding(
        proof_job_id="job-1", candidate_id=CANDIDATE_ID,
    ) == {}
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(f"/job-1/verification-candidates/{CANDIDATE_ID}/binding")
    assert call["headers"]["X-PALS-Worker-Secret"] == "test-secret"
    assert call["body"] is None
    with pytest.raises(ValueError):
        client.get_verification_candidate_binding(proof_job_id="job-1", candidate_id="bad")
    assert len(transport.calls) == 1
