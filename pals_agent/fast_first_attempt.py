"""Fast first attempt: one merged model call proposes the first candidate proof of a request.

Default off (``PALS_FAST_FIRST_ATTEMPT_ENABLED``).  It only PROPOSES a Lean source.  Everything that
decides whether the answer is correct stays where it was: the source goes through the same
preflight as any generated candidate, then the API's own compile (the verifier), the independent
semantic review and the mandatory explanation review.  This module never verifies, publishes or
claims anything, and it never raises into the pipeline: on any problem, or when the deadline
passes, it proposes nothing and the pipeline generates its first attempt exactly as without it.

A resident Lean is optional.  With a ``sieve`` (for example one built on ``ResidentWorker``), the
model's tactics and the automation portfolio are compiled at once and only a source that compiles
is proposed; without one, the model's first tactic is proposed unchecked and the API's compile
decides (a failure then costs one ordinary repair).
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Final

from pals_agent import fast_answer as fa
from pals_agent.automation_portfolio import PORTFOLIO, check_formal_statement
from pals_agent.fast_lane import THEOREM_NAME
from pals_agent.recipe_instantiation import InstantiationRejected

ENABLED_ENV: Final = "PALS_FAST_FIRST_ATTEMPT_ENABLED"
DEADLINE_ENV: Final = "PALS_FAST_FIRST_ATTEMPT_DEADLINE_SECONDS"
DEFAULT_DEADLINE_SECONDS: Final = 8.0
HEADER: Final = "import Mathlib\n\n"

# (sources, timeout_seconds) -> indices of sources that compile, best first; may raise
Sieve = Callable[[Sequence[str], float], Sequence[int]]


def enabled() -> bool:
    value = os.environ.get(ENABLED_ENV, "false")
    if value not in {"true", "false"}:
        raise ValueError(f"{ENABLED_ENV} must be true or false")
    return value == "true"


def deadline_seconds() -> float:
    raw = os.environ.get(DEADLINE_ENV)
    if raw is None:
        return DEFAULT_DEADLINE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{DEADLINE_ENV} must be a number") from None
    if not 1.0 <= value <= 60.0:
        raise ValueError(f"{DEADLINE_ENV} must be between 1 and 60")
    return value


_UNFINISHED = re.compile(r"\b(sorry|admit)\b")


def theorem_source(proposition: str, tactic: str) -> str:
    """One closed theorem, no ``set_option`` (the verifier's default limits apply)."""
    body = "\n  ".join(line.rstrip() for line in tactic.split("\n"))
    return f"{HEADER}theorem {THEOREM_NAME} : {proposition} := by\n  {body}\n"


@dataclass(slots=True)
class Proposal:
    sources: list[str] = field(default_factory=list)  # best first; empty: nothing proposed
    reason: str = "none"
    seconds: dict[str, float] = field(default_factory=dict)
    sieved: bool = False


class FastFirstAttempt:
    def __init__(
        self,
        model: Any,
        *,
        sieve: Sieve | None = None,
        deadline_s: float | None = None,
        gate_model: Any = None,
        gate: bool = True,
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.model = model  # gate.ModelCall: (prompt, schema) -> dict
        self.sieve = sieve
        self.deadline_s = deadline_s
        # The fidelity check (two terse reviews, the second told to look for a difference): the
        # API's semantic review would otherwise be the first to see a mistranslated statement,
        # and a rejection there ends the job instead of handing over.  Off only for measurement.
        self.gate_model, self.gate = gate_model or model, gate
        self.observer = observer

    def propose(self, statement: str, *, formal_statement: str | None) -> Proposal:
        """Never raises.  A request that fixed its formal statement is left to the normal path."""
        t0 = time.monotonic()
        proposal = Proposal()
        try:
            self._propose(statement, formal_statement, t0, proposal)
        except Exception as error:  # noqa: BLE001 - a fast lane must never fail a request
            proposal.sources, proposal.reason = [], f"error:{type(error).__name__}"
        proposal.seconds["total"] = round(time.monotonic() - t0, 3)
        if self.observer is not None:
            with contextlib.suppress(Exception):
                self.observer({"reason": proposal.reason, "seconds": dict(proposal.seconds),
                               "sieved": proposal.sieved, "proposed": len(proposal.sources)})
        return proposal

    def _propose(
        self, statement: str, formal_statement: str | None, t0: float, proposal: Proposal
    ) -> None:
        if formal_statement is not None:
            proposal.reason = "formal_statement_given"
            return
        budget = self.deadline_s if self.deadline_s is not None else deadline_seconds()
        deadline = t0 + budget
        future: Future[fa.Merged] = Future()
        context = contextvars.copy_context()  # a late call still reports its usage

        def call() -> None:
            try:
                future.set_result(fa.merged_call(self.model, statement))
            except BaseException as error:  # noqa: BLE001
                future.set_exception(error)

        threading.Thread(target=context.run, args=(call,), daemon=True, name="fast-first").start()
        try:
            merged = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except TimeoutError:
            proposal.reason = "model_deadline"
            return
        proposal.seconds["model"] = round(time.monotonic() - t0, 3)
        if merged.kind != "prove" or not merged.formal or not merged.tactics:
            proposal.reason = f"not_a_proof_request:{merged.kind}"
            return
        try:
            proposition = check_formal_statement(merged.formal)
        except InstantiationRejected:
            proposal.reason = "grammar_rejected"
            return
        sources = [theorem_source(proposition, tactic) for tactic in merged.tactics]
        sources = [
            s for s in sources if not _UNFINISHED.search(s) and fa.acceptable_source(s)
        ]
        if not sources:
            proposal.reason = "no_acceptable_source"
            return
        gate_future = self._start_gate(statement, proposition, context) if self.gate else None
        if self.sieve is None:
            chosen, proposal.reason = sources[:1], "proposed_unchecked"
        else:
            portfolio = [theorem_source(proposition, tactic.text) for tactic in PORTFOLIO]
            portfolio = [s for s in portfolio if fa.acceptable_source(s)]
            pool = sources + portfolio
            started = time.monotonic()
            winners = self.sieve(pool, max(0.0, deadline - started))
            proposal.seconds["sieve"] = round(time.monotonic() - started, 3)
            proposal.sieved = True
            chosen = [pool[i] for i in winners if 0 <= i < len(pool)][:1]
            if not chosen:
                proposal.reason = "sieve_rejected_all"
                return
            proposal.reason = "proposed_sieved"
        if gate_future is not None:
            try:
                faithful, issue = gate_future.result(timeout=max(0.0, deadline - time.monotonic()))
            except TimeoutError:
                proposal.reason = "gate_deadline"
                return
            proposal.seconds["gate"] = round(time.monotonic() - t0, 3)
            if not faithful:
                proposal.reason = "gate_rejected"
                return
        proposal.sources = chosen

    def _start_gate(
        self, request: str, proposition: str, context: contextvars.Context
    ) -> Future[tuple[bool, str]]:
        """Both terse reviews at once; faithful only if both say so (a failed call is not)."""
        out: Future[tuple[bool, str]] = Future()
        results: list[tuple[bool, str]] = []
        lock = threading.Lock()

        def review(skeptical: bool) -> None:
            try:
                verdict = fa.terse_review(
                    self.gate_model, request, proposition, "prove", skeptical=skeptical
                )
            except BaseException:  # noqa: BLE001
                verdict = (False, "review_call_failed")
            with lock:
                results.append(verdict)
                if (len(results) == 2 or not verdict[0]) and not out.done():
                    out.set_result(
                        (all(r[0] for r in results) and len(results) == 2,
                         next((r[1] for r in results if not r[0]), ""))
                    )

        for skeptical in (False, True):
            threading.Thread(
                target=context.copy().run, args=(review, skeptical), daemon=True, name="fast-gate"
            ).start()
        return out

def resident_sieve(worker: Any) -> Sieve:
    """A sieve on a ``ResidentWorker``: every source is compiled in its own child at once."""

    def accepted(_: int, out: str) -> bool:
        lowered = out.lower()
        return "error" not in lowered and "sorry" not in lowered

    def sieve(sources: Sequence[str], timeout_s: float) -> Sequence[int]:
        body = [s[len("import Mathlib\n") :] for s in sources]
        done = worker.check_race(body, accepted, timeout_s=timeout_s)
        return [i for i, out in sorted(done.items()) if accepted(i, out)]

    return sieve
