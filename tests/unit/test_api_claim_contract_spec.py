from __future__ import annotations

import json
from typing import Any

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.http_transport import HttpResponse, HttpTransportError
from pals_agent.models import Diagnostic

CLAIM_ID = "11111111-1111-4111-8111-111111111111"


class RecordingTransport:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload or {
            "claim_status": "terminal",
            "lease_remaining_ms": None,
            "resource": {"state": "completed"},
        }
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(
            {
                **kwargs,
                "body": (
                    json.loads(kwargs["body"].decode("utf-8"))
                    if kwargs["body"] is not None
                    else None
                ),
            }
        )
        if self.error is not None:
            raise self.error
        return HttpResponse(
            status_code=self.status_code,
            body=json.dumps(self.payload).encode("utf-8"),
        )


class TransportThatMustNotRun:
    def request(self, **kwargs: Any) -> HttpResponse:
        _ = kwargs
        pytest.fail("transport must not run")


@pytest.mark.parametrize("resource", ["explanation", "clarification"])
def test_pex_009_012_generating_request_is_exact_claim_variant(
    resource: str,
) -> None:
    transport = RecordingTransport()
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )

    if resource == "explanation":
        client.upsert_proof_explanation(
            proof_job_id="proof-1",
            state="generating",
            claim_id=CLAIM_ID,
            required_lease_ms=300_000,
        )
    else:
        client.update_proof_clarification(
            clarification_id="clarification-1",
            state="generating",
            claim_id=CLAIM_ID,
            required_lease_ms=300_000,
        )

    assert transport.calls[0]["body"] == {
        "state": "generating",
        "claim_id": CLAIM_ID,
        "required_lease_ms": 300_000,
    }
    assert transport.calls[0]["headers"]["X-PALS-Worker-Secret"] == "PRIVATE-SECRET"


def test_prx_042_proof_generation_claim_uses_exact_api_contract() -> None:
    transport = RecordingTransport(
        payload={
            "claim_status": "acquired",
            "lease_remaining_ms": 3_599_999,
            "resource": {"id": "proof-1"},
        }
    )
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )

    client.acquire_proof_generation_claim(
        proof_job_id="proof-1",
        claim_id=CLAIM_ID,
    )

    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"] == (
        "https://api.test/v1/internal/proof-jobs/proof-1/generation-claims"
    )
    assert transport.calls[0]["body"] == {
        "claim_id": CLAIM_ID,
        "required_lease_ms": 3_600_000,
    }
    assert transport.calls[0]["headers"]["X-PALS-Worker-Secret"] == "PRIVATE-SECRET"


def test_pex_009_completed_and_failed_variants_omit_forbidden_fields(
) -> None:
    transport = RecordingTransport()
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )

    client.upsert_proof_explanation(
        proof_job_id="proof-1",
        state="completed",
        claim_id=CLAIM_ID,
        content={"overview": "証明です。"},
    )
    client.upsert_proof_explanation(
        proof_job_id="proof-1",
        state="failed",
        claim_id=CLAIM_ID,
        diagnostics=[
            Diagnostic(
                severity="error",
                code="pals.explanation_failed",
                message="Explanation generation failed.",
            )
        ],
    )

    assert transport.calls[0]["body"] == {
        "state": "completed",
        "claim_id": CLAIM_ID,
        "content": {"overview": "証明です。"},
    }
    assert transport.calls[1]["body"] == {
        "state": "failed",
        "claim_id": CLAIM_ID,
        "diagnostics": [
                {
                    "severity": "error",
                    "code": "pals.explanation_failed",
                    "message": "Explanation generation failed.",
                    "line": None,
                    "column": None,
                }
        ],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"state": "generating", "claim_id": CLAIM_ID},
        {
            "state": "completed",
            "claim_id": CLAIM_ID,
            "content": None,
        },
        {
            "state": "failed",
            "claim_id": CLAIM_ID,
            "required_lease_ms": 300_000,
        },
        {
            "state": "generating",
            "claim_id": "not-a-uuid",
            "required_lease_ms": 300_000,
        },
    ],
)
def test_pex_009_client_rejects_invalid_claim_variant_before_transport(
    kwargs: dict[str, Any],
) -> None:
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=TransportThatMustNotRun(),
    )

    with pytest.raises(ValueError):
        client.upsert_proof_explanation(proof_job_id="proof-1", **kwargs)


def test_pae_015_http_error_body_is_parsed_for_code_then_discarded(
) -> None:
    secret = "PRIVATE-HTTP-BODY-CLAIM-SECRET"
    body = json.dumps(
        {
            "error": {
                "code": "proof_explanation_claim_expired",
                "message": secret,
            }
        }
    ).encode("utf-8")

    transport = RecordingTransport(
        status_code=409,
        payload=json.loads(body),
    )
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )

    with pytest.raises(PalsApiError) as error_info:
        client.upsert_proof_explanation(
            proof_job_id="proof-1",
            state="generating",
            claim_id=CLAIM_ID,
            required_lease_ms=300_000,
        )

    assert error_info.value.error_code == "proof_explanation_claim_expired"
    assert secret not in str(error_info.value)
    assert error_info.value.__cause__ is None


def test_pae_015_transport_detail_is_not_retained_in_api_error(
) -> None:
    secret = "PRIVATE-TRANSPORT-DETAIL"
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=RecordingTransport(error=HttpTransportError(secret)),
    )

    with pytest.raises(PalsApiError) as error_info:
        client.get_proof_job("proof-1")

    assert str(error_info.value) == "PALS API request failed"
    assert error_info.value.__cause__ is None


@pytest.mark.parametrize(
    ("method_name", "identifier"),
    [
        ("get_proof_job", "../proof"),
        ("get_proof_job", "proof/child"),
        ("get_proof_clarification", r"proof\\child"),
        ("get_proof_clarification", ".hidden"),
        ("get_proof_clarification", "proof?query"),
        ("get_proof_clarification", "proof#fragment"),
        ("get_proof_clarification", "%2Falready-escaped"),
    ],
)
def test_pae_015_dynamic_path_ids_are_rejected_before_transport(
    method_name: str,
    identifier: str,
) -> None:
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=TransportThatMustNotRun(),
    )

    with pytest.raises(ValueError, match="path segment"):
        getattr(client, method_name)(identifier)


@pytest.mark.parametrize("method_name", ["get_proof_job", "get_proof_clarification"])
def test_pae_015_dynamic_path_ids_reject_201_ascii_characters_before_transport(
    method_name: str,
) -> None:
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=TransportThatMustNotRun(),
    )

    with pytest.raises(ValueError, match="path segment"):
        getattr(client, method_name)("a" * 201)


@pytest.mark.parametrize("method_name", ["get_proof_job", "get_proof_clarification"])
def test_pae_015_dynamic_path_ids_accept_exactly_200_ascii_characters(
    method_name: str,
) -> None:
    transport = RecordingTransport()
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )

    getattr(client, method_name)("a" * 200)

    assert "a" * 200 in transport.calls[0]["url"]


@pytest.mark.parametrize(
    ("method_name", "expected_path"),
    [
        (
            "get_proof_job",
            "/v1/internal/proof-jobs/proof%3Aone/worker-input",
        ),
        (
            "get_proof_clarification",
            "/v1/internal/proof-clarifications/clarification%3Aone/worker-input",
        ),
    ],
)
def test_pae_015_accepted_ids_are_encoded_as_one_path_segment(
    method_name: str,
    expected_path: str,
) -> None:
    transport = RecordingTransport()
    client = PalsApiClient(
        base_url="https://api.test",
        worker_secret="PRIVATE-SECRET",
        transport=transport,
    )

    getattr(client, method_name)(
        "proof:one" if method_name == "get_proof_job" else "clarification:one"
    )

    assert transport.calls[0]["url"] == "https://api.test" + expected_path
