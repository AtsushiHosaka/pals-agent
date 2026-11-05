"""Closed claim compatibility only; no generation, provider or production claims."""

from typing import Any

import pytest

from pals_agent.worker import _parse_claim_envelope


def envelope(status: str) -> dict[str, Any]:
    state = {
        "acquired": "generating",
        "busy": "generating",
        "terminal": "failed",
        "not_ready": "queued",
    }[status]
    return {
        "claim_status": status,
        "lease_remaining_ms": 30000 if status in {"acquired", "busy"} else None,
        "resource": {
            "id": "clarification",
            "proof_job_id": "proof",
            "section_id": "selected",
            "selected_text": "coprimality assumption",
            "after_clarification_id": None,
            "question": "Why does coprimality allow cancellation of this factor?",
            "state": state,
            "content": None,
            "diagnostics": [],
            "created_at": "2026-11-05T00:00:00Z",
            "updated_at": "2026-11-05T00:00:00Z",
        },
    }


def parse(value):
    return _parse_claim_envelope(value, resource_kind="clarification", resource_id="clarification")


@pytest.mark.parametrize("status", ["acquired", "busy", "terminal", "not_ready"])
@pytest.mark.parametrize("language", [None, "en", "ja", "zh-Hans", "zh-Hant"])
def test_nullable_supported_language_accepts_current_claim_dto(status, language):
    value = envelope(status)
    value["resource"]["output_language"] = language
    result = parse(value)
    assert result.status == status
    assert result.lease_remaining_ms == value["lease_remaining_ms"]


@pytest.mark.parametrize("status", ["acquired", "busy", "terminal", "not_ready"])
def test_older_claim_without_optional_member_remains_supported(status):
    assert parse(envelope(status)).status == status


@pytest.mark.parametrize("language", ["fr", "zh", "", False, 0, [], {}])
def test_unknown_language_and_nonstring_are_rejected(language):
    value = envelope("acquired")
    value["resource"]["output_language"] = language
    with pytest.raises(ValueError, match="output language"):
        parse(value)


@pytest.mark.parametrize("change", ["unknown_member", "identity", "state", "timestamp"])
def test_optional_member_does_not_relax_closed_resource_validation(change):
    value = envelope("acquired")
    value["resource"]["output_language"] = "ja"
    if change == "unknown_member":
        value["resource"]["compatibility_mode"] = True
    elif change == "identity":
        value["resource"]["id"] = "other"
    elif change == "state":
        value["resource"]["state"] = "completed"
    else:
        value["resource"]["created_at"] = "2026-11-05T00:00:00"
    with pytest.raises(ValueError):
        parse(value)
