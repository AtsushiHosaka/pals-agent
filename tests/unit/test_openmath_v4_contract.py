from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from pals_agent.http_transport import HttpResponse
from pals_agent.openmath_v4_contract import (
    OpenMathV4ContractError,
    require_openmath_c14n_v4_contract,
    validate_openmath_c14n_v4_contract,
)
from pals_agent.private_draft_candidates import (
    DraftCandidateCompatibilityError,
    DraftEmbeddingFingerprint,
    PrivateDraftCandidateClient,
)

ROOT = Path(__file__).resolve().parents[3]


def _artifact_bytes() -> bytes:
    return (
        resources.files("pals_agent.contracts")
        .joinpath("openmath-cdbase-alpha-c14n-v4-vectors.json")
        .read_bytes()
    )


def _openmath_source_bytes() -> bytes:
    return resources.files("pals_agent").joinpath("openmath.py").read_bytes()


def _modified_artifact(mutate: Any) -> bytes:
    artifact = json.loads(_artifact_bytes())
    mutate(artifact)
    return json.dumps(artifact, separators=(",", ":")).encode("utf-8")


def test_lrc_t004_packaged_v4_contract_matches_the_shared_artifact_and_reference_source() -> None:
    shared_artifact = (
        ROOT / "specs" / "lean-recipe-catalog" / "openmath-cdbase-alpha-c14n-v4-vectors.json"
    ).read_bytes()

    assert _artifact_bytes() == shared_artifact
    require_openmath_c14n_v4_contract()


def test_lrc_t004_rejects_a_reference_source_that_does_not_match_the_artifact_digest() -> None:
    with pytest.raises(OpenMathV4ContractError, match="reference source digest"):
        validate_openmath_c14n_v4_contract(
            artifact_bytes=_artifact_bytes(),
            openmath_source_bytes=_openmath_source_bytes() + b"\n",
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        pytest.param(
            lambda artifact: artifact["vectors"][0].__setitem__(
                "canonical_openmath_xml", "<OMOBJ/>"
            ),
            "canonical XML",
            id="canonical-output",
        ),
        pytest.param(
            lambda artifact: artifact["vectors"][0].__setitem__("payload_jcs", "{}"),
            "payload JCS",
            id="payload-jcs",
        ),
        pytest.param(
            lambda artifact: artifact["vectors"][0].__setitem__("payload_sha256", "0" * 64),
            "payload digest",
            id="payload-digest",
        ),
    ],
)
def test_lrc_t004_rejects_tampered_v4_output_or_payload_vectors(mutate: Any, message: str) -> None:
    with pytest.raises(OpenMathV4ContractError, match=message):
        validate_openmath_c14n_v4_contract(
            artifact_bytes=_modified_artifact(mutate),
            openmath_source_bytes=_openmath_source_bytes(),
        )


def test_lrc_t004_rejects_a_reject_vector_that_the_reference_canonicalizer_accepts() -> None:
    def _make_reject_vector_accepted(artifact: dict[str, Any]) -> None:
        artifact["vectors"][-1]["input_openmath_xml"] = artifact["vectors"][0]["input_openmath_xml"]

    with pytest.raises(OpenMathV4ContractError, match="reject vector was accepted"):
        validate_openmath_c14n_v4_contract(
            artifact_bytes=_modified_artifact(_make_reject_vector_accepted),
            openmath_source_bytes=_openmath_source_bytes(),
        )


def test_lrc_t004_private_candidate_boundary_fails_closed_when_the_v4_contract_cannot_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Transport:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, **_: object) -> HttpResponse:
            self.calls += 1
            return HttpResponse(
                status_code=200,
                body=b'{"schema_version":"pals.draft-candidate-result.v1"}',
                headers=(("Content-Type", "application/json"),),
            )

    def _reject_contract() -> None:
        raise OpenMathV4ContractError("tampered contract")

    monkeypatch.setattr(
        "pals_agent.private_draft_candidates.require_openmath_c14n_v4_contract",
        _reject_contract,
    )
    transport = _Transport()
    client = PrivateDraftCandidateClient(
        base_url="https://api.pals.example",
        worker_secret="worker-secret",
        transport=transport,
    )
    fingerprint = DraftEmbeddingFingerprint(
        provider="openai",
        model="text-embedding-3-small",
        endpoint="https://api.openai.com/v1",
        deployment="text-embedding-3-small",
        revision="2026-07-27",
        dimension=2,
    )
    with pytest.raises(DraftCandidateCompatibilityError):
        client.find_candidates(embedding=[1.0, 0.0], fingerprint=fingerprint)

    assert transport.calls == 1
