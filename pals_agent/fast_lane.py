"""Fast lane: close a formal statement with automation, in parallel, on the resident Lean worker.

``statement -> N tactic attempts, each in its own forked child at once -> the first accepted one ->
the ordinary ``LeanVerifier.verify`` (policy, compile, trusted audit) of one clean theorem``.

Two kinds of result are kept apart on purpose:

* a *speculative* acceptance: a race child compiled ``theorem T : P := by <tactic>`` with exit code
  0, no error and no ``sorry``.  It only chooses what to verify; it is never shown as verified.
* the *verified* result: the existing verifier accepted the same theorem, including its trusted
  audit (kernel replay, axiom allow-list, statement binding).  Only this sets ``verified``.

Nothing here weakens a check: a statement goes through the same layer-0 grammar as the stage-0
lane, the final source goes through the same source policy and audit as any request, and a
failure of the race or of the resident worker is a miss (the caller continues with its normal
path), never an answer.  Default off; nothing imports this module on the request path yet.
"""

from __future__ import annotations

import dataclasses
import secrets
import threading
import time
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pals_agent.automation_portfolio import PORTFOLIO, Tactic, check_formal_statement
from pals_agent.lean import LeanVerifier
from pals_agent.lean_verifier.resident import ResidentBusy, ResidentLean, ResidentUnavailable
from pals_agent.recipe_instantiation import InstantiationRejected

THEOREM_NAME: Final = "pals_fast_lane_theorem"
HEADER: Final = "import Mathlib\n\n"


@dataclass(slots=True)
class Attempt:
    name: str
    accepted: bool = False
    verdict: str = "not_run"  # accepted | rejected | timeout | interrupted | not_run
    at_s: float | None = None  # seconds since the race started when it finished


@dataclass(slots=True)
class FastLaneResult:
    outcome: str  # "verified" | "miss"
    reason: str | None = None
    proposition: str | None = None
    tactic: str | None = None  # name of the tactic of the verified theorem
    source: str | None = None  # the verified Lean source (one theorem)
    speculative_at_s: float | None = None  # first accepted race child
    verified_at_s: float | None = None  # existing verifier accepted (audit included)
    attempts: list[Attempt] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)


def candidate_source(proposition: str, tactic: Tactic, name: str = THEOREM_NAME) -> str:
    """One closed theorem; ``maxHeartbeats`` is the tactic's own deterministic time limit."""
    return (
        f"{HEADER}set_option maxHeartbeats {tactic.heartbeats} in\n"
        f"theorem {name} : {proposition} := by\n  {tactic.text}\n"
    )


def speculative_accept(returncode: int, output: str) -> bool:
    """Exit 0 and no sign of an error or an unfinished proof in the compiler output."""
    lowered = output.lower()
    return returncode == 0 and "error" not in lowered and "sorry" not in lowered


class FastLane:
    def __init__(
        self,
        resident: ResidentLean,
        verifier: LeanVerifier,
        *,
        portfolio: Sequence[Tactic] = PORTFOLIO,
        race_budget_s: float = 20.0,
        verify_budget_s: float = 60.0,
    ) -> None:
        if verifier.resident is not resident:
            raise ValueError("the verifier must use the same resident worker")
        self.resident = resident
        # the final check gets the lane's own budget, not the verifier's (default 300 s)
        self.verifier = dataclasses.replace(verifier, timeout_seconds=verify_budget_s)
        self.portfolio = tuple(portfolio)
        self.race_budget_s = race_budget_s
        self.verify_budget_s = verify_budget_s

    def prove(self, statement: str, *, allow_header: bool = False) -> FastLaneResult:
        started = time.monotonic()
        try:
            proposition = check_formal_statement(statement, allow_header=allow_header)
        except InstantiationRejected:
            return FastLaneResult("miss", "statement_not_plain")
        result = FastLaneResult("miss", "no_attempt_succeeded", proposition=proposition)
        winners = self._race(proposition, result, started)
        result.seconds["race"] = round(time.monotonic() - started, 3)
        for tactic in winners:
            if time.monotonic() - started > self.race_budget_s + self.verify_budget_s:
                result.reason = "verify_budget_exhausted"
                break
            verify_started = time.monotonic()
            source = candidate_source(proposition, tactic)
            verified = self.verifier.verify(source)
            result.seconds["verify"] = round(time.monotonic() - verify_started, 3)
            if verified.success:
                result.outcome, result.reason = "verified", None
                result.tactic, result.source = tactic.name, source
                result.verified_at_s = round(time.monotonic() - started, 3)
                break
            result.reason = "verifier_rejected_speculative_winner"
        result.seconds["total"] = round(time.monotonic() - started, 3)
        return result

    def _race(self, proposition: str, result: FastLaneResult, started: float) -> list[Tactic]:
        """Compile every tactic attempt in its own child; return accepted tactics, fastest first."""
        cancel = threading.Event()
        attempts = {t.name: Attempt(t.name) for t in self.portfolio}
        result.attempts = list(attempts.values())
        accepted: list[Tactic] = []
        slots = self.resident.config.max_children
        with TemporaryDirectory(prefix="pals-fast-", dir=self.verifier.scratch_dir) as directory:
            work = Path(directory)

            def attempt(tactic: Tactic) -> tuple[Tactic, str]:
                if cancel.is_set():
                    return tactic, "not_run"
                path = work / f"{secrets.token_hex(6)}.lean"
                path.write_text(candidate_source(proposition, tactic), encoding="utf-8")
                try:
                    outcome = self.resident.compile(
                        path, workdir=work, olean=None, cancel=cancel,
                        timeout_s=max(0.5, self.race_budget_s - (time.monotonic() - started)),
                    )
                except (ResidentBusy, ResidentUnavailable):
                    return tactic, "interrupted"
                if outcome.timed_out:
                    return tactic, "timeout"
                if outcome.aborted or outcome.unsupported or outcome.output_limited:
                    return tactic, "interrupted"
                ok = speculative_accept(outcome.returncode, outcome.stdout)
                return tactic, "accepted" if ok else "rejected"

            with ThreadPoolExecutor(max_workers=slots) as pool:
                pending = {pool.submit(attempt, t) for t in self.portfolio}
                while pending:
                    done, pending = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in done:
                        tactic, verdict = future.result()
                        record = attempts[tactic.name]
                        record.verdict, record.at_s = verdict, round(time.monotonic() - started, 3)
                        if verdict == "accepted":
                            record.accepted = True
                            accepted.append(tactic)
                            if result.speculative_at_s is None:
                                result.speculative_at_s = record.at_s
                            cancel.set()  # the rest are not needed; their children are killed
                    if time.monotonic() - started > self.race_budget_s:
                        cancel.set()
        return accepted
