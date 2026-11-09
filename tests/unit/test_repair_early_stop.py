"""The repeated-statement-mismatch early stop: dedicated reason, events, API projection."""

import json
from pathlib import Path
from typing import Any

import pytest

from pals_agent import quality_events as qe
from pals_agent.artifacts import FileArtifactStore
from pals_agent.evaluation import _TERMINATION_REASONS, _TERMINATION_SOURCES
from pals_agent.models import (
    Diagnostic,
    GeneratedProof,
    RepairRouteAttemptEvidence,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import (
    EARLY_STOP_DIAGNOSTIC_CODE,
    EARLY_STOP_REASON,
    ProofPipeline,
    _repeated_mismatch_codes,
)
from pals_agent.worker import _proof_status_context

STATEMENT = "theorem pals_card_target (n : ℕ) : n + 0 = n"
HARNESS = "lean.formal_harness_mismatch"
MISMATCH = "lean.statement_mismatch"
JOB_ID = "6f1c2a64-7a44-4b6e-8c52-1f0a5d3c9e10"


class _Scripted:
    """One attempt per scripted kind: harness (statement missing), statement or other."""

    model = "fake"

    def __init__(self, kinds: list[str]) -> None:
        self.kinds = kinds
        self.calls = 0

    def generate(self, request):  # type: ignore[no-untyped-def]
        return self._next()

    def repair(self, request, feedback):  # type: ignore[no-untyped-def]
        return self._next()

    def select_repair_route(self, request, feedback):  # type: ignore[no-untyped-def]
        return RepairRouteDecision(
            route="prove",
            rationale="r",
            raw_model_output="{}",
            selector_attempts=(
                RepairRouteAttemptEvidence(
                    attempt=1, outcome="selected", diagnostic_code=None, route="prove"
                ),
            ),
        )

    def _next(self) -> GeneratedProof:
        kind = self.kinds[min(self.calls, len(self.kinds) - 1)]
        self.calls += 1
        statement = "" if kind == "harness" else f"{STATEMENT} := by\n  sorry\n"
        code = f"import Mathlib\n-- kind:{kind}\n{statement or 'example : True := trivial'}\n"
        return GeneratedProof(
            lean_code=code, model=self.model, raw_model_output=code, provider="fake"
        )


class _KindVerifier:
    def verify(self, lean_code: str) -> VerificationResult:
        if "kind:success" in lean_code:
            return VerificationResult(
                success=True, diagnostics=[], stdout="", stderr="", elapsed_ms=1
            )
        code = MISMATCH if "kind:statement" in lean_code else "lean.error"
        return VerificationResult(
            success=False,
            diagnostics=[Diagnostic(severity="error", code=code, message="x")],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )


def _run(
    tmp_path: Path, kinds: list[str], *, max_repairs: int = 6, **options: Any
) -> tuple[_Scripted, dict[str, Any], list[tuple[Any, ...]]]:
    generator = _Scripted(kinds)
    statuses: list[tuple[Any, ...]] = []
    pipeline = ProofPipeline(
        generator=generator,  # type: ignore[arg-type]
        verifier=_KindVerifier(),  # type: ignore[arg-type]
        artifact_store=FileArtifactStore(tmp_path),
        max_repair_attempts=max_repairs,
        **options,
    )
    pipeline.run_statement(
        statement="n plus zero",
        formal_statement=STATEMENT,
        proof_job_id=JOB_ID,
        on_status=lambda *args: statuses.append(args),
    )
    return generator, json.loads((tmp_path / JOB_ID / "result.json").read_text()), statuses


# ------------------------------------------------------------------ dedicated reason


def test_a_stop_has_its_own_reason_diagnostic_event_and_counts(tmp_path: Path) -> None:
    generator, metadata, _ = _run(
        tmp_path, ["statement"], stop_on_repeated_statement_mismatch=True
    )
    assert generator.calls == 2
    assert metadata["termination_reason"] == EARLY_STOP_REASON
    assert metadata["termination_event"] == {
        "reason": EARLY_STOP_REASON,
        "attempt": 2,
        "source": "repair_early_stop",
    }
    assert metadata["early_stop"] == {
        "rule": "repeated_statement_mismatch",
        "window": 2,
        "stopped_after_attempt": 2,
        "repairs_used": 1,
        "repairs_remaining": 5,
    }
    (stop,) = [d for d in metadata["diagnostics"] if d["code"] == EARLY_STOP_DIAGNOSTIC_CODE]
    assert MISMATCH in stop["message"]
    assert not [d for d in metadata["diagnostics"] if d["code"] == "pals.repair_budget_exhausted"]


def test_the_harness_flag_alone_uses_the_same_dedicated_reason(tmp_path: Path) -> None:
    _, metadata, _ = _run(tmp_path, ["harness"], stop_on_repeated_harness_mismatch=True)
    assert metadata["termination_reason"] == EARLY_STOP_REASON


def test_a_used_up_budget_stays_repair_budget_exhausted(tmp_path: Path) -> None:
    # Two mismatches in a row exactly when the last repair is spent: nothing was saved.
    generator, metadata, _ = _run(
        tmp_path, ["statement"], max_repairs=1, stop_on_repeated_statement_mismatch=True
    )
    assert generator.calls == 2
    assert metadata["termination_reason"] == "repair_budget_exhausted"
    assert "early_stop" not in metadata


def test_the_evaluation_contract_accepts_the_reason_with_budget_left() -> None:
    assert EARLY_STOP_REASON in _TERMINATION_REASONS
    assert _TERMINATION_SOURCES[EARLY_STOP_REASON] == "repair_early_stop"


# ------------------------------------------------------------------ window


def test_the_window_decides_how_many_failures_in_a_row_stop_the_run(tmp_path: Path) -> None:
    generator, metadata, _ = _run(
        tmp_path,
        ["statement"],
        stop_on_repeated_statement_mismatch=True,
        repeated_mismatch_window=3,
    )
    assert generator.calls == 3
    assert metadata["early_stop"]["window"] == 3
    assert metadata["early_stop"]["repairs_used"] == 2


def test_a_window_of_three_does_not_stop_a_pair_followed_by_a_success(tmp_path: Path) -> None:
    generator, metadata, _ = _run(
        tmp_path,
        ["statement", "statement", "success"],
        stop_on_repeated_statement_mismatch=True,
        repeated_mismatch_window=3,
    )
    assert generator.calls == 3
    assert metadata["termination_reason"] == "verified"


def test_the_window_is_limited_to_what_the_api_can_hand_back(tmp_path: Path) -> None:
    for window in (1, 4):
        with pytest.raises(ValueError, match="window"):
            ProofPipeline(
                generator=_Scripted(["statement"]),  # type: ignore[arg-type]
                verifier=_KindVerifier(),  # type: ignore[arg-type]
                artifact_store=FileArtifactStore(tmp_path),
                repeated_mismatch_window=window,
            )


def test_the_rule_reports_the_codes_it_matched() -> None:
    history = [frozenset({f"{HARNESS}|a"}), frozenset({f"{MISMATCH}|b"})]
    both = frozenset({HARNESS, MISMATCH})
    assert _repeated_mismatch_codes(history, both) == both
    assert _repeated_mismatch_codes(history, frozenset({HARNESS})) is None
    assert _repeated_mismatch_codes(history[:1], both) is None
    assert _repeated_mismatch_codes([*history, frozenset({"lean.error|x"})], both, 2) is None
    assert _repeated_mismatch_codes([frozenset(), history[0]], both) is None


# ------------------------------------------------------------------ observe mode


def test_observe_mode_never_stops_but_reports_the_would_be_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []

    class _Sink:
        def send(self, line: str) -> None:
            lines.append(line)

    monkeypatch.setenv("PALS_QUALITY_EVENTS_ENABLED", "true")
    monkeypatch.setenv("PALS_QUALITY_EVENTS_ENVIRONMENT", "local")
    with qe.use_transport(_Sink()):
        generator, metadata, _ = _run(
            tmp_path,
            ["statement", "statement", "success"],
            observe_repeated_statement_mismatch=True,
        )
    assert generator.calls == 3
    assert metadata["termination_reason"] == "verified"
    (event,) = [json.loads(line) for line in lines]
    assert event["stop_mode"] == "observed"
    assert event["RepairEarlyStopsObserved"] == 1
    assert "RepairEarlyStops" not in event


def test_a_stop_is_emitted_as_a_closed_event_without_any_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []

    class _Sink:
        def send(self, line: str) -> None:
            lines.append(line)

    monkeypatch.setenv("PALS_QUALITY_EVENTS_ENABLED", "true")
    monkeypatch.setenv("PALS_QUALITY_EVENTS_ENVIRONMENT", "local")
    with qe.use_transport(_Sink()):
        _run(tmp_path, ["harness", "statement"], stop_on_repeated_statement_mismatch=True)
    (event,) = [json.loads(line) for line in lines]
    assert event["event"] == "repair_early_stop"
    assert event["stop_mode"] == "stopped"
    assert event["stop_codes"] == f"{HARNESS},{MISMATCH}"
    assert (event["attempts"], event["repairs_used"], event["repairs_remaining"]) == (2, 1, 5)
    assert event["RepairEarlyStops"] == 1
    assert len(event["request_hash"]) == 64
    assert STATEMENT not in json.dumps(event)
    assert set(event) - {"_aws"} <= (
        qe.ALLOWED_LOG_FIELDS | qe.ALLOWED_DIMENSIONS | qe.ALLOWED_METRICS
    )


def test_events_are_silent_while_quality_events_are_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []

    class _Sink:
        def send(self, line: str) -> None:
            lines.append(line)

    monkeypatch.delenv("PALS_QUALITY_EVENTS_ENABLED", raising=False)
    with qe.use_transport(_Sink()):
        _run(tmp_path, ["statement"], stop_on_repeated_statement_mismatch=True)
    assert lines == []


_EVENT_ARGUMENTS: dict[str, Any] = {
    "environment": "local",
    "mode": "stopped",
    "codes": [MISMATCH],
    "window": 2,
    "attempts": 2,
    "repairs_used": 1,
    "repairs_remaining": 5,
    "request_id": JOB_ID,
}


def test_the_event_sorts_and_deduplicates_its_codes() -> None:
    event = qe.build_repair_early_stop(
        **{**_EVENT_ARGUMENTS, "codes": [MISMATCH, HARNESS, MISMATCH]}
    )
    assert event.emf["stop_codes"] == f"{HARNESS},{MISMATCH}"


@pytest.mark.parametrize(
    "overrides",
    [{"codes": ["lean.error"]}, {"codes": ["a b"]}, {"mode": "maybe"}, {"window": -1}],
)
def test_the_event_rejects_anything_outside_its_closed_vocabulary(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(qe.QualityEventRejected):
        qe.build_repair_early_stop(**{**_EVENT_ARGUMENTS, **overrides})


# ------------------------------------------------------------------ API projection


def _api_terminal_is_valid(context: dict[str, Any]) -> None:
    """The relations pals-api enforces on a failed ``repair_budget_exhausted`` status context."""
    attempt = context["attempt_evidence"]["attempt"]
    event = context["termination_event"]
    assert context["stage"] == "failed"
    assert context["termination_reason"] == event["reason"] == "repair_budget_exhausted"
    assert event["source"] == "repair_budget"
    assert event["attempt"] == attempt
    assert context["repairs_used"] == attempt - 1
    assert attempt <= context["max_repair_attempts"] + 1
    assert attempt == context["max_repair_attempts"] + 1  # required for repair_budget_exhausted
    assert 1 <= context["max_repair_attempts"] <= 64


def test_the_api_receives_a_valid_budget_terminal_not_the_unknown_reason(
    tmp_path: Path,
) -> None:
    _, _, statuses = _run(tmp_path, ["statement"], stop_on_repeated_statement_mismatch=True)
    state, diagnostics, _, _, raw = statuses[-1]
    assert state == "failed"
    assert raw["termination_reason"] == EARLY_STOP_REASON
    context = _proof_status_context(
        state=state, raw=raw, diagnostics=diagnostics, max_repair_attempts=6, language="en"
    )
    _api_terminal_is_valid(context)
    assert context["max_repair_attempts"] == 1
    assert EARLY_STOP_REASON not in json.dumps(context)
    # The dedicated code still reaches the job through its diagnostics.
    assert any(d.code == EARLY_STOP_DIAGNOSTIC_CODE for d in diagnostics)


def test_the_projection_leaves_an_ordinary_budget_exhaustion_alone(tmp_path: Path) -> None:
    _, _, statuses = _run(tmp_path, ["other"], max_repairs=2)
    state, diagnostics, _, _, raw = statuses[-1]
    context = _proof_status_context(
        state=state, raw=raw, diagnostics=diagnostics, max_repair_attempts=2, language="en"
    )
    _api_terminal_is_valid(context)
    assert context["max_repair_attempts"] == 2
