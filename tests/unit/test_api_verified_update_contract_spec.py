from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from pals_agent.api_client import PalsApiClient
from pals_agent.http_transport import HttpResponse

LEAN_CODE = "import Mathlib\n\nexample : True := by\n  trivial\n"
CLAIM_ID = "11111111-1111-4111-8111-111111111111"
CANDIDATE_ID = "22222222-2222-4222-8222-222222222222"
LEAN_SHA256 = hashlib.sha256(LEAN_CODE.encode("utf-8")).hexdigest()
ARTIFACT_URI = f"s3://manual-fixtures/manual-fixtures/{LEAN_SHA256}.lean"


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
