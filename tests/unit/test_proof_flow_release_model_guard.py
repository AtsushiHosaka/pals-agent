from dataclasses import replace

import pytest

from pals_agent.proof_flow_release_evaluator import (
    ReleaseEvaluationError,
    _require_governed_reranker,
)
from tests.unit.test_proof_flow_reranker import _request


def test_current_luna_request_cannot_emit_historical_mini_release_evidence():
    request = _request()
    assert request.compatibility["reranker_model"] == "gpt-6-luna"
    with pytest.raises(ReleaseEvaluationError, match="runtime_incompatible"):
        _require_governed_reranker(request)


def test_historical_identity_is_preserved_for_existing_evidence():
    request = _request()
    historic = replace(
        request,
        compatibility={
            **request.compatibility,
            "reranker_model": "gpt-5.4-mini-2026-03-17",
        },
    )
    _require_governed_reranker(historic)


@pytest.mark.parametrize("field", ["provider", "provider_api", "contract_version", "prompt_sha256"])
def test_historical_evidence_also_rejects_changed_provider_or_contract(field):
    request = _request()
    changed = replace(
        request,
        compatibility={
            **request.compatibility,
            "reranker_model": "gpt-5.4-mini-2026-03-17",
            f"reranker_{field}": "changed",
        },
    )
    with pytest.raises(ReleaseEvaluationError, match="runtime_incompatible"):
        _require_governed_reranker(changed)
