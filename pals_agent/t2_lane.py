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
import os
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, wait
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pals_agent.usage import forward_usage, hold_usage

NO_SKETCH_ENV = "PALS_T2_NO_SKETCH_ENABLED"
PARALLEL_CANDIDATES_ENV = "PALS_T2_PARALLEL_CANDIDATES_ENABLED"
PATCH_REPAIR_ENV = "PALS_T2_PATCH_REPAIR_ENABLED"
PARALLEL_EXPLANATION_ENV = "PALS_T2_PARALLEL_EXPLANATION_ENABLED"
PARALLEL_REVIEW_ENV = "PALS_T2_PARALLEL_REVIEW_ENABLED"
NO_DRAFT_ENV = "PALS_T2_NO_DRAFT_ENABLED"
NAME_SAFETY_ENV = "PALS_T2_NAME_SAFETY_ENABLED"
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


def patch_repair_enabled() -> bool:
    return _flag(PATCH_REPAIR_ENV)


def parallel_explanation_enabled() -> bool:
    return _flag(PARALLEL_EXPLANATION_ENV)


def parallel_review_enabled() -> bool:
    """The semantic review starts when a candidate goes to Lean (discarded if the proof
    changes); it still must approve the exact returned proof before an answer is released."""
    return _flag(PARALLEL_REVIEW_ENV)


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
    "`norm_num`, `simp`, `omega`, `gcongr`, `field_simp` or `ring`."
)


class BackgroundCall:
    """A call started now whose value is read later; it is waited for by ``drain_background``."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self._future: Future[Any] = Future()
        with _PENDING_LOCK:
            _PENDING.add(self._future)
        self._future.add_done_callback(_discard_pending)

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


def variant_instruction() -> str:
    """The instruction of the candidate running in this context ('' outside a race)."""
    index = _variant.get()
    if index is None:
        return ""
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
    """Receive the usage of explanation calls that were started and then discarded.

    A discarded call is infrastructure cost, not learner work, so it never reaches the ordinary
    usage reporter (quota); an evaluation sets this scope to count it as spend.
    """
    token = _discarded_sink.set(sink)
    try:
        yield
    finally:
        _discarded_sink.reset(token)


def _account_discarded(handle: Any, sink: Callable[[dict[str, Any]], None]) -> None:
    future: Future[None] = Future()
    with _PENDING_LOCK:
        _PENDING.add(future)
    future.add_done_callback(_discard_pending)

    def work() -> None:
        try:
            handle.wait()
            for record in handle.held_usage():
                with contextlib.suppress(Exception):
                    sink(record)
        finally:
            future.set_result(None)

    threading.Thread(target=work, name="pals-t2-discarded-usage", daemon=True).start()


class ExplanationRun:
    """Speculative calls of one pipeline run for one purpose (explanation or semantic review).

    ``start`` is called with every candidate that goes to verification (a race starts one per
    candidate); each distinct (statement, source) gets one call. ``finish`` returns the call that
    belongs to the proof actually returned and verified, and discards all others: a discarded
    call is billed work nobody uses, so its usage goes to the ``discarded_usage_scope`` sink (an
    evaluation counts it as spend) and never to the learner's usage reporter.
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
        self._sink = _discarded_sink.get()

    def _drop(self, handle: Any) -> None:
        handle.discard()
        self.discarded.append(handle)
        if self._sink is not None:
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
    try:
        yield memo, run
    finally:
        _memo.reset(memo_token)
        _explanation_run.reset(run_token)
        _review_run.reset(review_token)


# ---- candidate race ---------------------------------------------------------------------------

T = TypeVar("T")
_PENDING: set[Future[Any]] = set()
_PENDING_LOCK = threading.Lock()


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
        with _PENDING_LOCK:
            _PENDING.add(future)
        future.add_done_callback(_discard_pending)
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
    with _PENDING_LOCK:
        pending = set(_PENDING)
    if not pending:
        return 0
    _done, not_done = wait(pending, timeout=timeout)
    return len(not_done)
