"""Content-free release evidence for the manual PFI reranker gate.

This module intentionally has no provider, database, logging, corpus, or runtime-result
dependency.  The release operator supplies a governed corpus inventory and a secure external
store adapter; invalid inputs or inactive controls block the write before any record is emitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

import rfc8785

from pals_agent.proof_flow_reranker import DraftRerankerUsage

_SCHEMA_VERSION = "pals.draft-reranker-release-evidence.v1"
_MODEL = "gpt-5.4-mini-2026-03-17"
_MAX_TOKEN_COUNT = 9_223_372_036_854_775_807
_RETENTION_SECONDS = 15_552_000
_DELETION_GRACE_SECONDS = 86_400
_REQUIRED_ROLES = frozenset({"pals_release_operator", "pals_release_auditor"})
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PINNED_PRICING_VALUES = (
    "pals.provider-pricing.v1",
    "openai-gpt-5.4-mini-2026-07-27",
    "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
    "2026-07-27",
    "USD",
    "USD per 1000000 tokens",
    "0.75",
    "0.075",
    "4.50",
)


class ReleaseEvidenceError(RuntimeError):
    """A release-evidence precondition or external-control check failed."""


@dataclass(frozen=True, slots=True)
class ReleasePricingSnapshot:
    """The immutable pricing authority defined by the PFI requirements."""

    schema_version: str = "pals.provider-pricing.v1"
    snapshot_id: str = "openai-gpt-5.4-mini-2026-07-27"
    source_url: str = "https://developers.openai.com/api/docs/models/gpt-5.4-mini"
    effective_date: str = "2026-07-27"
    currency: str = "USD"
    unit: str = "USD per 1000000 tokens"
    uncached_input_rate: str = "0.75"
    cached_input_rate: str = "0.075"
    output_including_reasoning_rate: str = "4.50"

    def __post_init__(self) -> None:
        values = (
            self.schema_version,
            self.snapshot_id,
            self.source_url,
            self.effective_date,
            self.currency,
            self.unit,
            self.uncached_input_rate,
            self.cached_input_rate,
            self.output_including_reasoning_rate,
        )
        if values != _PINNED_PRICING_VALUES:
            raise ReleaseEvidenceError("The release pricing snapshot is not the pinned snapshot.")

    def as_evidence_json(self) -> dict[str, str]:
        return {
            "snapshot_id": self.snapshot_id,
            "effective_date": self.effective_date,
            "currency": self.currency,
            "unit": self.unit,
        }


# Do not fetch or replace this value from a provider dashboard at runtime.
PINNED_RELEASE_PRICING = ReleasePricingSnapshot()


@dataclass(frozen=True, slots=True)
class ReleaseCost:
    microusd_numerator: int
    microusd_denominator: int
    rounded_microusd: int
    rounded_usd: str

    def __post_init__(self) -> None:
        if (
            type(self.microusd_numerator) is not int
            or self.microusd_numerator < 0
            or self.microusd_denominator != 40
            or type(self.rounded_microusd) is not int
            or self.rounded_microusd < 0
            or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.[0-9]{6}", self.rounded_usd)
        ):
            raise ReleaseEvidenceError("Release cost has an invalid shape.")
        if self.rounded_microusd != (self.microusd_numerator + 20) // 40:
            raise ReleaseEvidenceError("Release cost does not use required half-up rounding.")
        expected_usd = (
            f"{self.rounded_microusd // 1_000_000}."
            f"{self.rounded_microusd % 1_000_000:06d}"
        )
        if self.rounded_usd != expected_usd:
            raise ReleaseEvidenceError("Release USD cost does not match the micro-USD amount.")

    def as_json(self) -> dict[str, str | int]:
        return {
            "microusd_numerator": str(self.microusd_numerator),
            "microusd_denominator": self.microusd_denominator,
            "rounded_microusd": str(self.rounded_microusd),
            "rounded_usd": self.rounded_usd,
        }


def calculate_release_cost(usage: DraftRerankerUsage) -> ReleaseCost:
    """Calculate the requirements-defined rational USD cost without floating point."""
    _validate_usage(usage)
    numerator = (
        30 * usage.uncached_input_tokens
        + 3 * usage.cached_input_tokens
        + 180 * usage.output_tokens
    )
    rounded = (numerator + 20) // 40
    return ReleaseCost(
        microusd_numerator=numerator,
        microusd_denominator=40,
        rounded_microusd=rounded,
        rounded_usd=f"{rounded // 1_000_000}.{rounded % 1_000_000:06d}",
    )


@dataclass(frozen=True, slots=True)
class GovernedReleaseCorpus:
    """Immutable identifiers only; never a statement, prompt, proof, or OpenMath payload."""

    query_ids: frozenset[str]
    draft_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.query_ids or not self.draft_ids:
            raise ReleaseEvidenceError("Governed corpus IDs must be non-empty.")
        if not all(_safe_governed_id(value) for value in self.query_ids | self.draft_ids):
            raise ReleaseEvidenceError("Governed corpus contains an invalid ID.")


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceStoreControls:
    """The active, independently inspected controls of the external evidence store."""

    encrypted_in_transit: bool
    encrypted_at_rest: bool
    readable_roles: frozenset[str]
    retention_seconds: int
    deletion_grace_seconds: int
    scheduled_deletion_active: bool
    records_immutable_until_expiry: bool
    dataset_replication_disabled: bool

    def __post_init__(self) -> None:
        if (
            self.encrypted_in_transit is not True
            or self.encrypted_at_rest is not True
            or self.readable_roles != _REQUIRED_ROLES
            or type(self.retention_seconds) is not int
            or self.retention_seconds != _RETENTION_SECONDS
            or type(self.deletion_grace_seconds) is not int
            or self.deletion_grace_seconds != _DELETION_GRACE_SECONDS
            or self.scheduled_deletion_active is not True
            or self.records_immutable_until_expiry is not True
            or self.dataset_replication_disabled is not True
        ):
            raise ReleaseEvidenceError("Release evidence store controls are not exact.")


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceRetention:
    expires_at: str
    deletion_deadline: str


@dataclass(frozen=True, slots=True)
class ReleaseEvidenceWriteReceipt:
    """Content-free acknowledgement of the exact external write controls."""

    controls: ReleaseEvidenceStoreControls
    retention: ReleaseEvidenceRetention


class ExternalReleaseEvidenceStore(Protocol):
    """A production adapter for a secure store outside this repository and the corpus."""

    def inspect_active_controls(self) -> ReleaseEvidenceStoreControls: ...

    def has_overdue_retained_record(self) -> bool: ...

    def has_incomplete_corpus_run(
        self, *, governed_query_ids: frozenset[str]
    ) -> bool: ...

    def inspect_run_query_ids(self, *, observed_at: str) -> tuple[str, ...]: ...

    def write_encrypted_external(
        self,
        *,
        record_jcs: bytes,
        retention: ReleaseEvidenceRetention,
    ) -> ReleaseEvidenceWriteReceipt: ...


@dataclass(frozen=True, slots=True)
class DraftRerankerReleaseEvidence:
    corpus_query_id: str
    observed_at: str
    outcome: Literal["match", "no_match"]
    selected_draft_ids: tuple[str, ...]
    latency_ms: int
    usage: DraftRerankerUsage
    cost: ReleaseCost

    def __post_init__(self) -> None:
        _parse_canonical_utc(self.observed_at)
        if self.outcome not in {"match", "no_match"}:
            raise ReleaseEvidenceError("Release evidence outcome is invalid.")
        if not _safe_governed_id(self.corpus_query_id):
            raise ReleaseEvidenceError("Corpus query ID is invalid.")
        if type(self.latency_ms) is not int or not 0 <= self.latency_ms <= 86_400_000:
            raise ReleaseEvidenceError("Release evidence latency is invalid.")
        if len(self.selected_draft_ids) > 4 or len(self.selected_draft_ids) != len(
            set(self.selected_draft_ids)
        ):
            raise ReleaseEvidenceError("Release evidence selected Draft IDs are invalid.")
        if not all(_safe_governed_id(identifier) for identifier in self.selected_draft_ids):
            raise ReleaseEvidenceError("Release evidence Draft ID is invalid.")
        if (self.outcome == "match") != bool(self.selected_draft_ids):
            raise ReleaseEvidenceError("Release evidence outcome does not match selection.")
        _validate_usage(self.usage)
        if self.cost != calculate_release_cost(self.usage):
            raise ReleaseEvidenceError("Release evidence cost does not match usage.")

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "corpus_query_id": self.corpus_query_id,
            "observed_at": self.observed_at,
            "model": _MODEL,
            "schema_admitted": True,
            "outcome": self.outcome,
            "selected_draft_ids": list(self.selected_draft_ids),
            "latency_ms": self.latency_ms,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "cached_input_tokens": self.usage.cached_input_tokens,
                "uncached_input_tokens": self.usage.uncached_input_tokens,
                "output_tokens": self.usage.output_tokens,
                "reasoning_output_tokens": self.usage.reasoning_output_tokens,
                "nonreasoning_output_tokens": self.usage.nonreasoning_output_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "pricing": PINNED_RELEASE_PRICING.as_evidence_json(),
            "cost": self.cost.as_json(),
        }

    def as_jcs(self) -> bytes:
        return rfc8785.dumps(cast(Any, self.as_json()))


@dataclass(frozen=True, slots=True)
class DraftRerankerReleaseEvidenceWriter:
    """Validate and write exactly one content-free record to an inspected external store."""

    corpus: GovernedReleaseCorpus
    store: ExternalReleaseEvidenceStore

    def preflight(self, *, observed_at: str | None = None) -> ReleaseEvidenceStoreControls:
        """Validate all active external-store controls before a paid provider call."""
        if observed_at is not None:
            _parse_canonical_utc(observed_at)
        controls = self._inspect_controls()
        try:
            if (
                self.store.has_incomplete_corpus_run(
                    governed_query_ids=self.corpus.query_ids
                )
                is not False
            ):
                raise ReleaseEvidenceError(
                    "An incomplete release evidence corpus blocks release."
                )
        except ReleaseEvidenceError:
            raise
        except Exception as exc:
            raise ReleaseEvidenceError("External release evidence store is unavailable.") from exc
        return controls

    def write(
        self,
        *,
        corpus_query_id: str,
        observed_at: str,
        selected_draft_ids: tuple[str, ...],
        latency_ms: int,
        usage: DraftRerankerUsage,
    ) -> DraftRerankerReleaseEvidence:
        if corpus_query_id not in self.corpus.query_ids:
            raise ReleaseEvidenceError("Corpus query ID is not governed.")
        if any(identifier not in self.corpus.draft_ids for identifier in selected_draft_ids):
            raise ReleaseEvidenceError("Selected Draft ID is not governed.")
        evidence = DraftRerankerReleaseEvidence(
            corpus_query_id=corpus_query_id,
            observed_at=observed_at,
            outcome="match" if selected_draft_ids else "no_match",
            selected_draft_ids=selected_draft_ids,
            latency_ms=latency_ms,
            usage=usage,
            cost=calculate_release_cost(usage),
        )
        try:
            controls = self._inspect_controls()
            retention = _retention_for(evidence.observed_at)
            receipt = self.store.write_encrypted_external(
                record_jcs=evidence.as_jcs(),
                retention=retention,
            )
            if (
                not isinstance(receipt, ReleaseEvidenceWriteReceipt)
                or receipt.controls != controls
                or receipt.retention != retention
            ):
                raise ReleaseEvidenceError(
                    "Release evidence store did not acknowledge exact controls."
                )
        except ReleaseEvidenceError:
            raise
        except Exception as exc:
            raise ReleaseEvidenceError("External release evidence store is unavailable.") from exc
        return evidence

    def verify_complete_run(self, *, observed_at: str) -> None:
        """Require one externally retained record for every governed query and no extras."""
        _parse_canonical_utc(observed_at)
        self.preflight()
        try:
            query_ids = self.store.inspect_run_query_ids(observed_at=observed_at)
        except Exception as exc:
            raise ReleaseEvidenceError("External release evidence store is unavailable.") from exc
        if (
            not isinstance(query_ids, tuple)
            or not all(isinstance(value, str) for value in query_ids)
            or len(query_ids) != len(set(query_ids))
            or frozenset(query_ids) != self.corpus.query_ids
        ):
            raise ReleaseEvidenceError("Release evidence corpus set is incomplete.")

    def _inspect_controls(self) -> ReleaseEvidenceStoreControls:
        try:
            controls = self.store.inspect_active_controls()
            if not isinstance(controls, ReleaseEvidenceStoreControls):
                raise ReleaseEvidenceError("Release evidence store controls are unavailable.")
            if self.store.has_overdue_retained_record() is not False:
                raise ReleaseEvidenceError("An overdue retained record blocks release.")
        except ReleaseEvidenceError:
            raise
        except Exception as exc:
            raise ReleaseEvidenceError("External release evidence store is unavailable.") from exc
        return controls


def _validate_usage(usage: DraftRerankerUsage) -> None:
    counts = (
        usage.input_tokens,
        usage.cached_input_tokens,
        usage.uncached_input_tokens,
        usage.output_tokens,
        usage.reasoning_output_tokens,
        usage.nonreasoning_output_tokens,
        usage.total_tokens,
    )
    if any(type(value) is not int or not 0 <= value <= _MAX_TOKEN_COUNT for value in counts):
        raise ReleaseEvidenceError("Release evidence usage is invalid.")
    if (
        usage.uncached_input_tokens != usage.input_tokens - usage.cached_input_tokens
        or usage.nonreasoning_output_tokens != usage.output_tokens - usage.reasoning_output_tokens
        or usage.cached_input_tokens > usage.input_tokens
        or usage.reasoning_output_tokens > usage.output_tokens
        or usage.total_tokens != usage.input_tokens + usage.output_tokens
    ):
        raise ReleaseEvidenceError("Release evidence usage is inconsistent.")


def _retention_for(observed_at: str) -> ReleaseEvidenceRetention:
    observed = _parse_canonical_utc(observed_at)
    expiry = observed + timedelta(seconds=_RETENTION_SECONDS)
    deletion_deadline = expiry + timedelta(seconds=_DELETION_GRACE_SECONDS)
    return ReleaseEvidenceRetention(
        expires_at=_format_canonical_utc(expiry),
        deletion_deadline=_format_canonical_utc(deletion_deadline),
    )


def _parse_canonical_utc(value: str) -> datetime:
    if not isinstance(value, str) or not _UTC_TIMESTAMP.fullmatch(value):
        raise ReleaseEvidenceError("Release evidence observation time is not canonical UTC.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ReleaseEvidenceError("Release evidence observation time is invalid.") from exc
    if _format_canonical_utc(parsed) != value:
        raise ReleaseEvidenceError("Release evidence observation time is not canonical UTC.")
    return parsed


def _format_canonical_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_governed_id(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= 256
    except UnicodeEncodeError:
        return False
