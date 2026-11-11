"""The explanation model call may run beside the semantic review, and never outlives a rejection.

The API accepts an explanation claim only for a ``verified`` job and a job becomes verified only
by an approved, settled review. So the call alone starts early; the claim, the explanation review
and the final write stay behind the approval, and every other outcome drops the early result.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.explanations import ExplanationDeadlineExceeded, ProofExplanation
from pals_agent.settings import AgentSettings
from pals_agent.speculative_explanation import SpeculativeExplanation
from pals_agent.usage import report_usage, usage_scope
from pals_agent.worker import SqsProofWorker
from tests.unit.test_worker import RecordingSemanticReviewer, SemanticReviewApi
from tests.unit.test_worker_claim_spec import (
    RecordingExplainer,
    RecordingOutputReviewer,
    _envelope,
)

STATEMENT = "theorem sample : True := by trivial"
LEAN = "theorem sample : True := by\n  trivial"
_WAIT = 5.0


class Trace:
    """Thread-safe record of what happened, in order."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self._lock = threading.Lock()

    def add(self, name: str) -> None:
        with self._lock:
            self.events.append(name)

    def index(self, name: str) -> int:
        return self.events.index(name)


class TracedApi(SemanticReviewApi):
    def __init__(self, trace: Trace, *, settle_error: Exception | None = None) -> None:
        super().__init__()
        self.trace = trace
        self.settle_error = settle_error
        self.explanation_updates: list[dict[str, Any]] = []
        self.usage_records: list[dict[str, Any]] = []

    def settle_proof_semantic_review(self, *, proof_job_id: str, evidence: dict[str, Any]) -> Any:
        self.trace.add("settle")
        if self.settle_error is not None:
            raise self.settle_error
        return super().settle_proof_semantic_review(
            proof_job_id=proof_job_id, evidence=evidence,
        )

    def settle_proof_semantic_review_unavailable(self, *, proof_job_id: str, failure: Any) -> Any:
        self.trace.add("settle_unavailable")
        return super().settle_proof_semantic_review_unavailable(
            proof_job_id=proof_job_id, failure=failure,
        )

    def upsert_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        self.trace.add(f"explanation_{kwargs['state']}")
        self.explanation_updates.append(kwargs)
        if kwargs["state"] == "generating":
            return _envelope("acquired", 3_000_000, resource_id=kwargs["proof_job_id"])
        return _envelope("terminal", None, resource_id=kwargs["proof_job_id"])

    def record_usage(self, **kwargs: Any) -> None:
        self.usage_records.append(kwargs)


class TracedReviewer(RecordingSemanticReviewer):
    """Blocks until the explanation call has started, which proves the two overlapped."""

    def __init__(
        self, trace: Trace, explain_started: threading.Event, *, reject: bool = False,
        wait_for_explainer: bool = True,
    ) -> None:
        super().__init__(reject=reject)
        self.trace = trace
        self.explain_started = explain_started
        self.wait_for_explainer = wait_for_explainer
        self.saw_explainer_start = False

    def review_proof(self, **kwargs: Any) -> Any:
        self.trace.add("review_start")
        if self.wait_for_explainer:
            self.saw_explainer_start = self.explain_started.wait(_WAIT)
        result = super().review_proof(**kwargs)
        self.trace.add("review_end")
        return result


class TracedExplainer(RecordingExplainer):
    def __init__(
        self, trace: Trace, started: threading.Event, *, error: Exception | None = None,
        report: bool = True,
    ) -> None:
        super().__init__(error=error)
        self.trace = trace
        self.started = started
        self.report = report

    def explain(self, **kwargs: Any) -> ProofExplanation:
        self.trace.add("explain_start")
        self.started.set()
        if self.report:
            report_usage(
                "99999999-9999-4999-8999-999999999999", "gpt-6-luna",
                {"input_tokens": 10, "output_tokens": 5},
            )
        try:
            return super().explain(**kwargs)
        finally:
            self.trace.add("explain_end")


class TracedOutputReviewer(RecordingOutputReviewer):
    def __init__(self, trace: Trace) -> None:
        super().__init__()
        self.trace = trace

    def review_explanation(self, **kwargs: Any) -> Any:
        self.trace.add("output_review")
        return super().review_explanation(**kwargs)


def _settings(**extra: Any) -> AgentSettings:
    # The feature is off by default in production; these tests exercise it switched on.
    values: dict[str, Any] = {"speculative_explanation_enabled": True, **extra}
    return cast(
        AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17, **values),
    )


def _run(
    *,
    reject: bool = False,
    reviewer_raises: bool = False,
    settle_error: Exception | None = None,
    explainer_error: Exception | None = None,
    settings: AgentSettings | None = None,
    claim: bool = True,
    with_output_reviewer: bool = True,
    wait_for_explainer: bool = True,
    outer_scope: bool = True,
) -> tuple[bool | None, Trace, TracedApi, TracedReviewer, TracedExplainer, list[dict[str, Any]],
           TracedOutputReviewer]:
    trace = Trace()
    started = threading.Event()
    api = TracedApi(trace, settle_error=settle_error)
    reviewer = TracedReviewer(
        trace, started, reject=reject,
        wait_for_explainer=wait_for_explainer and settings is None,
    )
    explainer = TracedExplainer(trace, started, error=explainer_error)
    output_reviewer = TracedOutputReviewer(trace)

    class RaisingReviewer(TracedReviewer):
        def review_proof(self, **kwargs: Any) -> Any:
            super().review_proof(**kwargs)
            raise RuntimeError("reviewer transport is unavailable")

    worker = SqsProofWorker(
        settings=settings or _settings(),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=cast(Any, explainer),
        output_reviewer=cast(Any, output_reviewer) if with_output_reviewer else None,
        proof_reviewer=cast(
            Any,
            RaisingReviewer(trace, started, wait_for_explainer=wait_for_explainer)
            if reviewer_raises else reviewer,
        ),
        uuid4_factory=lambda: uuid.UUID("44444444-4444-4444-8444-444444444444"),
    )
    held: list[dict[str, Any]] = []
    visibility: list[int] = []
    with usage_scope(held.append) if outer_scope else contextlib.nullcontext():
        acknowledged = worker.process_proof_job(
            "job-semantic",
            claim_id="55555555-5555-4555-8555-555555555555" if claim else None,
            extend_visibility=visibility.append if claim else None,
        )
    # Let a dropped early call finish so late effects would be visible to the assertions.
    for thread in threading.enumerate():
        if thread.name == "pals-speculative-explanation":
            thread.join(_WAIT)
    return acknowledged, trace, api, reviewer, explainer, held, output_reviewer


def test_the_explanation_call_runs_during_the_review_and_the_claim_waits_for_the_approval() -> None:
    acknowledged, trace, api, reviewer, explainer, held, output_reviewer = _run()

    assert acknowledged is True
    assert reviewer.saw_explainer_start, "the explanation call did not overlap the review"
    assert trace.index("explain_start") < trace.index("review_end")
    # Everything durable follows the settlement of the approval.
    assert trace.index("settle") < trace.index("explanation_generating")
    assert trace.index("explanation_generating") < trace.index("output_review")
    assert trace.index("output_review") < trace.index("explanation_completed")
    assert api.evidence[0]["decision"] == "approved"
    # Used once: no second generation, and it is the early candidate that was reviewed.
    assert len(explainer.explain_calls) == 1
    assert len(output_reviewer.explanation_calls) == 1
    completed = api.explanation_updates[-1]
    assert completed["state"] == "completed"
    assert completed["review_evidence"] is not None
    assert completed["content"] is not None
    # The call receives the same inputs a direct call would.
    call = explainer.explain_calls[0]
    assert (call["theorem_statement"], call["lean_code"], call["verified"]) == (
        STATEMENT, LEAN, True,
    )
    assert call["language"] == "zh-Hans"


def test_the_independent_explanation_review_still_runs_on_the_early_candidate() -> None:
    _, _, _, _, _, _, output_reviewer = _run()

    assert len(output_reviewer.explanation_calls) == 1
    reviewed = output_reviewer.explanation_calls[0]
    assert reviewed["lean_code"] == LEAN
    assert reviewed["explanation"].model == "explain-model"


def test_usage_of_an_adopted_call_reaches_the_active_reporter_once() -> None:
    _, _, _, _, _, held, _ = _run()

    assert [record["call_id"] for record in held] == ["99999999-9999-4999-8999-999999999999"]


def test_an_adopted_calls_usage_is_recorded_against_the_claim_with_no_outer_reporter() -> None:
    """The production delivery has no ambient reporter: adoption must report to the claim itself."""
    _, _, api, _, _, held, _ = _run(outer_scope=False)

    assert held == []
    assert [r["usage"]["call_id"] for r in api.usage_records] == [
        "99999999-9999-4999-8999-999999999999"
    ]
    assert api.usage_records[0]["claim_id"] == "55555555-5555-4555-8555-555555555555"


def test_a_rejected_review_leaves_no_explanation_no_claim_and_no_usage() -> None:
    acknowledged, trace, api, _, explainer, held, output_reviewer = _run(reject=True)

    assert acknowledged is True
    assert api.evidence[0]["decision"] == "rejected"
    # The call ran (that is the speculation), but nothing durable or billable came from it.
    assert len(explainer.explain_calls) == 1
    assert api.explanation_updates == []
    assert output_reviewer.explanation_calls == []
    assert held == []
    assert api.usage_records == []
    assert "explanation_generating" not in trace.events
    assert "explanation_completed" not in trace.events


def test_an_unavailable_review_drops_the_early_call() -> None:
    acknowledged, trace, api, _, explainer, held, output_reviewer = _run(reviewer_raises=True)

    assert acknowledged is True
    assert api.evidence == []
    assert api.operational_failure["failure_kind"] == "internal"
    assert api.explanation_updates == []
    assert output_reviewer.explanation_calls == []
    assert held == []
    assert "settle_unavailable" in trace.events
    assert len(explainer.explain_calls) == 1


def test_a_settlement_that_did_not_succeed_drops_the_early_call() -> None:
    from pals_agent.api_client import PalsApiError

    acknowledged, _, api, _, _, held, output_reviewer = _run(
        settle_error=PalsApiError("settlement response lost"),
    )

    assert acknowledged is False
    assert api.explanation_updates == []
    assert output_reviewer.explanation_calls == []
    assert held == []


def test_a_failed_early_call_ends_as_a_direct_failure_would_without_a_second_call() -> None:
    from pals_agent.explanations import ExplanationGenerationError

    acknowledged, _, api, _, explainer, _, output_reviewer = _run(
        explainer_error=ExplanationGenerationError("model returned invalid JSON"),
    )

    assert acknowledged is True
    assert [update["state"] for update in api.explanation_updates] == ["generating", "failed"]
    assert api.explanation_updates[-1]["diagnostics"][0].code == "pals.explanation_failed"
    assert len(explainer.explain_calls) == 1
    assert output_reviewer.explanation_calls == []


def test_without_the_switch_the_call_starts_only_after_the_settlement() -> None:
    _, trace, api, _, explainer, _, _ = _run(
        settings=_settings(speculative_explanation_enabled=False),
    )

    assert trace.index("review_end") < trace.index("settle") < trace.index("explain_start")
    assert len(explainer.explain_calls) == 1
    assert api.explanation_updates[-1]["state"] == "completed"


@pytest.mark.parametrize("missing", ["claim", "output_reviewer"])
def test_no_early_call_when_nothing_could_use_it(missing: str) -> None:
    _, _, api, _, explainer, _, _ = _run(
        claim=missing != "claim",
        with_output_reviewer=missing != "output_reviewer",
        wait_for_explainer=False,
    )

    assert explainer.explain_calls == []
    assert not any(update["state"] == "completed" for update in api.explanation_updates)


def test_an_early_call_is_used_only_for_the_inputs_it_started_with_and_only_once() -> None:
    started = threading.Event()
    trace = Trace()
    explainer = TracedExplainer(trace, started, report=False)
    speculative = SpeculativeExplanation.start(
        explain=explainer.explain, theorem_statement="A", lean_code="L", language="en",
        deadline=1e12, timeout_seconds=17,
    )
    assert started.wait(_WAIT)

    assert speculative.adopt(
        theorem_statement="B", lean_code="L", language="en", wait_seconds=_WAIT,
    ) is None
    # Closed by the first look: a matching second request cannot reuse it either.
    assert speculative.adopt(
        theorem_statement="A", lean_code="L", language="en", wait_seconds=_WAIT,
    ) is None


def test_an_early_call_that_is_not_done_by_the_deadline_is_a_missed_deadline() -> None:
    release = threading.Event()

    def slow_explain(**kwargs: Any) -> ProofExplanation:
        release.wait(_WAIT)
        raise AssertionError("not reached in time")

    speculative = SpeculativeExplanation.start(
        explain=slow_explain, theorem_statement="A", lean_code="L", language="en",
        deadline=1e12, timeout_seconds=17,
    )
    try:
        with pytest.raises(ExplanationDeadlineExceeded):
            speculative.adopt(
                theorem_statement="A", lean_code="L", language="en", wait_seconds=0.0,
            )
    finally:
        release.set()


def test_the_switch_is_off_by_default_and_must_be_turned_on_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pals_agent.settings import _strict_bool_env_default

    name = "PALS_SPECULATIVE_EXPLANATION_ENABLED"
    monkeypatch.delenv(name, raising=False)
    assert _strict_bool_env_default(name, False) is False
    monkeypatch.setenv(name, "true")
    assert _strict_bool_env_default(name, False) is True
    monkeypatch.setenv(name, "false")
    assert _strict_bool_env_default(name, False) is False
    # a settings object that does not carry the field behaves as off (no speculation)
    bare = cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17))
    assert getattr(bare, "speculative_explanation_enabled", False) is False
    assert AgentSettings.__dataclass_fields__["speculative_explanation_enabled"].default is False
