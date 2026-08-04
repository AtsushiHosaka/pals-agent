from __future__ import annotations

import json
from dataclasses import replace
from typing import Literal, cast

import pytest

from pals_agent.proof_flow_release_evidence import (
    DraftRerankerReleaseEvidenceWriter,
    GovernedReleaseCorpus,
    ReleaseEvidenceError,
    ReleaseEvidenceRetention,
    ReleaseEvidenceStoreControls,
    ReleaseEvidenceWriteReceipt,
    calculate_release_cost,
)
from pals_agent.proof_flow_reranker import DraftRerankerUsage


class RecordingExternalStore:
    def __init__(self, *, overdue: bool = False) -> None:
        self.overdue = overdue
        self.records: list[tuple[bytes, ReleaseEvidenceRetention]] = []

    def inspect_active_controls(self) -> ReleaseEvidenceStoreControls:
        return ReleaseEvidenceStoreControls(
            encrypted_in_transit=True,
            encrypted_at_rest=True,
            readable_roles=frozenset({"pals_release_operator", "pals_release_auditor"}),
            retention_seconds=15_552_000,
            deletion_grace_seconds=86_400,
            scheduled_deletion_active=True,
            records_immutable_until_expiry=True,
            dataset_replication_disabled=True,
        )

    def has_overdue_retained_record(self) -> bool:
        return self.overdue

    def has_incomplete_corpus_run(
        self, *, governed_query_ids: frozenset[str]
    ) -> bool:
        by_observation: dict[str, set[str]] = {}
        for record, _ in self.records:
            payload = json.loads(record)
            by_observation.setdefault(payload["observed_at"], set()).add(
                payload["corpus_query_id"]
            )
        return any(
            frozenset(query_ids) != governed_query_ids
            for query_ids in by_observation.values()
        )

    def inspect_run_query_ids(self, *, observed_at: str) -> tuple[str, ...]:
        return tuple(
            json.loads(record)["corpus_query_id"]
            for record, _ in self.records
            if json.loads(record)["observed_at"] == observed_at
        )

    def write_encrypted_external(
        self, *, record_jcs: bytes, retention: ReleaseEvidenceRetention
    ) -> ReleaseEvidenceWriteReceipt:
        self.records.append((record_jcs, retention))
        return ReleaseEvidenceWriteReceipt(
            controls=self.inspect_active_controls(),
            retention=retention,
        )


_USAGE = DraftRerankerUsage(
    input_tokens=10,
    cached_input_tokens=2,
    uncached_input_tokens=8,
    output_tokens=3,
    reasoning_output_tokens=1,
    nonreasoning_output_tokens=2,
    total_tokens=13,
)


def _writer(store: RecordingExternalStore) -> DraftRerankerReleaseEvidenceWriter:
    return DraftRerankerReleaseEvidenceWriter(
        corpus=GovernedReleaseCorpus(
            query_ids=frozenset({"governed-query-1"}),
            draft_ids=frozenset({"draft-a", "draft-b"}),
        ),
        store=store,
    )


def test_pfi_ag_007_writes_exact_content_free_evidence_and_retention() -> None:
    store = RecordingExternalStore()

    evidence = _writer(store).write(
        corpus_query_id="governed-query-1",
        observed_at="2026-07-27T00:00:00Z",
        selected_draft_ids=("draft-a",),
        latency_ms=42,
        usage=_USAGE,
    )

    assert evidence.cost.as_json() == {
        "microusd_numerator": "786",
        "microusd_denominator": 40,
        "rounded_microusd": "20",
        "rounded_usd": "0.000020",
    }
    assert len(store.records) == 1
    body, retention = store.records[0]
    assert json.loads(body) == {
        "schema_version": "pals.draft-reranker-release-evidence.v1",
        "corpus_query_id": "governed-query-1",
        "observed_at": "2026-07-27T00:00:00Z",
        "model": "gpt-5.4-mini-2026-03-17",
        "schema_admitted": True,
        "outcome": "match",
        "selected_draft_ids": ["draft-a"],
        "latency_ms": 42,
        "usage": {
            "input_tokens": 10,
            "cached_input_tokens": 2,
            "uncached_input_tokens": 8,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
            "nonreasoning_output_tokens": 2,
            "total_tokens": 13,
        },
        "pricing": {
            "snapshot_id": "openai-gpt-5.4-mini-2026-07-27",
            "effective_date": "2026-07-27",
            "currency": "USD",
            "unit": "USD per 1000000 tokens",
        },
        "cost": evidence.cost.as_json(),
    }
    assert retention == ReleaseEvidenceRetention(
        expires_at="2027-01-23T00:00:00Z",
        deletion_deadline="2027-01-24T00:00:00Z",
    )
    _writer(store).verify_complete_run(observed_at="2026-07-27T00:00:00Z")


def test_pfi_ag_007_rounds_half_up_and_rejects_non_governed_or_overdue_writes() -> None:
    half = DraftRerankerUsage(
        input_tokens=1,
        cached_input_tokens=0,
        uncached_input_tokens=1,
        output_tokens=0,
        reasoning_output_tokens=0,
        nonreasoning_output_tokens=0,
        total_tokens=1,
    )
    assert calculate_release_cost(half).as_json() == {
        "microusd_numerator": "30",
        "microusd_denominator": 40,
        "rounded_microusd": "1",
        "rounded_usd": "0.000001",
    }
    with pytest.raises(ReleaseEvidenceError):
        _writer(RecordingExternalStore()).write(
            corpus_query_id="unknown",
            observed_at="2026-07-27T00:00:00Z",
            selected_draft_ids=(),
            latency_ms=0,
            usage=_USAGE,
        )
    with pytest.raises(ReleaseEvidenceError):
        _writer(RecordingExternalStore(overdue=True)).write(
            corpus_query_id="governed-query-1",
            observed_at="2026-07-27T00:00:00Z",
            selected_draft_ids=(),
            latency_ms=0,
            usage=_USAGE,
        )


def test_pfi_ag_007_blocks_a_write_without_an_exact_control_receipt() -> None:
    class MismatchedReceiptStore(RecordingExternalStore):
        def write_encrypted_external(
            self, *, record_jcs: bytes, retention: ReleaseEvidenceRetention
        ) -> ReleaseEvidenceWriteReceipt:
            super().write_encrypted_external(record_jcs=record_jcs, retention=retention)
            return ReleaseEvidenceWriteReceipt(
                controls=self.inspect_active_controls(),
                retention=ReleaseEvidenceRetention(
                    expires_at="2026-07-27T00:00:00Z",
                    deletion_deadline="2026-07-28T00:00:00Z",
                ),
            )

    with pytest.raises(ReleaseEvidenceError, match="did not acknowledge"):
        _writer(MismatchedReceiptStore()).write(
            corpus_query_id="governed-query-1",
            observed_at="2026-07-27T00:00:00Z",
            selected_draft_ids=(),
            latency_ms=0,
            usage=_USAGE,
        )


def test_pfi_ag_007_rejects_unregistered_outcomes_and_non_utf8_governed_ids() -> None:
    valid = _writer(RecordingExternalStore()).write(
        corpus_query_id="governed-query-1",
        observed_at="2026-07-27T00:00:00Z",
        selected_draft_ids=(),
        latency_ms=0,
        usage=_USAGE,
    )

    with pytest.raises(ReleaseEvidenceError, match="outcome"):
        replace(valid, outcome=cast(Literal["match", "no_match"], "unknown"))
    with pytest.raises(ReleaseEvidenceError, match="invalid ID"):
        GovernedReleaseCorpus(query_ids=frozenset({"\ud800"}), draft_ids=frozenset({"draft-a"}))


@pytest.mark.parametrize(
    "controls",
    [
        {"encrypted_in_transit": False, "encrypted_at_rest": True},
        {"encrypted_in_transit": True, "encrypted_at_rest": False},
    ],
)
def test_pfi_ag_007_requires_exact_store_encryption_and_roles(
    controls: dict[str, bool],
) -> None:
    with pytest.raises(ReleaseEvidenceError):
        ReleaseEvidenceStoreControls(
            readable_roles=frozenset({"pals_release_operator"}),
            retention_seconds=15_552_000,
            deletion_grace_seconds=86_400,
            scheduled_deletion_active=True,
            records_immutable_until_expiry=True,
            dataset_replication_disabled=True,
            **controls,
        )


@pytest.mark.parametrize(
    ("retention_seconds", "deletion_grace_seconds", "scheduled_deletion_active"),
    [
        (15_551_999, 86_400, True),
        (15_552_000, 86_399, True),
        (15_552_000, 86_400, False),
    ],
)
def test_pfi_ag_007_requires_exact_active_lifecycle_controls(
    retention_seconds: int,
    deletion_grace_seconds: int,
    scheduled_deletion_active: bool,
) -> None:
    with pytest.raises(ReleaseEvidenceError, match="controls"):
        ReleaseEvidenceStoreControls(
            encrypted_in_transit=True,
            encrypted_at_rest=True,
            readable_roles=frozenset(
                {"pals_release_operator", "pals_release_auditor"}
            ),
            retention_seconds=retention_seconds,
            deletion_grace_seconds=deletion_grace_seconds,
            scheduled_deletion_active=scheduled_deletion_active,
            records_immutable_until_expiry=True,
            dataset_replication_disabled=True,
        )


@pytest.mark.parametrize(
    ("records_immutable_until_expiry", "dataset_replication_disabled"),
    [(False, True), (True, False)],
)
def test_pfi_ag_007_requires_immutability_and_no_dataset_replication(
    records_immutable_until_expiry: bool,
    dataset_replication_disabled: bool,
) -> None:
    with pytest.raises(ReleaseEvidenceError, match="controls"):
        ReleaseEvidenceStoreControls(
            encrypted_in_transit=True,
            encrypted_at_rest=True,
            readable_roles=frozenset(
                {"pals_release_operator", "pals_release_auditor"}
            ),
            retention_seconds=15_552_000,
            deletion_grace_seconds=86_400,
            scheduled_deletion_active=True,
            records_immutable_until_expiry=records_immutable_until_expiry,
            dataset_replication_disabled=dataset_replication_disabled,
        )


def test_pfi_ag_007_rejects_partial_or_duplicate_external_run_coverage() -> None:
    class DuplicateCoverageStore(RecordingExternalStore):
        def inspect_run_query_ids(self, *, observed_at: str) -> tuple[str, ...]:
            del observed_at
            return ("governed-query-1", "governed-query-1")

    with pytest.raises(ReleaseEvidenceError, match="incomplete"):
        _writer(DuplicateCoverageStore()).verify_complete_run(
            observed_at="2026-07-27T00:00:00Z"
        )
