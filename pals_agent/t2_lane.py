"""Switches and helpers for the 30-second generation lane ("T2"). Every switch defaults to off.

* ``PALS_T2_NO_SKETCH_ENABLED``           first attempt: Draft -> one full proof call (no Sketch).
* ``PALS_T2_PARALLEL_CANDIDATES_ENABLED`` first attempt: two candidates generated and compiled
                                          concurrently; the first that compiles wins.
* ``PALS_T2_PATCH_REPAIR_ENABLED``        first repairs: a minimal edit fed with a sanitised
                                          failure summary instead of route + handoff + regeneration.
* ``PALS_T2_NO_DRAFT_ENABLED``  first attempt: no Draft before the proof (routine requests skip
                                it; others run it beside the proof, kept only for repair).
* ``PALS_T2_NAME_SAFETY_ENABLED``  lemma-name guidance in the direct proof prompt.
* ``PALS_T2_PARALLEL_REVIEW_ENABLED``  the semantic review starts when a candidate goes to Lean.
* ``PALS_T2_PARALLEL_EXPLANATION_ENABLED`` the explanation call starts when a candidate goes to
                                          Lean, not after it is verified; discarded if the proof
                                          changes.

Each is read at call time (like the prompt flags in ``generator.py``), so an evaluation can switch
them per arm and they can be measured alone or together. Nothing here changes what counts as a
correct answer: a returned proof is still checked by Lean against the request's statement.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, wait
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pals_agent.usage import forward_usage, forward_usage_strict, hold_usage

logger = logging.getLogger(__name__)

NO_SKETCH_ENV = "PALS_T2_NO_SKETCH_ENABLED"
PARALLEL_CANDIDATES_ENV = "PALS_T2_PARALLEL_CANDIDATES_ENABLED"
PATCH_REPAIR_ENV = "PALS_T2_PATCH_REPAIR_ENABLED"
PARALLEL_EXPLANATION_ENV = "PALS_T2_PARALLEL_EXPLANATION_ENABLED"
PARALLEL_REVIEW_ENV = "PALS_T2_PARALLEL_REVIEW_ENABLED"
NO_DRAFT_ENV = "PALS_T2_NO_DRAFT_ENABLED"
NAME_SAFETY_ENV = "PALS_T2_NAME_SAFETY_ENABLED"
HETERO_RACE_ENV = "PALS_T2_HETERO_RACE_ENABLED"
SOURCE_HYGIENE_ENV = "PALS_T2_SOURCE_HYGIENE_ENABLED"
CHEAP_FIRST_ENV = "PALS_T2_CHEAP_FIRST_ENABLED"
# Unset: the first attempt runs at HETERO_EFFORTS[0] ("low"). Set (none|low|medium): that effort
# instead, for the cheap-first un-raced first attempt only; repairs never take it.
FIRST_EFFORT_ENV = "PALS_T2_FIRST_EFFORT"
# Reasoning effort of each race candidate when HETERO_RACE_ENV is on: a fast one and a strong one.
HETERO_EFFORTS = ("low", "medium")
# How long a failed compile waits for the held alternate candidate to finish generating. A model
# repair costs about as much, so waiting longer than this never pays.
ALTERNATE_WAIT_SECONDS = 60.0
CANDIDATE_COUNT = 2
# Consecutive repairs that may use a patch before the full repair path takes over.
PATCH_REPAIR_MAX_ROUNDS = 2


def _flag(name: str) -> bool:
    value = os.environ.get(name, "false")
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def no_sketch_enabled() -> bool:
    return _flag(NO_SKETCH_ENV)


def parallel_candidates_enabled() -> bool:
    return _flag(PARALLEL_CANDIDATES_ENV)


def hetero_race_enabled() -> bool:
    return _flag(HETERO_RACE_ENV)


def first_effort() -> str:
    value = os.environ.get(FIRST_EFFORT_ENV)
    if value is None or value == "":
        return HETERO_EFFORTS[0]
    if value not in {"none", "low", "medium"}:
        raise ValueError(f"{FIRST_EFFORT_ENV} must be none, low or medium")
    return value


def cheap_first_enabled() -> bool:
    """The first attempt's proof runs at the fast effort (``HETERO_EFFORTS[0]``); every repair
    (a patch, a full repair) runs at the role's own, stronger effort. One candidate, no race: a
    plain compile failure escalates instead of paying for a second candidate up front.

    The first attempt also receives candidate 0's style instruction (``variant_instruction``: a
    short proof that closes routine goals with automation), exactly as the fast candidate of the
    heterogeneous race does; the measured effect is that of both together, not of the effort
    alone."""
    return _flag(CHEAP_FIRST_ENV)


def source_hygiene_enabled() -> bool:
    """Drop redundant ``import Mathlib.*`` lines and add the ``open`` a notation needs."""
    return _flag(SOURCE_HYGIENE_ENV)


def patch_repair_enabled() -> bool:
    return _flag(PATCH_REPAIR_ENV)


def parallel_explanation_enabled() -> bool:
    return _flag(PARALLEL_EXPLANATION_ENV)


def parallel_review_enabled() -> bool:
    """The semantic review starts when a candidate goes to Lean (discarded if the proof
    changes); it still must approve the exact returned proof before an answer is released."""
    return _flag(PARALLEL_REVIEW_ENV)


LEAN_SLOTS_ENV = "PALS_T2_LEAN_SLOTS"


def lean_slots() -> int:
    """How many racing candidates may compile at once (default: all of them).

    The race assumes Lean capacity for this many concurrent compiles per job. With 1 the race
    is serial at the compiler: the first candidate to be ready compiles, and the other is
    cancelled before it compiles if that one wins. Set it to the capacity a job really has."""
    raw = os.environ.get(LEAN_SLOTS_ENV)
    if raw is None:
        return CANDIDATE_COUNT
    if not raw.isdigit() or not 1 <= int(raw) <= CANDIDATE_COUNT:
        raise ValueError(f"{LEAN_SLOTS_ENV} must be an integer from 1 to {CANDIDATE_COUNT}")
    return int(raw)


def validate_flags() -> None:
    """Read every T2 switch once, so a malformed value fails at startup, not mid-job after
    model spend. Raises ValueError."""
    for check in (
        no_sketch_enabled,
        parallel_candidates_enabled,
        patch_repair_enabled,
        parallel_explanation_enabled,
        parallel_review_enabled,
        no_draft_enabled,
        name_safety_enabled,
        hetero_race_enabled,
        source_hygiene_enabled,
        cheap_first_enabled,
        first_effort,
        lean_slots,
        lean_process_slots,
    ):
        check()


LEAN_PROCESS_SLOTS_ENV = "PALS_T2_LEAN_PROCESS_SLOTS"
_process_slots_lock = threading.Lock()
_process_slots: dict[int, threading.BoundedSemaphore] = {}  # one semaphore per size, per process


def lean_process_slots() -> int:
    """Process-wide cap on Lean compiles of every pipeline (0 = no cap, the default).

    Every verifier call a ``ProofPipeline`` makes (final compile, Sketch check, lemma repair, a
    race candidate's compile) goes through ``SlottedVerifier`` when this is set at pipeline
    construction, so the default path is capped too: setting only this variable, with every T2
    flag off, bounds the worker's concurrent compiles. The per-race slots (``PALS_T2_LEAN_SLOTS``)
    bound one job's racing candidates; this bounds all jobs together. Size it from measured
    parallel-compile capacity (the verifier's own slot count), not from this module. It is read
    when a pipeline is constructed and on each call."""
    raw = os.environ.get(LEAN_PROCESS_SLOTS_ENV)
    if raw is None:
        return 0
    if not raw.isdigit() or int(raw) > 64:
        raise ValueError(f"{LEAN_PROCESS_SLOTS_ENV} must be an integer from 0 to 64")
    return int(raw)


@contextmanager
def process_lean_slot() -> Iterator[None]:
    size = lean_process_slots()
    if size == 0:
        yield
        return
    with _process_slots_lock:
        semaphore = _process_slots.setdefault(size, threading.BoundedSemaphore(size))
    with semaphore:
        yield


_lost_lock = threading.Lock()
_lost_reports = 0


def _note_lost_usage_report() -> None:
    global _lost_reports
    with _lost_lock:
        _lost_reports += 1
    logger.warning("t2_usage_report_failed")  # closed code: no content


def lost_usage_reports() -> int:
    """How many speculative-call usage records could not be reported (process lifetime)."""
    with _lost_lock:
        return _lost_reports


class SlottedVerifier:
    """A verifier whose every compile holds a process-wide Lean slot (no-op without a cap).

    Wraps any verifier object: ``verify``, ``verify_sketch`` and any other attribute are
    delegated, so every call site of the pipeline (including ones added later) shares the cap."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if name not in {"verify", "verify_sketch"} or not callable(attribute):
            return attribute

        def slotted(*args: Any, **kwargs: Any) -> Any:
            with process_lean_slot():
                return attribute(*args, **kwargs)

        return slotted


_preflight: ContextVar[Callable[[str], list[Any]] | None] = ContextVar(
    "pals_t2_preflight", default=None
)


def current_preflight() -> Callable[[str], list[Any]] | None:
    """The run's own source preflight (same harness and target rules as the main loop)."""
    return _preflight.get()


@contextmanager
def preflight_scope(check: Callable[[str], list[Any]]) -> Iterator[None]:
    token = _preflight.set(check)
    try:
        yield
    finally:
        _preflight.reset(token)


def no_draft_enabled() -> bool:
    """First attempt: no Draft before the proof. Routine requests (``ProofRequest.routine``)
    skip the Draft entirely; the others run the Draft beside the proof and keep it for repair."""
    return _flag(NO_DRAFT_ENV)


def name_safety_enabled() -> bool:
    """Add the lemma-name guidance (the top first-attempt failure class: unknown identifiers)."""
    return _flag(NAME_SAFETY_ENV)


NAME_SAFETY_GUIDANCE = (
    "Name safety: an unknown identifier is the most common reason a first proof fails. Use a "
    "Mathlib lemma by name only when you are certain of its exact current spelling and "
    "namespace (Lean 4 Mathlib: `Nat.succ_le_iff`, `Real.sqrt_nonneg`, `abs_nonneg`; never "
    "Lean 3 style such as `nat.succ_le_iff` or `real.sqrt`). Otherwise build the fact "
    "yourself with `have`, or use `nlinarith [sq_nonneg (a - b), ...]`, `positivity`, "
    "`norm_num`, `simp`, `omega`, `gcongr`, `field_simp` or `ring`. Import only `import Mathlib` "
    "(never a submodule such as `Mathlib.Tactic.Omega`, unless the theorem harness below gives "
    "its own header), write `open Topology` before using `𝓝`, "
    "and never name a variable `λ` (it is the lambda keyword; use `lam` or `μ`)."
)


class BackgroundCall:
    """A call started now whose value is read later; it is waited for by ``drain_background``."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self._future: Future[Any] = Future()
        _track(self._future)

        def run() -> None:
            try:
                self._future.set_result(fn())
            except BaseException as exc:  # noqa: BLE001 -- surfaced as None by ``value``
                self._future.set_exception(exc)

        threading.Thread(
            target=copy_context().run, args=(run,), name="pals-t2-background", daemon=True
        ).start()

    def value(self) -> Any | None:
        """The result, waiting for it; ``None`` when the call raised."""
        try:
            return self._future.result()
        except BaseException:  # noqa: BLE001
            return None


# ---- candidate variants -----------------------------------------------------------------------

_variant: ContextVar[int | None] = ContextVar("pals_t2_candidate_variant", default=None)
VARIANT_INSTRUCTIONS = (
    "Candidate style: prefer a short proof that closes routine goals with automation "
    "(`nlinarith`, `positivity`, `norm_num`, `simp`, `omega`) and only a few `have` steps.",
    "Candidate style: prefer an explicit step-by-step proof with named `have`/`calc` steps "
    "that each use a well-known Mathlib lemma, avoiding heavy search tactics.",
)


@contextmanager
def candidate_variant(index: int) -> Iterator[None]:
    """Run a block as race candidate ``index`` (what the race itself sets in each thread)."""
    token = _variant.set(index)
    try:
        yield
    finally:
        _variant.reset(token)


def variant_effort() -> str | None:
    """The reasoning effort of the race candidate running in this context (None outside a
    heterogeneous race): candidate 0 is the fast one, candidate 1 the strong one."""
    index = _variant.get()
    if index is None:
        return None
    if hetero_race_enabled():
        return HETERO_EFFORTS[index % len(HETERO_EFFORTS)]
    # Cheap-first sets variant 0 for the one un-raced first attempt only; a race thread (which
    # sets its own variants) never takes an effort from it.
    if cheap_first_enabled() and index == 0 and not parallel_candidates_enabled():
        return first_effort()
    return None


def variant_instruction() -> str:
    """The instruction of the candidate running in this context ('' outside a race)."""
    index = _variant.get()
    if index is None or hetero_race_enabled():
        return ""  # candidates differ by effort, not by prompt, when the race is heterogeneous
    return VARIANT_INSTRUCTIONS[index % len(VARIANT_INSTRUCTIONS)]


# ---- verification memo ------------------------------------------------------------------------


class VerificationMemo:
    """Lean results a racing candidate already obtained, keyed by its exact source."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: dict[str, Any] = {}

    @staticmethod
    def _key(lean_code: str) -> str:
        return hashlib.sha256(lean_code.encode("utf-8")).hexdigest()

    def put(self, lean_code: str, result: Any) -> None:
        with self._lock:
            self._results[self._key(lean_code)] = result

    def peek(self, lean_code: str) -> Any | None:
        with self._lock:
            return self._results.get(self._key(lean_code))

    def take(self, lean_code: str) -> Any | None:
        with self._lock:
            return self._results.pop(self._key(lean_code), None)


_memo: ContextVar[VerificationMemo | None] = ContextVar("pals_t2_memo", default=None)


def current_memo() -> VerificationMemo | None:
    return _memo.get()


def take_memoised(lean_code: str) -> Any | None:
    """The Lean result a racing candidate already obtained for exactly this source, once."""
    memo = _memo.get()
    return memo.take(lean_code) if memo is not None else None


def peek_memoised(lean_code: str) -> Any | None:
    memo = _memo.get()
    return memo.peek(lean_code) if memo is not None else None


# ---- explanation started beside verification ---------------------------------------------------


_discarded_sink: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "pals_t2_discarded_usage_sink", default=None
)


@contextmanager
def discarded_usage_scope(sink: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    """Receive the usage of explanation/review calls that were started and then discarded.

    Without this scope a discarded call is metered through the ordinary usage reporter, so no
    spend is lost. An evaluation sets it to count discarded work separately (and itself adds it
    to the spend).
    """
    token = _discarded_sink.set(sink)
    try:
        yield
    finally:
        _discarded_sink.reset(token)


def settle_unadopted(handle: Any, timeout: float = 120.0) -> None:
    """Report the usage of a speculative call the caller chose not to adopt.

    A kept handle's usage is forwarded only when it is adopted. A caller that releases an answer
    without adopting it (or drops the result) must settle it here, so provider spend is never
    silently lost. Waits up to ``timeout`` for the call to end and reports what it used; if it is
    still running then, the usage is reported when it ends (see ``drain_background``)."""
    handle.discard()
    handle.wait(timeout)
    if handle.done():
        forward_usage(handle.take_usage_once())
        return
    # Still running at the deadline: its usage is not known yet and must not be marked as
    # forwarded now. Report it through the ordinary reporter of this context when it ends
    # (tracked, so a drain waits for it; a failed report is counted and logged).
    logger.warning("t2_settle_timeout")  # closed code: no content
    parent = copy_context()
    _account_discarded(handle, lambda record: parent.copy().run(forward_usage_strict, [record]))


def _account_discarded(handle: Any, sink: Callable[[dict[str, Any]], None]) -> None:
    future: Future[None] = Future()
    _track(future)

    def work() -> None:
        try:
            handle.wait()
            for record in handle.take_usage_once():
                try:
                    sink(record)
                except Exception:  # noqa: BLE001 -- counted and logged, never silent
                    _note_lost_usage_report()
        finally:
            future.set_result(None)

    threading.Thread(target=work, name="pals-t2-discarded-usage", daemon=True).start()


class ExplanationRun:
    """Speculative calls of one pipeline run for one purpose (explanation or semantic review).

    ``start`` is called with every candidate that goes to verification (a race starts one per
    candidate); each distinct (statement, source) gets one call. ``finish`` returns the call that
    belongs to the proof actually returned and verified, and discards all others: a discarded
    call is billed work nobody uses; its usage goes to the ``discarded_usage_scope`` sink when an
    evaluation set one, and otherwise to the ordinary usage reporter of this context.
    """

    def __init__(
        self,
        explain: Callable[..., Any] | None,
        language: str,
        enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._explain = explain
        self._language = language
        self._enabled = enabled or parallel_explanation_enabled
        self._handles: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()
        self.discarded: list[Any] = []
        # An evaluation may set its own sink; otherwise a discarded call is metered through the
        # ordinary usage reporter of this context, so production spend is never under-reported.
        parent = copy_context()
        # Each report runs in its own copy: ``Context.run`` cannot be entered by two threads at
        # once, and two discarded calls can finish together.
        self._sink = _discarded_sink.get() or (
            lambda record: parent.copy().run(forward_usage_strict, [record])
        )

    def _drop(self, handle: Any) -> None:
        handle.discard()
        self.discarded.append(handle)
        _account_discarded(handle, self._sink)

    @property
    def active(self) -> bool:
        return self._explain is not None and self._enabled()

    def start(self, *, statement: str, lean_code: str) -> None:
        if not self.active or not lean_code.strip():
            return
        key = (statement, lean_code)
        with self._lock:
            if key in self._handles:
                return
            from pals_agent.speculative_explanation import SpeculativeExplanation

            # An early start is an optimisation only: a failure to start is ignored.
            with contextlib.suppress(Exception):
                self._handles[key] = SpeculativeExplanation.start(
                    explain=self._explain,  # type: ignore[arg-type]
                    theorem_statement=statement,
                    lean_code=lean_code,
                    language=self._language,
                    deadline=time.monotonic() + EXPLANATION_DEADLINE_SECONDS,
                    timeout_seconds=EXPLANATION_CALL_TIMEOUT_SECONDS,
                )

    def finish(self, *, verified: bool, statement: str, lean_code: str) -> Any | None:
        with self._lock:
            handles, self._handles = self._handles, {}
        keep = handles.pop((statement, lean_code), None) if verified else None
        for handle in handles.values():
            self._drop(handle)
        if keep is None and verified is False:
            return None
        return keep


EXPLANATION_DEADLINE_SECONDS = 360.0
EXPLANATION_CALL_TIMEOUT_SECONDS = 120.0
_explanation_run: ContextVar[ExplanationRun | None] = ContextVar(
    "pals_t2_explanation_run", default=None
)


def current_explanation_run() -> ExplanationRun | None:
    return _explanation_run.get()


_review_run: ContextVar[ExplanationRun | None] = ContextVar("pals_t2_review_run", default=None)


def current_review_run() -> ExplanationRun | None:
    return _review_run.get()


@contextmanager
def t2_run_scope(
    explain: Callable[..., Any] | None,
    language: str,
    review: Callable[..., Any] | None = None,
) -> Iterator[tuple[VerificationMemo, ExplanationRun]]:
    """Per-run state: the verification memo and the explanation run, visible to race threads."""
    memo, run = VerificationMemo(), ExplanationRun(explain, language)
    review_run = ExplanationRun(review, language, enabled=parallel_review_enabled)
    memo_token = _memo.set(memo)
    run_token = _explanation_run.set(run)
    review_token = _review_run.set(review_run)
    background_token = _run_background.set(RunBackground())
    try:
        yield memo, run
    finally:
        _run_background.reset(background_token)
        _memo.reset(memo_token)
        _explanation_run.reset(run_token)
        _review_run.reset(review_token)


# ---- candidate race ---------------------------------------------------------------------------

T = TypeVar("T")
_PENDING: set[Future[Any]] = set()  # fallback for work started outside a pipeline run
_PENDING_LOCK = threading.Lock()


class AlternateSlot:
    """The race candidate that did not win, kept for a failed compile of the winner.

    Only a candidate that passed the worker's own preflight is offered. ``take`` hands it out at
    most once (a redelivered or resumed delivery cannot submit it twice) and waits for a candidate
    that is still being generated, up to a deadline; it returns None once every candidate has
    finished without one. Usage is not tracked here: the race forwards each candidate's usage
    exactly once when the candidate ends.
    """

    def __init__(self, candidates: int) -> None:
        self._cond = threading.Condition()
        self._running = candidates
        self._offered: Any = None
        self._taken = False

    def offer(self, generated: Any) -> None:
        with self._cond:
            if self._offered is None and not self._taken:
                self._offered = generated
            self._cond.notify_all()

    def finished_one(self) -> None:
        with self._cond:
            self._running -= 1
            self._cond.notify_all()

    def take(self, timeout: float, should_stop: Callable[[], bool] | None = None) -> Any:
        """The held candidate, waiting up to ``timeout`` for one still being generated.

        ``should_stop`` is polled while waiting (a shutdown request): a stop returns None at once
        and leaves the candidate unclaimed.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self._cond:
            while self._offered is None and self._running > 0 and not self._taken:
                if should_stop is not None and should_stop():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(min(remaining, 0.2))
            if self._taken or self._offered is None:
                return None
            self._taken = True
            offered, self._offered = self._offered, None
            return offered


_repair_alternate: ContextVar[AlternateSlot | None] = ContextVar(
    "pals_t2_repair_alternate", default=None
)


# What bounds the alternate's wait: the end of the claim's lease (monotonic) and the worker's stop
# request. Set by the worker around the pipeline run; unset means the fixed default only.
_alternate_limits: ContextVar[tuple[float | None, Callable[[], bool] | None]] = ContextVar(
    "pals_t2_alternate_limits", default=(None, None)
)
ALTERNATE_LEASE_MARGIN_SECONDS = 30.0


@contextmanager
def alternate_limits(
    *, lease_deadline: float | None, should_stop: Callable[[], bool] | None
) -> Iterator[None]:
    token = _alternate_limits.set((lease_deadline, should_stop))
    try:
        yield
    finally:
        _alternate_limits.reset(token)


def alternate_wait() -> tuple[float, Callable[[], bool] | None]:
    """How long the held candidate may be waited for, and the stop predicate to poll."""
    lease_deadline, should_stop = _alternate_limits.get()
    wait = ALTERNATE_WAIT_SECONDS
    if lease_deadline is not None:
        wait = min(
            wait, lease_deadline - ALTERNATE_LEASE_MARGIN_SECONDS - time.monotonic()
        )
    return max(0.0, wait), should_stop


def repair_alternate() -> AlternateSlot | None:
    """The alternate a repair run may use instead of a model repair (set by the worker)."""
    return _repair_alternate.get()


@contextmanager
def alternate_for_repair(slot: AlternateSlot | None) -> Iterator[None]:
    token = _repair_alternate.set(slot)
    try:
        yield
    finally:
        _repair_alternate.reset(token)


class RunBackground:
    """Calls one pipeline run left running (race losers, an unused Draft, discarded
    explanations). Per run, so one run's accounting never waits for, or mixes with, another's."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._futures: set[Future[Any]] = set()
        self.alternate: AlternateSlot | None = None  # set by a heterogeneous race

    def track(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)

    def _forget(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)

    def pending(self) -> int:
        with self._lock:
            return len(self._futures)

    def drain(self, timeout: float = 180.0) -> int:
        """Wait for them; their usage is forwarded when each ends. Returns how many were still
        running at the deadline (their usage is then not counted in this run)."""
        with self._lock:
            pending = set(self._futures)
        if not pending or timeout <= 0:
            return len(pending)
        _done, not_done = wait(pending, timeout=timeout)
        return len(not_done)


_run_background: ContextVar[RunBackground | None] = ContextVar("pals_t2_background", default=None)


def current_background() -> RunBackground | None:
    return _run_background.get()


def _track(future: Future[Any]) -> None:
    background = _run_background.get()
    if background is not None:
        background.track(future)
        return
    with _PENDING_LOCK:
        _PENDING.add(future)
    future.add_done_callback(_discard_pending)


@dataclass(slots=True)
class Candidate(Generic[T]):  # noqa: UP046
    index: int
    value: T | None = None
    error: BaseException | None = None
    usage: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    forwarded: bool = False


@dataclass(slots=True)
class RaceResult(Generic[T]):  # noqa: UP046
    winner: Candidate[T] | None
    best: Candidate[T] | None
    candidates: list[Candidate[T]]
    cancelled: int  # candidates still running when the race was decided


class _Race(Generic[T]):  # noqa: UP046
    def __init__(self, count: int, parent: Any) -> None:
        self.lock = threading.Lock()
        self.decided = False
        self.winner_index: int | None = None
        self.parent = parent  # a copy of the caller's context: it holds the usage reporter
        self.candidates = [Candidate[T](i) for i in range(count)]

    def forward(self, candidate: Candidate[T]) -> None:
        if candidate.forwarded:
            return
        candidate.forwarded = True
        self.parent.run(forward_usage, candidate.usage)


def race_candidates(  # noqa: UP047
    tasks: Sequence[Callable[[threading.Event], T]],
    *,
    is_win: Callable[[T], bool],
    rank: Callable[[T], float],
) -> RaceResult[T]:
    """Run ``tasks`` concurrently; return when one wins, or when all have finished.

    ``is_win(value)`` decides a win (for the lane: Lean accepted the candidate). Each task gets a
    cancel event, set once the race is decided; a task checks it before starting expensive work
    such as a compile. A request already sent to the model cannot be recalled, so a loser's tokens
    are still spent: every candidate's usage is held back and forwarded exactly once to the usage
    reporter active in the caller, at once for the winner and the finished losers, and as soon as
    a still-running loser ends. ``drain_background`` waits for those. When nobody wins, the
    finished candidate with the lowest ``rank`` is returned as ``best``.
    """
    race: _Race[T] = _Race(len(tasks), copy_context())
    cancel = threading.Event()

    def run(index: int, future: Future[None]) -> None:
        try:
            _run_candidate(index)
        finally:
            future.set_result(None)

    def _run_candidate(index: int) -> None:
        candidate = race.candidates[index]
        with hold_usage() as records:
            _variant.set(index)
            try:
                candidate.value = tasks[index](cancel)
            except BaseException as exc:  # noqa: BLE001 -- surfaced by the caller via .error
                candidate.error = exc
        with race.lock:
            candidate.usage = list(records)
            candidate.done = True
            if race.decided and race.winner_index != index:
                race.forward(candidate)  # a loser that ended after the decision

    futures: list[Future[None]] = []
    for index in range(len(tasks)):
        future: Future[None] = Future()
        futures.append(future)
        _track(future)
        # One real thread per candidate: they must run at the same time, never queue.
        threading.Thread(
            target=copy_context().run,
            args=(run, index, future),
            name="pals-t2-candidate",
            daemon=True,
        ).start()

    winner: Candidate[T] | None = None
    remaining = set(futures)
    while remaining and winner is None:
        done_now, remaining = wait(remaining, return_when="FIRST_COMPLETED")
        for candidate in race.candidates:
            if (
                candidate.done
                and candidate.error is None
                and candidate.value is not None
                and is_win(candidate.value)
            ):
                winner = candidate
                break
    with race.lock:
        race.decided = True
        race.winner_index = winner.index if winner is not None else None
        cancel.set()
        running = sum(1 for candidate in race.candidates if not candidate.done)
        for candidate in race.candidates:
            if candidate.done:
                race.forward(candidate)

    finished = [c for c in race.candidates if c.done and c.error is None and c.value is not None]
    best = min(finished, key=lambda c: rank(c.value), default=None)  # type: ignore[arg-type]
    return RaceResult(
        winner=winner,
        best=winner or best,
        candidates=list(race.candidates),
        cancelled=running,
    )


def _discard_pending(future: Future[Any]) -> None:
    with _PENDING_LOCK:
        _PENDING.discard(future)


def drain_background(timeout: float = 180.0) -> int:
    """Wait for candidates still running after a race; their usage is forwarded when they end.

    Call it after the wall clock stops and before reading a run's usage, so a cancelled loser's
    tokens are counted without adding to the measured time. Returns how many were still running
    at the deadline.
    """
    background = _run_background.get()
    inner = background.drain(timeout) if background is not None else 0
    with _PENDING_LOCK:
        pending = set(_PENDING)
    if not pending:
        return inner
    _done, not_done = wait(pending, timeout=timeout)
    return inner + len(not_done)
