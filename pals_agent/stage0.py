"""Optional stage 0: answer from Lean automation before the normal generation pipeline.

request -> (formal statement given, else ONE pair of independent formalisations) -> portfolio on
a warm Lean worker under a hard time budget -> on success AND gate pass, a template explanation;
otherwise ``fallthrough`` and the normal pipeline continues with nothing lost.

Release rules (the point of this module):
  * a formal statement that was written by a model is released only with the fidelity gate
    (two formalisations that agree in Lean, and a semantic review) passing in addition to Lean's
    proof; Lean success alone never releases it;
  * a statement given by a reviewed source (catalog card, grammar) needs the proof only;
  * no explanation template that would be dishonest is used (see ``portfolio_explanation``): the
    answer is then verified but needs a model-written explanation, reported as
    ``verified_needs_explanation`` and not released here.

Flag ``PALS_STAGE0_PORTFOLIO`` (default off).  No exception leaves ``run``.
"""

from __future__ import annotations

import concurrent.futures as futures
import contextvars
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Final

from pals_agent import automation_portfolio as ap
from pals_agent import fidelity_gate as gate
from pals_agent import general_recipe_lane as lane
from pals_agent import portfolio_explanation as expl
from pals_agent.recipe_instantiation import InstantiationRejected

SCHEMA_VERSION: Final = "pals.stage0-portfolio.v1"
BUDGET_GIVEN_S: Final = 6.0
BUDGET_FORMALISED_S: Final = 12.0


def stage0_enabled(environ: dict[str, str] | None = None) -> bool:
    value = (environ if environ is not None else os.environ).get("PALS_STAGE0_PORTFOLIO", "")
    return value.strip().lower() in {"on", "true", "1"}


@dataclass(slots=True)
class Stage0Result:
    outcome: str  # answered | verified_needs_explanation | fallthrough
    reason: str | None = None
    answer_text: str | None = None
    formal: str | None = None
    formal_source: str | None = None  # given | formalised
    route: str | None = None
    by: str | None = None
    lemma: str | None = None
    gate: gate.GateResult | None = None
    model_calls: int = 0
    seconds: dict[str, float] = field(default_factory=dict)

    def evidence(self) -> dict[str, Any]:
        digest = hashlib.sha256((self.formal or "").encode()).hexdigest()
        out: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "phase": "stage0_portfolio",
            "lean_route": "portfolio_stage0",
            "outcome": self.outcome,
            "formal_statement_sha256": digest,
            "formal_source": self.formal_source,
            "closed_by": self.by,
            "cited_lemma": self.lemma,
            "model_calls": self.model_calls,
            "seconds": self.seconds,
        }
        if self.gate is not None:
            out["fidelity_gate"] = {
                "passed": self.gate.passed,
                "agree": self.gate.agree,
                "reviewed": self.gate.reviewed,
                "reasons": self.gate.reasons,
                "numerals_signal": self.gate.numerals_signal,
                "structure": self.gate.structure,
                "triviality": self.gate.triviality,
                "roundtrip": self.gate.roundtrip,
            }
        return out


class Stage0:
    """Stage 0.  ``require_flags`` (default True) makes ``run`` inert unless BOTH
    ``PALS_STAGE0_PORTFOLIO`` and ``PALS_GENERAL_RECIPE_LANE`` are on; measurement scripts and
    tests pass ``require_flags=False``."""

    def __init__(
        self,
        worker: ap.WarmWorker,
        pool: list[lane.PoolRecipe],
        model: gate.ModelCall | None,
        *,
        require_flags: bool = True,
    ) -> None:
        self.worker, self.pool, self.model = worker, pool, model
        self.require_flags = require_flags

    # -- helpers -----------------------------------------------------------------------------
    def _lemma_info(self, solved: ap.SolveResult) -> expl.LemmaInfo | None:
        if not solved.lemma:
            return None
        try:
            output, _ = self.worker.check(expl.lemma_probe_source(solved.lemma), timeout_s=10.0)
        except (TimeoutError, ValueError):
            return expl.LemmaInfo(solved.lemma, call=solved.call or "")
        return expl.parse_lemma_probe(solved.lemma, output, solved.call or "")

    def _ensure_worker(self) -> None:
        if not self.worker.alive():
            self.worker.restart()
            self.worker.prewarm_search()

    def _agree(self, first: str, second: str, deadline: float) -> bool:
        text, _ = gate.equivalence_source(first, second)
        remaining = max(0.5, deadline - time.monotonic())
        try:
            output, _ = self.worker.check(text, timeout_s=min(20.0, remaining))
        except (TimeoutError, RuntimeError):
            return False
        return gate.equivalence_verdict(output)

    def _vacuous(self, formal: str, deadline: float) -> bool:
        """True when simple automation refutes the hypotheses (the theorem says nothing)."""
        probe = gate.vacuity_probe(formal)
        if probe is None:
            return False
        quick = tuple(t for t in ap.PORTFOLIO if t.name in {"omega", "decide", "simp", "norm_num"})
        try:
            solved = ap.solve_warm(
                probe,
                [],
                self.worker,
                portfolio=quick,
                deadline=min(deadline, time.monotonic() + 3.0),
            )
        except (TimeoutError, RuntimeError, InstantiationRejected):
            return False
        return solved.outcome == "answered"

    # -- entry point ---------------------------------------------------------------------------
    def run(
        self,
        request: str,
        language: str,
        *,
        formal: str | None = None,
        budget_s: float | None = None,
    ) -> Stage0Result:
        t0 = time.monotonic()
        if self.require_flags and not (stage0_enabled() and lane.lane_enabled()):
            return Stage0Result("fallthrough", "flag_off")  # inert: no worker, no model, no Lean
        try:
            return self._run(request, language, formal, t0, budget_s)
        except Exception as error:  # noqa: BLE001 - stage 0 must never fail a request
            return Stage0Result(
                "fallthrough",
                f"stage0_error:{type(error).__name__}",
                seconds={"total": round(time.monotonic() - t0, 3)},
            )

    def _run(
        self, request: str, language: str, formal: str | None, t0: float, budget: float | None
    ) -> Stage0Result:
        given = formal is not None  # a catalog card's statement: reviewed, not model-written
        deadline = t0 + (
            budget if budget is not None else BUDGET_GIVEN_S if given else BUDGET_FORMALISED_S
        )
        result = Stage0Result("fallthrough", formal_source="given" if given else "formalised")
        calls = 0
        second_f: futures.Future[str] | None = None
        review_f: futures.Future[tuple[bool, str]] | None = None
        trip_f: futures.Future[tuple[bool, str]] | None = None
        pool = futures.ThreadPoolExecutor(max_workers=4)

        def submit(fn: Any, *args: Any) -> Any:
            return pool.submit(contextvars.copy_context().run, fn, *args)

        try:
            if not given:
                if self.model is None:
                    result.reason = "no_model_for_formalisation"
                    return result
                t1 = time.monotonic()
                first_f = submit(gate.formalise, self.model, request, 0)
                second_f = submit(gate.formalise, self.model, request, 1)
                formal = first_f.result(timeout=max(1.0, deadline - time.monotonic()))
                calls += 2
                result.seconds["formalise"] = round(time.monotonic() - t1, 3)
                if not formal:
                    result.reason = "formalisation_empty"
                    return result
                review_f = submit(gate.review, self.model, request, formal)
                trip_f = submit(gate.roundtrip, self.model, request, formal, language)
                calls += 3  # review, back-translation, comparison
            assert formal is not None
            result.formal = formal
            try:
                ap.check_formal_statement(formal, allow_header=given)
            except InstantiationRejected:
                result.reason = "statement_not_plain"
                return result
            self._ensure_worker()
            t2 = time.monotonic()
            solved = ap.solve_warm(
                formal,
                self.pool if given else [],
                self.worker,
                deadline=deadline,
                allow_header=given,
            )
            result.seconds["portfolio"] = round(time.monotonic() - t2, 3)
            result.route, result.by, result.lemma = solved.route, solved.by, solved.lemma
            if solved.outcome != "answered":
                result.reason = solved.code or "not_proved"
                return result
            if not given:
                self._gate(result, request, formal, second_f, review_f, trip_f, deadline)
                if result.gate is None or not result.gate.passed:
                    result.reason = "fidelity_gate_failed"
                    return result
            info = self._lemma_info(solved) if solved.by == "exact?" else None
            if solved.route == "recipe":
                result.outcome, result.reason = "verified_needs_explanation", "recipe_answer_text"
            else:
                text = expl.render(
                    language, formal, solved.by or "", info, unverified_formalisation=not given
                )
                if text is None:
                    result.outcome = "verified_needs_explanation"
                    result.reason = "no_honest_template"
                else:
                    result.outcome, result.answer_text, result.reason = "answered", text, None
            return result
        finally:
            result.model_calls = calls
            result.seconds["total"] = round(time.monotonic() - t0, 3)
            pool.shutdown(wait=False, cancel_futures=True)

    def _gate(
        self,
        result: Stage0Result,
        request: str,
        formal: str,
        second_f: futures.Future[str] | None,
        review_f: futures.Future[tuple[bool, str]] | None,
        trip_f: futures.Future[tuple[bool, str]] | None,
        deadline: float,
    ) -> None:
        g = gate.GateResult(False)
        result.gate = g
        t3 = time.monotonic()

        def wait(future: Any, default: Any) -> Any:
            if future is None:
                return default
            try:
                return future.result(timeout=max(0.5, deadline - time.monotonic()))
            except Exception:  # noqa: BLE001 - a missing check is a failed check
                return default

        second = wait(second_f, None)
        g.numerals_signal = gate.numerals_signal(request, formal)
        g.agree = bool(second) and self._agree(formal, second, deadline)
        g.structure = gate.structure_check(request, formal)
        g.triviality = gate.triviality_check(formal)
        if not g.triviality and self._vacuous(formal, deadline):
            g.triviality.append("hypotheses_vacuous")
        g.reviewed, g.review_issue = wait(review_f, (False, "review_unavailable"))
        g.roundtrip, g.roundtrip_issue = wait(trip_f, (False, "roundtrip_unavailable"))
        if not g.agree:
            g.reasons.append("formalisations_disagree")
        if g.structure:
            g.reasons.append("structure_mismatch")
        if g.triviality:
            g.reasons.append("trivial_statement")
        if not g.reviewed:
            g.reasons.append(
                "review_rejected"
                if g.review_issue != "review_unavailable"
                else "review_unavailable"
            )
        if not g.roundtrip:
            g.reasons.append(
                "roundtrip_mismatch"
                if g.roundtrip_issue != "roundtrip_unavailable"
                else "roundtrip_unavailable"
            )
        g.passed = not g.reasons
        g.seconds["gate"] = round(time.monotonic() - t3, 3)
        result.seconds["gate_extra"] = g.seconds["gate"]
