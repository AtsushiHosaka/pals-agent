#!/usr/bin/env python3
"""A/B timing of PALS_SPECULATIVE_EXPLANATION_ENABLED on the real worker code path.

    uv run --extra dev python tools/speculative_ab.py --fake -n 20 --seed 1
    uv run --extra dev python tools/speculative_ab.py --real --confirm-spend -n 3   # model calls

Each pair runs ``SqsProofWorker.process_proof_job`` for a job in state ``semantic_review`` twice,
once with the switch off and once on, alternating ABAB (off, on, off, on, ...) so slow drift
falls on both arms. The worker, the speculative-explanation module, the claim, the explanation
review and the final write are the production code. Only the edges are replaced:

* the API client is a stub that answers the calls this stage makes (after an optional latency);
* the semantic reviewer, the explainer and the explanation reviewer are either fake clients with
  configurable latency distributions (``--fake``, the default) or the repo's real clients built
  from ``AgentSettings.from_env()`` (``--real``; exits with a message when the environment has no
  OpenAI credentials, and needs ``--confirm-spend`` because it makes paid calls).

With ``--fake`` time is virtual: every thread keeps its own logical clock, a forked thread
starts at its parent's time and a join takes the later of the two. A run therefore takes
milliseconds, and the same seed always gives the same numbers. Both arms of pair *i* use the same
random draws, so the paired difference measures the switch and not the luck of the draw.

Output
    stderr  one ``proof_request_latency`` JSON event per delivery, exactly the line
            ``pals_agent.runtime_latency.report_latency`` writes (``--events none`` to drop,
            ``--events PREFIX`` to write PREFIX.off.jsonl and PREFIX.on.jsonl for
            ``python -m pals_agent.latency_report``)
    stdout  a compact table per arm (p50 / p95 / mean of semantic_review, explanation,
            explanation_review and the total from review start to the explanation being
            written; counts of outcomes, speculative calls started and discarded, and explain
            usage forwarded) and the paired difference off - on with a bootstrap 95% CI.

The default latency distributions are placeholders, not measurements.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import random
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO, cast

from pals_agent import runtime_latency
from pals_agent.explanations import (
    ExplanationGenerationError,
    ExplanationSection,
    LeanLineReference,
    ProofExplanation,
    ProofOutputReview,
    ProofSemanticReview,
)
from pals_agent.latency_report import percentile
from pals_agent.runtime_latency import TimedTransport, traced_delivery
from pals_agent.usage import capture_usage, report_usage, usage_scope
from pals_agent.worker import SqsProofWorker

STATEMENT = "theorem sample : True := by trivial"
LEAN = "theorem sample : True := by\n  trivial"
_REPO_ROOT = Path(__file__).resolve().parents[1]
JOB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RESULT_URI = "s3://pals-artifacts/proof-jobs/job-semantic/result.lean"
CLAIM_ID = "55555555-5555-4555-8555-555555555555"
SPECULATIVE_THREAD = "pals-speculative-explanation"
ARMS = ("off", "on")
METRICS = ("semantic_review", "explanation", "explanation_review", "total")
_FAKE_BASE = "https://fake-provider.invalid"
_MONOTONIC_BASE = 1000.0
_UNIX_EPOCH_MS = 1_793_000_000_000.0
_API_DRAWS = 8


# --------------------------------------------------------------------------------------------
# Clocks


class VirtualClock:
    """Logical time per thread of control; ``sleep`` advances it instantly.

    The time lives in a ``ContextVar``. ``SpeculativeExplanation.start`` runs its thread in a
    copy of the caller's context, so the forked thread starts at the time of the fork and then
    advances on its own. A join is ``advance_to(finished_at)``.
    """

    virtual = True

    def __init__(self) -> None:
        self._elapsed: ContextVar[float] = ContextVar(
            f"speculative_ab_time_{id(self)}", default=0.0,
        )

    def monotonic(self) -> float:
        return _MONOTONIC_BASE + self._elapsed.get()

    def time(self) -> float:
        return _UNIX_EPOCH_MS / 1000 + self._elapsed.get()

    def sleep(self, seconds: float) -> None:
        self._elapsed.set(self._elapsed.get() + max(0.0, seconds))

    def advance_to(self, monotonic: float) -> None:
        self._elapsed.set(max(self._elapsed.get(), monotonic - _MONOTONIC_BASE))

    def reset(self) -> None:
        """Start a delivery at time zero, so floating-point sums do not depend on position."""
        self._elapsed.set(0.0)


class RealClock:
    virtual = False

    def monotonic(self) -> float:
        return time.monotonic()

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def advance_to(self, monotonic: float) -> None:  # real time cannot be advanced
        return None


Clock = VirtualClock | RealClock


@contextlib.contextmanager
def _trace_clock(clock: Clock) -> Iterator[None]:
    """Let the repo's own tracing read the virtual clock; no production code is changed."""
    if not clock.virtual:
        yield
        return
    namespace = vars(runtime_latency)
    original = namespace["time"]
    namespace["time"] = SimpleNamespace(monotonic=clock.monotonic, time=clock.time)
    try:
        yield
    finally:
        namespace["time"] = original


# --------------------------------------------------------------------------------------------
# Latency distributions and the draws shared by both arms of a pair


def parse_distribution(spec: str) -> Callable[[random.Random], float]:
    """``const:S``, ``uniform:LO,HI`` or ``lognormal:MEDIAN,SIGMA`` (seconds)."""
    kind, _, rest = spec.partition(":")
    try:
        numbers = [float(part) for part in rest.split(",") if part.strip()]
    except ValueError as error:
        raise ValueError(f"bad distribution {spec!r}") from error
    if any(not math.isfinite(n) or n < 0 for n in numbers):
        raise ValueError(f"bad distribution {spec!r}: numbers must be finite and >= 0")
    if kind == "const" and len(numbers) == 1:
        value = numbers[0]
        return lambda rng: value
    if kind == "uniform" and len(numbers) == 2 and numbers[0] <= numbers[1]:
        low, high = numbers
        return lambda rng: rng.uniform(low, high)
    if kind == "lognormal" and len(numbers) == 2 and numbers[0] > 0:
        mu, sigma = math.log(numbers[0]), numbers[1]
        return lambda rng: rng.lognormvariate(mu, sigma)
    raise ValueError(
        f"bad distribution {spec!r}; use const:S, uniform:LO,HI or lognormal:MED,SIGMA"
    )


@dataclass(frozen=True)
class Draws:
    """Everything random about one pair, drawn once and used by both arms."""

    review_s: float
    explain_s: float
    explain_review_s: float
    api_s: tuple[float, ...]
    reject: bool
    explain_fails: bool


@dataclass(frozen=True)
class Scenario:
    review: str = "lognormal:8,0.25"
    explain: str = "lognormal:20,0.3"
    explain_review: str = "lognormal:8,0.25"
    api: str = "const:0.3"
    reject_rate: float = 0.0
    explain_fail_rate: float = 0.0


def draw_pairs(scenario: Scenario, pairs: int, seed: int) -> list[Draws]:
    rng = random.Random(seed)
    review = parse_distribution(scenario.review)
    explain = parse_distribution(scenario.explain)
    explain_review = parse_distribution(scenario.explain_review)
    api = parse_distribution(scenario.api)
    return [
        Draws(
            review_s=review(rng),
            explain_s=explain(rng),
            explain_review_s=explain_review(rng),
            api_s=tuple(api(rng) for _ in range(_API_DRAWS)),
            reject=rng.random() < scenario.reject_rate,
            explain_fails=rng.random() < scenario.explain_fail_rate,
        )
        for _ in range(pairs)
    ]


# --------------------------------------------------------------------------------------------
# Stub API and the marks one iteration leaves behind


@dataclass
class Marks:
    review_start: float | None = None
    explain_finished: float = 0.0
    completed_at: float | None = None
    explain_threads: list[str] = field(default_factory=list)
    # Usage of every explanation call, kept even when the call was discarded (the production
    # path drops a discarded call's usage, which is exactly the waste this has to measure).
    explain_records: list[dict[str, Any]] = field(default_factory=list)
    # Exceptions the model clients raised (class and a short message), for telling a provider
    # outage from a model answer.
    errors: list[str] = field(default_factory=list)

    def note_error(self, error: BaseException) -> None:
        self.errors.append(f"{type(error).__name__}: {str(error)[:160]}")


@dataclass(frozen=True)
class Case:
    """The proof job the stub API hands to the worker."""

    name: str
    statement: str
    formal_statement: str
    lean: str
    target_name: str
    language: str


TRIVIAL_CASE = Case("trivial", STATEMENT, "True", LEAN, "sample", "zh-Hans")


def square_continuity_case() -> Case:
    """The x^2 continuity card: the Lean proof is the repo's own test data."""
    base = _REPO_ROOT / "testdata" / "square-continuity-recipe-v1"
    card = json.loads((base / "card.json").read_text(encoding="utf-8"))
    lean = (base / "proofs" / "square_continuous_explicit_epsilon_delta.lean").read_text(
        encoding="utf-8"
    ).rstrip("\n")
    return Case(
        "x2", card["statement"], "Continuous (fun x : ℝ => x ^ 2)", lean,
        "square_continuous_explicit_epsilon_delta", "ja",
    )


def load_case(name: str) -> Case:
    return square_continuity_case() if name == "x2" else TRIVIAL_CASE


@dataclass
class Current:
    """The draws of the pair being run; the fake clients read from here."""

    draws: Draws | None = None


def _explanation() -> ProofExplanation:
    reference = LeanLineReference(2, 2, "  trivial")
    return ProofExplanation(
        overview="証明の概要です。",
        sections=(
            ExplanationSection(
                id="finish",
                title="証明を閉じる",
                summary="この命題は追加の仮定なしに成り立つことを確認します。",
                references=(reference,),
            ),
        ),
        conclusion="したがって True が証明されました。",
        model="explain-model",
        provider="test-provider",
        prompt="PRIVATE PROMPT",
        raw_model_output="PRIVATE RAW OUTPUT",
        elapsed_ms=2,
    )


def _explanation_resource(proof_job_id: str, state: str) -> dict[str, Any]:
    content = None
    if state == "completed":
        content = {
            "overview": "証明の概要です。",
            "sections": [{
                "id": "finish",
                "title": "証明を閉じる",
                "summary": "この命題は追加の仮定なしに成り立つことを確認します。",
                "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
            }],
            "conclusion": "したがって True が証明されました。",
            "model": "explain-model",
            "provider": "test-provider",
            "elapsed_ms": 2,
        }
    return {
        "proof_job_id": proof_job_id, "state": state, "content": content,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        "diagnostics": [],
    }


def _envelope(status: str, lease_remaining_ms: int | None, proof_job_id: str) -> dict[str, Any]:
    state = "generating" if status == "acquired" else "completed"
    return {
        "claim_status": status,
        "lease_remaining_ms": lease_remaining_ms,
        "resource": _explanation_resource(proof_job_id, state),
    }


class StubApi:
    """Answers the API calls of the semantic-review -> explanation stage, after a latency."""

    def __init__(
        self, clock: Clock, current: Current, marks: Marks, case: Case = TRIVIAL_CASE,
    ) -> None:
        self.clock = clock
        self.current = current
        self.marks = marks
        self.case = case
        self.calls = 0
        self.evidence: list[dict[str, Any]] = []
        self.operational_failure: Any = None
        self.explanation_updates: list[dict[str, Any]] = []

    def _latency(self) -> None:
        draws = self.current.draws
        if draws is not None:
            self.clock.sleep(draws.api_s[self.calls % len(draws.api_s)])
        self.calls += 1

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        self._latency()
        return {
            "id": proof_job_id,
            "state": "semantic_review",
            "result_artifact_uri": RESULT_URI,
            "chat_id": "chat-1",
            "output_language": self.case.language,
            "theorem_statement": self.case.statement,
            "request_context": {"formal_statement": self.case.formal_statement},
            "lean_code": self.case.lean,
            "status_context": {"target_declaration": {
                "kind": "theorem", "name": self.case.target_name,
                "proposition": self.case.formal_statement,
            }},
            "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
            "generation_session_id": "11111111-1111-4111-8111-111111111111",
        }

    def get_verification_candidate_binding(self, **kwargs: Any) -> dict[str, Any]:
        self._latency()
        return {
            "schema_version": "pals.verification-candidate-binding.v1", **kwargs,
            "mutation_claim_id": "11111111-1111-4111-8111-111111111111",
            "lean_sha256": hashlib.sha256(self.case.lean.encode()).hexdigest(),
            "result_artifact_uri": RESULT_URI,
            "source_binding_sha256": None, "candidate_status": "semantic_review",
        }

    def settle_proof_semantic_review(
        self, *, proof_job_id: str, evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self._latency()
        self.evidence.append(evidence)
        return {
            "id": proof_job_id,
            "state": "verified" if evidence["decision"] == "approved" else "failed",
        }

    def settle_proof_semantic_review_unavailable(
        self, *, proof_job_id: str, failure: Any,
    ) -> dict[str, Any]:
        self._latency()
        self.operational_failure = failure
        return {"id": proof_job_id, "state": "failed"}

    def upsert_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["state"] != "generating":
            # Whoever writes the result has waited for the explanation call to finish.
            self.clock.advance_to(self.marks.explain_finished)
        self._latency()
        self.explanation_updates.append(kwargs)
        if kwargs["state"] == "completed":
            self.marks.completed_at = self.clock.monotonic()
        if kwargs["state"] == "generating":
            return _envelope("acquired", 3_000_000, kwargs["proof_job_id"])
        return _envelope("terminal", None, kwargs["proof_job_id"])

    def record_usage(self, **kwargs: Any) -> None:
        return None


# --------------------------------------------------------------------------------------------
# Fake clients: each model call is one request through the repo's own TimedTransport, so the
# trace records it exactly as it records a real call (provider / generation / role).


class _FakeProviderTransport:
    def __init__(self, clock: Clock, seconds: Callable[[], float]) -> None:
        self._clock = clock
        self._seconds = seconds

    def request(
        self, *, method: str, url: str, headers: dict[str, str], body: bytes | None,
        timeout_seconds: float,
    ) -> Any:
        self._clock.sleep(self._seconds())
        return SimpleNamespace(status_code=200, headers=[])


def _call(transport: TimedTransport) -> None:
    transport.request(
        method="POST", url=_FAKE_BASE + "/v1/responses", headers={}, body=None,
        timeout_seconds=1.0,
    )


class _FakeSemanticReviewer:
    def __init__(self, clock: Clock, current: Current) -> None:
        self._current = current
        self._transport = TimedTransport(
            cast(Any, _FakeProviderTransport(clock, lambda: self._draws().review_s)),
            "provider", _FAKE_BASE,
        )

    def _draws(self) -> Draws:
        assert self._current.draws is not None
        return self._current.draws

    def review_proof(self, **kwargs: Any) -> ProofSemanticReview:
        _call(self._transport)
        return ProofSemanticReview(
            decision="rejected" if self._draws().reject else "approved",
            rationale="The target and proof match the learner request.",
            reviewer_provider="fake", reviewer_model="fake-review",
            session_id="33333333-3333-4333-8333-333333333333",
        )


class _FakeExplainer:
    def __init__(self, clock: Clock, current: Current) -> None:
        self._current = current
        self._transport = TimedTransport(
            cast(Any, _FakeProviderTransport(clock, lambda: self._draws().explain_s)),
            "provider", _FAKE_BASE,
        )

    def _draws(self) -> Draws:
        assert self._current.draws is not None
        return self._current.draws

    def explain(self, **kwargs: Any) -> ProofExplanation:
        _call(self._transport)
        report_usage(
            "99999999-9999-4999-8999-999999999999", "gpt-6-luna",
            {"input_tokens": 10, "output_tokens": 5},
        )
        if self._draws().explain_fails:
            raise ExplanationGenerationError("model returned invalid JSON")
        return _explanation()


class _FakeOutputReviewer:
    def __init__(self, clock: Clock, current: Current) -> None:
        self._current = current
        self._transport = TimedTransport(
            cast(Any, _FakeProviderTransport(clock, lambda: self._draws().explain_review_s)),
            "provider", _FAKE_BASE,
        )

    def _draws(self) -> Draws:
        assert self._current.draws is not None
        return self._current.draws

    def review_explanation(self, **kwargs: Any) -> ProofOutputReview:
        _call(self._transport)
        return ProofOutputReview(
            kind="explanation", reviewer_provider="fake", reviewer_model="fake-review",
            session_id="33333333-3333-4333-8333-333333333333",
            rationale="The explanation is grounded in the verified Lean source.",
        )


# --------------------------------------------------------------------------------------------
# Marking proxies (used with fake and real clients alike)


class _ReviewerProxy:
    def __init__(self, inner: Any, marks: Marks, clock: Clock) -> None:
        self._inner, self._marks, self._clock = inner, marks, clock

    def review_proof(self, **kwargs: Any) -> Any:
        self._marks.review_start = self._clock.monotonic()
        try:
            return self._inner.review_proof(**kwargs)
        except Exception as error:
            self._marks.note_error(error)
            raise


class _ExplainerProxy:
    def __init__(self, inner: Any, marks: Marks, clock: Clock) -> None:
        self._inner, self._marks, self._clock = inner, marks, clock

    def explain(self, **kwargs: Any) -> Any:
        self._marks.explain_threads.append(threading.current_thread().name)
        try:
            with capture_usage() as records:
                try:
                    return self._inner.explain(**kwargs)
                except Exception as error:
                    self._marks.note_error(error)
                    raise
                finally:
                    self._marks.explain_records.extend(records)
        finally:
            self._marks.explain_finished = max(
                self._marks.explain_finished, self._clock.monotonic(),
            )


class _OutputReviewerProxy:
    def __init__(self, inner: Any, marks: Marks, clock: Clock) -> None:
        self._inner, self._marks, self._clock = inner, marks, clock

    def review_explanation(self, **kwargs: Any) -> Any:
        # The review cannot start before the explanation it reviews exists.
        self._clock.advance_to(self._marks.explain_finished)
        try:
            return self._inner.review_explanation(**kwargs)
        except Exception as error:
            self._marks.note_error(error)
            raise


# --------------------------------------------------------------------------------------------
# One delivery


@dataclass
class IterationResult:
    pair: int
    arm: str
    outcome: str
    semantic_review_ms: float | None
    explanation_ms: float | None
    explanation_review_ms: float | None
    total_ms: float | None
    speculative_started: bool
    speculative_discarded: bool
    explain_calls: int
    explain_usage_forwarded: int
    explanation_upserts: int
    event: dict[str, Any] | None = field(default=None, repr=False)
    cost_usd: float = 0.0
    wasted_cost_usd: float = 0.0
    failure: str | None = None


@dataclass
class Clients:
    explainer: Any
    output_reviewer: Any
    reviewer: Any


# USD per million tokens. gpt-6-luna: input at the cache-write price, the upper bound that
# pals_agent.usage prices with (price snapshot openai-gpt-6-luna-standard-upper-bound-2026-09-30;
# list prices in docs/proof-reuse-latency-decisions-research-2026-09-30.md). A model without an
# entry is an error, so a changed role binding cannot be spent unmetered.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {"gpt-6-luna": (0.125, 0.50)}


class UnknownPrice(Exception):
    pass


def record_cost(record: dict[str, Any]) -> float:
    model = str(record.get("model"))
    if model not in PRICES_USD_PER_MTOK:
        raise UnknownPrice(f"no price for model {model!r}")
    price_in, price_out = PRICES_USD_PER_MTOK[model]
    return float(
        record["input_tokens"] * price_in + record["output_tokens"] * price_out
    ) / 1e6


def _event_line(metrics: dict[str, Any]) -> str:
    """The line ``runtime_latency.report_latency`` writes for one delivery."""
    return json.dumps(
        {"event": "proof_request_latency", "metrics": metrics},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def _phase_ms(
    metrics: dict[str, Any], service: str, phase: str, role: str | None = None,
) -> float | None:
    values = [
        row["elapsed_total_ms"] for row in metrics.get("phases", ())
        if row["service"] == service and row["phase"] == phase
        and (role is None or row["role"] == role)
    ]
    return math.fsum(values) if values else None


def _join_speculative_threads(timeout: float) -> None:
    for thread in threading.enumerate():
        if thread.name == SPECULATIVE_THREAD:
            thread.join(timeout)


def _release_in_flight(now: float) -> None:
    """Spans still running when the delivery ended are unfinished, as in a real delivery."""
    trace = runtime_latency._ACTIVE.get()
    if trace is None:
        return
    with trace.lock:
        for span in trace.spans:
            if span["end"] is not None and span["end"] > now:
                span["end"] = None


def _outcome(api: StubApi, marks: Marks) -> str:
    if marks.completed_at is not None:
        return "completed"
    if api.operational_failure is not None:
        return "review_unavailable"
    if api.evidence and api.evidence[-1]["decision"] != "approved":
        return "rejected"
    if any(update["state"] == "failed" for update in api.explanation_updates):
        return "explanation_failed"
    return "other"


def run_iteration(
    *, pair: int, arm: str, clock: Clock, settings: Any, draws: Draws | None,
    build_clients: Callable[[Current], Clients], current: Current,
    case: Case = TRIVIAL_CASE,
) -> IterationResult:
    current.draws = draws
    if isinstance(clock, VirtualClock):
        clock.reset()
    marks = Marks()
    api = StubApi(clock, current, marks, case)
    clients = build_clients(current)
    worker = SqsProofWorker(
        settings=settings,
        api_client=cast(Any, api),
        pipeline=None,
        explainer=cast(Any, _ExplainerProxy(clients.explainer, marks, clock)),
        output_reviewer=cast(Any, _OutputReviewerProxy(clients.output_reviewer, marks, clock)),
        proof_reviewer=cast(Any, _ReviewerProxy(clients.reviewer, marks, clock)),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    events: list[dict[str, Any]] = []
    forwarded: list[dict[str, Any]] = []
    with _trace_clock(clock), usage_scope(forwarded.append):
        with traced_delivery("proof_job", JOB_ID, emit=events.append):
            worker.process_proof_job(
                JOB_ID, claim_id=CLAIM_ID, extend_visibility=lambda seconds: None,
            )
            if clock.virtual:
                _join_speculative_threads(10.0)
                _release_in_flight(clock.monotonic())
        _join_speculative_threads(300.0)
    metrics = events[0] if events else None
    outcome = _outcome(api, marks)
    started = SPECULATIVE_THREAD in marks.explain_threads
    claimed = any(update["state"] == "generating" for update in api.explanation_updates)
    completed = outcome == "completed"
    adopted = {record.get("call_id") for record in forwarded}
    cost = math.fsum(record_cost(record) for record in forwarded)
    wasted = math.fsum(
        record_cost(record) for record in marks.explain_records
        if record.get("call_id") not in adopted
    )
    return IterationResult(
        pair=pair,
        arm=arm,
        outcome=outcome,
        semantic_review_ms=(
            _phase_ms(metrics, "local", "semantic_review") if metrics else None
        ),
        explanation_ms=(
            _phase_ms(metrics, "provider", "generation", "explain")
            if metrics and completed else None
        ),
        explanation_review_ms=(
            _phase_ms(metrics, "provider", "generation", "explanation_review")
            if metrics and completed else None
        ),
        total_ms=(
            (marks.completed_at - marks.review_start) * 1000
            if completed and marks.completed_at is not None and marks.review_start is not None
            else None
        ),
        speculative_started=started,
        speculative_discarded=started and not claimed,
        explain_calls=len(marks.explain_threads),
        explain_usage_forwarded=sum(1 for _ in forwarded),
        explanation_upserts=len(api.explanation_updates),
        event=metrics,
        cost_usd=cost + wasted,
        wasted_cost_usd=wasted,
        failure=None if completed else _failure_detail(api, outcome, marks),
    )


def _failure_detail(api: StubApi, outcome: str, marks: Marks) -> str:
    """A short description of why a delivery did not complete: the outcome, the client errors
    (exception class and a short message) and, for an operational failure, its repr."""
    parts = [outcome]
    if outcome == "review_unavailable":
        parts.append(repr(api.operational_failure)[:200])
    if outcome == "rejected":
        parts.append(str(api.evidence[-1].get("decision")))
    parts.extend(marks.errors[:3])
    return " | ".join(parts)[:500]


# --------------------------------------------------------------------------------------------
# The experiment


def arm_sequence(pairs: int, order: str) -> list[tuple[int, str]]:
    """ABAB: off, on, off, on ... ; ``abba`` flips every second pair to cancel linear drift."""
    sequence: list[tuple[int, str]] = []
    for pair in range(pairs):
        arms = ARMS if order == "abab" or pair % 2 == 0 else ARMS[::-1]
        sequence.extend((pair, arm) for arm in arms)
    return sequence


def _fake_clients(clock: Clock) -> Callable[[Current], Clients]:
    return lambda current: Clients(
        explainer=_FakeExplainer(clock, current),
        output_reviewer=_FakeOutputReviewer(clock, current),
        reviewer=_FakeSemanticReviewer(clock, current),
    )


def _fake_settings(on: bool) -> Any:
    return SimpleNamespace(explanation_model_timeout_seconds=17, speculative_explanation_enabled=on)


def run_experiment(
    *, pairs: int, seed: int, scenario: Scenario, order: str = "abab",
    clients_factory: Callable[[Clock], Callable[[Current], Clients]] | None = None,
    settings_factory: Callable[[bool], Any] | None = None, clock: Clock | None = None,
    case: Case = TRIVIAL_CASE, max_usd: float | None = None,
    retries: int = 0, excluded: list[IterationResult] | None = None,
    stop_reason: list[str] | None = None, reserve_usd: float = 0.05,
) -> list[IterationResult]:
    """Run ``pairs`` pairs; fake clients and virtual time unless a factory and clock are given.

    ``max_usd`` stops the run before an iteration that could take the spend past the cap (the
    reserve is the dearest iteration so far, at least ``reserve_usd``); the reason is appended
    to ``stop_reason``. With ``retries`` a pair in which an arm hit a transient provider failure
    (see :func:`is_transient`) is run again, up to that many times; the aborted attempts go to
    ``excluded`` and are not part of the returned results.
    """
    virtual = clock is None
    the_clock: Clock = clock if clock is not None else VirtualClock()
    draws: list[Draws | None] = (
        list(draw_pairs(scenario, pairs, seed)) if virtual else [None] * pairs
    )
    build_clients = (clients_factory or _fake_clients)(the_clock)
    make_settings = settings_factory or _fake_settings
    current = Current()
    results: list[IterationResult] = []
    spent = 0.0
    dearest = reserve_usd
    by_pair: dict[int, list[tuple[int, str]]] = {}
    for pair, arm in arm_sequence(pairs, order):
        by_pair.setdefault(pair, []).append((pair, arm))
    for pair, slots in by_pair.items():
        for attempt in range(retries + 1):
            attempt_results: list[IterationResult] = []
            for _, arm in slots:
                if max_usd is not None and spent + dearest > max_usd:
                    if stop_reason is not None:
                        stop_reason.append(
                            f"spend cap: ${spent:.4f} spent, next iteration may cost "
                            f"${dearest:.4f}, cap ${max_usd:.2f}"
                        )
                    return results + attempt_results
                result = run_iteration(
                    pair=pair, arm=arm, clock=the_clock, settings=make_settings(arm == "on"),
                    draws=draws[pair], build_clients=build_clients, current=current, case=case,
                )
                spent += result.cost_usd
                dearest = max(dearest, result.cost_usd)
                attempt_results.append(result)
                if is_transient(result):
                    break
            if any(is_transient(r) for r in attempt_results) and attempt < retries:
                if excluded is not None:
                    excluded.extend(attempt_results)
                continue
            results.extend(attempt_results)
            break
    return results


_TRANSIENT_MARKERS = (
    "timeout", "timed out", "rate_limit", "rate limit", "429", "500", "502", "503", "504",
    "overloaded", "connection", "server_error", "api_error",
)


def is_transient(result: IterationResult) -> bool:
    """A delivery that stopped on a provider-side error, not on what the model answered.

    Judged on the failure description (content-free codes); a model rejection is a result.
    """
    if result.outcome in ("completed", "rejected") or result.failure is None:
        return False
    text = result.failure.lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


# --------------------------------------------------------------------------------------------
# Statistics


def stats(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "n": float(len(values)),
        "p50_ms": round(percentile(list(values), 0.5), 1),
        "p95_ms": round(percentile(list(values), 0.95), 1),
        "mean_ms": round(math.fsum(values) / len(values), 1),
    }


def bootstrap_mean_ci(
    values: Sequence[float], *, resamples: int, seed: int, alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Mean and a percentile bootstrap interval, deterministic for a seed."""
    if not values:
        raise ValueError("no values to resample")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        math.fsum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)
    )
    return (
        math.fsum(values) / n,
        percentile(means, alpha / 2),
        percentile(means, 1 - alpha / 2),
    )


def summarize(results: Sequence[IterationResult], *, resamples: int, seed: int) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in ARMS:
        mine = [r for r in results if r.arm == arm]
        arms[arm] = {
            "iterations": len(mine),
            "outcomes": dict(sorted(Counter(r.outcome for r in mine).items())),
            "completed": sum(r.outcome == "completed" for r in mine),
            "failed": sum(r.outcome != "completed" for r in mine),
            "speculative_started": sum(r.speculative_started for r in mine),
            "speculative_discarded": sum(r.speculative_discarded for r in mine),
            "explain_calls": sum(r.explain_calls for r in mine),
            "explain_usage_forwarded": sum(r.explain_usage_forwarded for r in mine),
            "explanation_upserts": sum(r.explanation_upserts for r in mine),
            "cost_usd": round(math.fsum(r.cost_usd for r in mine), 6),
            "wasted_cost_usd": round(math.fsum(r.wasted_cost_usd for r in mine), 6),
            "metrics": {
                name: stats([
                    v for r in mine if (v := getattr(r, f"{name}_ms")) is not None
                ])
                for name in METRICS
            },
        }
    paired: dict[str, Any] = {}
    by_pair: dict[int, dict[str, IterationResult]] = {}
    for r in results:
        by_pair.setdefault(r.pair, {})[r.arm] = r
    for name in METRICS:
        diffs = [
            off - on
            for arms_ in by_pair.values()
            if "off" in arms_ and "on" in arms_
            and (off := getattr(arms_["off"], f"{name}_ms")) is not None
            and (on := getattr(arms_["on"], f"{name}_ms")) is not None
        ]
        if diffs:
            mean, low, high = bootstrap_mean_ci(diffs, resamples=resamples, seed=seed)
            paired[name] = {
                "pairs": len(diffs), "mean_diff_ms": round(mean, 1),
                "ci95_ms": [round(low, 1), round(high, 1)], "resamples": resamples,
            }
    return {"arms": arms, "paired_off_minus_on": paired}


def render_table(summary: dict[str, Any], header: str) -> str:
    lines = [header, ""]
    lines.append(
        f"{'arm':<5}{'n':>4}{'completed':>11}{'failed':>8}{'spec_started':>14}"
        f"{'spec_discarded':>16}{'explain_usage_fwd':>19}{'explanation_writes':>20}"
    )
    for arm in ARMS:
        a = summary["arms"][arm]
        lines.append(
            f"{arm:<5}{a['iterations']:>4}{a['completed']:>11}{a['failed']:>8}"
            f"{a['speculative_started']:>14}{a['speculative_discarded']:>16}"
            f"{a['explain_usage_forwarded']:>19}{a['explanation_upserts']:>20}"
            + ("  " + json.dumps(a["outcomes"], sort_keys=True)
               if set(a["outcomes"]) != {"completed"} else "")
        )
    if any(summary["arms"][arm]["cost_usd"] for arm in ARMS):
        lines += [""] + [
            f"cost {arm}: ${summary['arms'][arm]['cost_usd']:.4f} "
            f"(of which discarded speculative calls ${summary['arms'][arm]['wasted_cost_usd']:.4f})"
            for arm in ARMS
        ]
    lines += ["", f"{'arm':<5}{'metric':<20}{'n':>4}{'p50_ms':>11}{'p95_ms':>11}{'mean_ms':>11}"]
    for arm in ARMS:
        for name in METRICS:
            s = summary["arms"][arm]["metrics"][name]
            if s is None:
                lines.append(f"{arm:<5}{name:<20}{0:>4}{'-':>11}{'-':>11}{'-':>11}")
            else:
                lines.append(
                    f"{arm:<5}{name:<20}{int(s['n']):>4}{s['p50_ms']:>11.1f}"
                    f"{s['p95_ms']:>11.1f}{s['mean_ms']:>11.1f}"
                )
    lines += ["", "paired difference off - on (positive = the switch saves time), 95% bootstrap CI"]
    if not summary["paired_off_minus_on"]:
        lines.append("  no pair completed in both arms")
    for name, p in summary["paired_off_minus_on"].items():
        low, high = p["ci95_ms"]
        lines.append(
            f"  {name:<20}pairs={p['pairs']:<4}mean={p['mean_diff_ms']:>10.1f} ms"
            f"  [{low:.1f}, {high:.1f}]"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------
# Real clients


class RealUnavailable(Exception):
    """The environment cannot run real clients; the message says why."""


def real_setup() -> tuple[Callable[[Clock], Callable[[Current], Clients]], Callable[[bool], Any]]:
    from pals_agent.settings import AgentSettings

    try:
        base = AgentSettings.from_env()
    except Exception as error:
        raise RealUnavailable(
            f"settings could not be built from the environment ({type(error).__name__})"
        ) from error
    if not base.openai_api_key.strip():
        raise RealUnavailable(
            "no OpenAI credentials in the environment (PALS_OPENAI_API_KEY / OPENAI_API_KEY)"
        )
    from pals_agent import factory

    try:
        explainer = factory.build_proof_explainer(base)
        output_reviewer = factory.build_proof_output_reviewer(base)
        reviewer = factory.build_proof_semantic_reviewer(base)
    except Exception as error:
        raise RealUnavailable(
            f"real clients could not be built ({type(error).__name__})"
        ) from error

    def clients_factory(clock: Clock) -> Callable[[Current], Clients]:
        return lambda current: Clients(
            explainer=explainer, output_reviewer=output_reviewer, reviewer=reviewer,
        )

    def settings_factory(on: bool) -> Any:
        return dataclasses.replace(base, speculative_explanation_enabled=on)

    return clients_factory, settings_factory


# --------------------------------------------------------------------------------------------
# Command line


def load_openai_key(path: Path) -> bool:
    """Put OPENAI_API_KEY from an env file into ``os.environ``; nothing else, and never printed.

    Only that one name is read, so other settings in the file (model names, base URLs) cannot
    change the production role bindings this harness measures. An existing value wins.
    """
    import os

    if os.environ.get("OPENAI_API_KEY"):
        return True
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        if sep and name.strip() == "OPENAI_API_KEY":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                os.environ["OPENAI_API_KEY"] = value
                return True
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A/B timing of PALS_SPECULATIVE_EXPLANATION_ENABLED.",
        epilog="Default distributions are placeholders, not measurements.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fake", action="store_true", help="fake clients, virtual time (default)")
    mode.add_argument("--real", action="store_true", help="the repo's real clients; paid calls")
    parser.add_argument("--confirm-spend", action="store_true", help="required with --real")
    parser.add_argument("--max-usd", type=float, default=None,
                        help="spend cap in USD (required with --real); the run stops before an "
                             "iteration that could pass it")
    parser.add_argument("--case", choices=("trivial", "x2"), default="trivial",
                        help="the proof job: a one-line True proof, or the x^2 continuity card")
    parser.add_argument("--retries", type=int, default=0,
                        help="re-run a pair up to this many times after a transient provider "
                             "failure; aborted attempts are listed apart from the results")
    parser.add_argument("--env-file", default=None, metavar="PATH",
                        help="load only the OpenAI API key from this env file (value never shown)")
    parser.add_argument("-n", "--pairs", type=int, default=20, help="pairs, i.e. 2n deliveries")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--order", choices=("abab", "abba"), default="abab")
    parser.add_argument("--review", default=Scenario.review, metavar="DIST",
                        help="semantic review latency, seconds (fake)")
    parser.add_argument("--explain", default=Scenario.explain, metavar="DIST",
                        help="explanation call latency, seconds (fake)")
    parser.add_argument("--explain-review", default=Scenario.explain_review, metavar="DIST",
                        help="explanation review latency, seconds (fake)")
    parser.add_argument("--api", default=Scenario.api, metavar="DIST",
                        help="latency of each stub API call, seconds (fake)")
    parser.add_argument("--reject-rate", type=float, default=0.0,
                        help="share of semantic reviews that reject (fake)")
    parser.add_argument("--explain-fail-rate", type=float, default=0.0,
                        help="share of explanation calls that fail (fake)")
    parser.add_argument("--bootstrap", type=int, default=2000, help="bootstrap resamples")
    parser.add_argument(
        "--events", default="-", metavar="PREFIX|-|none",
        help="proof_request_latency events: - for stderr, none, or PREFIX.<arm>.jsonl",
    )
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    return parser


def _write_events(results: Sequence[IterationResult], target: str, stderr: TextIO) -> None:
    if target == "none":
        return
    with contextlib.ExitStack() as stack:
        handles: dict[str, TextIO] = {}
        for r in results:
            if r.event is None:
                continue
            line = _event_line(r.event) + "\n"
            if target == "-":
                stderr.write(line)
                continue
            if r.arm not in handles:
                handles[r.arm] = stack.enter_context(
                    open(f"{target}.{r.arm}.jsonl", "w", encoding="utf-8")
                )
            handles[r.arm].write(line)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.pairs < 1 or args.bootstrap < 1:
        print("error: -n and --bootstrap must be at least 1", file=sys.stderr)
        return 2
    clients_factory = settings_factory = clock = None
    if args.env_file is not None:
        try:
            load_openai_key(Path(args.env_file))
        except OSError as error:
            print(f"error: cannot read --env-file ({type(error).__name__})", file=sys.stderr)
            return 2
    if args.real:
        if not args.confirm_spend:
            print(
                f"error: --real makes {3 * 2 * args.pairs}+ paid model calls; "
                "pass --confirm-spend to run it", file=sys.stderr,
            )
            return 2
        if args.max_usd is None or args.max_usd <= 0:
            print("error: --real needs --max-usd > 0", file=sys.stderr)
            return 2
        try:
            clients_factory, settings_factory = real_setup()
        except RealUnavailable as error:
            print(f"error: real mode not run: {error}", file=sys.stderr)
            return 2
        clock = RealClock()
        header = (f"real clients; case {args.case}; {args.pairs} pairs, {args.order.upper()}; "
                  f"cap ${args.max_usd:.2f}")
    else:
        header = f"fake clients, virtual time; seed {args.seed}; {args.pairs} pairs, " \
                 f"{args.order.upper()}"
    scenario = Scenario(
        review=args.review, explain=args.explain, explain_review=args.explain_review,
        api=args.api, reject_rate=args.reject_rate, explain_fail_rate=args.explain_fail_rate,
    )
    excluded: list[IterationResult] = []
    stop_reason: list[str] = []
    try:
        results = run_experiment(
            pairs=args.pairs, seed=args.seed, scenario=scenario, order=args.order,
            clients_factory=clients_factory, settings_factory=settings_factory, clock=clock,
            case=load_case(args.case), max_usd=args.max_usd, retries=args.retries,
            excluded=excluded, stop_reason=stop_reason,
        )
    except (ValueError, UnknownPrice) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    _write_events(results, args.events, sys.stderr)
    summary = summarize(results, resamples=args.bootstrap, seed=args.seed)
    summary["case"] = args.case
    summary["per_iteration"] = [
        {"pair": r.pair, "arm": r.arm, "outcome": r.outcome,
         **{f"{m}_ms": getattr(r, f"{m}_ms") for m in METRICS},
         "cost_usd": round(r.cost_usd, 6), "wasted_cost_usd": round(r.wasted_cost_usd, 6),
         "explain_calls": r.explain_calls}
        for r in results
    ]
    summary["stopped_early"] = stop_reason
    summary["excluded_transient"] = [
        {"pair": r.pair, "arm": r.arm, "outcome": r.outcome, "failure": r.failure,
         "cost_usd": round(r.cost_usd, 6)} for r in excluded
    ]
    if args.json:
        json.dump(summary, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_table(summary, header))
        for note in stop_reason:
            sys.stdout.write(f"stopped early: {note}\n")
        for row in summary["excluded_transient"]:
            sys.stdout.write(f"excluded (transient, re-run): {json.dumps(row, sort_keys=True)}\n")
        failed = [r for r in results if r.outcome != "completed"]
        for r in failed:
            sys.stdout.write(f"failed (kept as a result): pair {r.pair} {r.arm} {r.failure}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
