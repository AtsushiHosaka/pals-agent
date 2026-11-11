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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Final

from pals_agent import automation_portfolio as ap
from pals_agent import fidelity_gate as gate
from pals_agent import general_recipe_lane as lane
from pals_agent import portfolio_explanation as expl
from pals_agent.recipe_instantiation import InstantiationRejected
from pals_agent.statement_normalise import equivalence_source, hoist_lets

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
    formal_proved: str | None = None  # the statement Lean proved (¬P for a `no` answer)
    kind: str | None = None  # prove | decide | compute | explain
    answer: str | None = None  # yes | no for a question
    expression: str | None = None
    value: str | None = None
    normalised: str | None = None  # safe normalisation applied (let_hoisted)
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
            "kind": self.kind,
            "answer": self.answer,
            "value": self.value,
            "normalised": self.normalised,
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
        roundtrip_mode: str = "two_calls",
        bound_recipes: bool = False,
    ) -> None:
        self.worker, self.pool, self.model = worker, pool, model
        self.require_flags = require_flags
        self.bound_recipes = bound_recipes  # many-alternative Recipe closers (off: costly)
        self.roundtrip_mode = roundtrip_mode  # "two_calls" (blind paraphrase) | "single"

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
        pool = futures.ThreadPoolExecutor(max_workers=5)

        def submit(fn: Any, *args: Any) -> Any:
            return pool.submit(contextvars.copy_context().run, fn, *args)

        try:
            if given:
                assert formal is not None
                return self._prove_given(result, language, formal, deadline)
            if self.model is None:
                result.reason = "no_model_for_formalisation"
                return result
            t1 = time.monotonic()
            first_f = submit(gate.formalise_typed, self.model, request, 0)
            second_f = submit(gate.formalise_typed, self.model, request, 1)
            first = first_f.result(timeout=max(1.0, deadline - time.monotonic()))
            calls += 2
            result.seconds["formalise"] = round(time.monotonic() - t1, 3)
            result.kind = first.kind
            if first.kind == "explain" or not (first.formal or first.expression):
                result.reason = (
                    "explain_request" if first.kind == "explain" else "formalisation_empty"
                )
                return result
            self._ensure_worker()
            statement = self._statement(result, first, deadline)
            if statement is None:
                return result
            result.formal = statement
            try:
                ap.check_formal_statement(statement)
            except InstantiationRejected:
                result.reason = "statement_not_plain"
                return result
            checks = [
                submit(gate.review, self.model, request, statement, first.kind),
                submit(self._roundtrip, request, statement, language, first.kind),
            ]
            calls += 1 + (1 if self.roundtrip_mode == "single" else 2)
            t2 = time.monotonic()
            proved = self._prove(result, first.kind, statement, deadline)
            result.seconds["portfolio"] = round(time.monotonic() - t2, 3)
            if proved is None:
                return result
            self._gate(result, request, first, second_f, checks, deadline)
            if result.gate is None or not result.gate.passed:
                result.reason = "fidelity_gate_failed"
                return result
            self._explain(result, language, proved, unverified=True)
            return result
        finally:
            result.model_calls = calls
            result.seconds["total"] = round(time.monotonic() - t0, 3)
            pool.shutdown(wait=False, cancel_futures=True)

    # -- routes ------------------------------------------------------------------------------
    def _roundtrip(
        self, request: str, statement: str, language: str, intent: str
    ) -> tuple[bool, str]:
        assert self.model is not None
        fn = gate.roundtrip_single if self.roundtrip_mode == "single" else gate.roundtrip
        return fn(self.model, request, statement, language, intent)

    def _statement(
        self, result: Stage0Result, first: gate.TypedFormal, deadline: float
    ) -> str | None:
        """The statement the gate and the proof are about (None: no statement, fall through)."""
        if first.kind != "compute":
            return first.formal
        try:
            value = ap.derive_value(self.worker, first.expression, first.type, deadline=deadline)
            if value is None:
                result.reason = "value_not_derived"
                return None
            result.expression, result.value = first.expression, value
            return ap.closed_value_statement(first.expression, value, first.type)
        except InstantiationRejected:
            result.reason = "statement_not_plain"
            return None

    def _prove(
        self, result: Stage0Result, kind: str, statement: str, deadline: float
    ) -> ap.SolveResult | None:
        """Prove the statement; for a question, attempt P and not-P, exactly one may be proved."""
        solved = ap.solve_warm(statement, [], self.worker, deadline=deadline)
        if kind == "decide":
            negated = ap.solve_warm(
                f"¬ ({statement})",
                [],
                self.worker,
                deadline=min(deadline, time.monotonic() + 4.0),
                portfolio=tuple(t for t in ap.PORTFOLIO if t.name != "exact?"),
            )
            if solved.outcome == "answered" and negated.outcome == "answered":
                result.reason = "both_proved"  # impossible in a consistent theory: never answer
                return None
            if negated.outcome == "answered":
                result.answer = "no"
                result.formal_proved = f"¬ ({statement})"
                solved = negated
            elif solved.outcome == "answered":
                result.answer = "yes"
                result.formal_proved = statement
        else:
            result.formal_proved = statement
        result.route, result.by, result.lemma = solved.route, solved.by, solved.lemma
        if solved.outcome != "answered":
            result.reason = solved.code or "not_proved"
            return None
        return solved

    def _prove_given(
        self, result: Stage0Result, language: str, formal: str, deadline: float
    ) -> Stage0Result:
        self._ensure_worker()
        formal = self._hoist(result, formal)
        try:
            ap.check_formal_statement(formal, allow_header=True)
        except InstantiationRejected:
            result.reason = "statement_not_plain"
            return result
        t2 = time.monotonic()
        solved = ap.solve_warm(
            formal,
            self.pool,
            self.worker,
            deadline=deadline,
            allow_header=True,
            bound_stage=self.bound_recipes,
        )
        result.formal = formal
        result.seconds["portfolio"] = round(time.monotonic() - t2, 3)
        result.route, result.by, result.lemma = solved.route, solved.by, solved.lemma
        if solved.outcome != "answered":
            result.reason = solved.code or "not_proved"
            return result
        result.formal_proved = formal
        self._explain(result, language, solved, unverified=False)
        return result

    def _hoist(self, result: Stage0Result, formal: str) -> str:
        """Catalog statements with a ``let`` chain: hoist by substitution, check in Lean."""
        try:
            closed = ap.closed_statement(ap.split_preamble(formal)[1])
        except InstantiationRejected:
            return formal
        if not re.search(r"(?<![\w'.])let\s", closed):
            return formal
        hoisted = hoist_lets(closed)
        if hoisted is None:
            return formal
        try:
            output, _ = self.worker.check(equivalence_source(closed, hoisted), timeout_s=20.0)
        except (TimeoutError, RuntimeError):
            return formal
        if lane._ERROR_LINE.search(output) or "_pals_hoist' depends on axioms" not in output:
            return formal
        if "sorryAx" in output:
            return formal
        result.normalised = "let_hoisted"
        preamble = ap.split_preamble(formal)[0]
        return (preamble + "\n" if preamble else "") + hoisted

    def _explain(
        self, result: Stage0Result, language: str, solved: ap.SolveResult, *, unverified: bool
    ) -> None:
        if solved.route == "recipe":
            result.outcome, result.reason = "verified_needs_explanation", "recipe_answer_text"
            return
        proved = result.formal_proved or result.formal or ""
        info = self._lemma_info(solved) if solved.by == "exact?" else None
        if result.kind == "compute" and result.expression and result.value:
            text: str | None = expl.render_compute(
                language, result.expression, result.value, unverified_formalisation=unverified
            )
        elif result.kind == "decide" and result.answer:
            text = expl.render_decision(
                language,
                result.answer == "yes",
                proved,
                solved.by or "",
                info,
                unverified_formalisation=unverified,
            )
        else:
            text = expl.render(
                language, proved, solved.by or "", info, unverified_formalisation=unverified
            )
        if text is None:
            result.outcome, result.reason = "verified_needs_explanation", "no_honest_template"
        else:
            result.outcome, result.answer_text, result.reason = "answered", text, None

    def _gate(
        self,
        result: Stage0Result,
        request: str,
        first: gate.TypedFormal,
        second_f: futures.Future[gate.TypedFormal] | None,
        checks: list[futures.Future[tuple[bool, str]]],
        deadline: float,
    ) -> None:
        """Every check must have RETURNED and approved; a check that has not returned fails."""
        g = gate.GateResult(False)
        result.gate = g
        t3 = time.monotonic()
        statement = result.formal or ""

        def wait(future: Any, default: Any) -> Any:
            if future is None:
                return default
            try:
                return future.result(timeout=max(0.5, deadline - time.monotonic()))
            except Exception:  # noqa: BLE001 - a missing check is a failed check
                return default

        second = wait(second_f, None)
        g.numerals_signal = gate.numerals_signal(request, statement)
        g.agree = self._agrees(first, second, result.value, deadline)
        g.structure = gate.structure_check(request, statement)
        g.triviality = gate.triviality_check(statement)
        if first.kind != "compute" and not g.triviality and self._vacuous(statement, deadline):
            g.triviality.append("hypotheses_vacuous")
        g.reviewed, g.review_issue = wait(checks[0], (False, "review_unavailable"))
        g.roundtrip, g.roundtrip_issue = wait(checks[1], (False, "roundtrip_unavailable"))
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

    def _agrees(
        self,
        first: gate.TypedFormal,
        second: gate.TypedFormal | None,
        own_value: str | None,
        deadline: float,
    ) -> bool:
        if second is None or second.kind != first.kind:
            return False
        if first.kind == "compute":
            try:
                other = ap.derive_value(
                    self.worker, second.expression, second.type, deadline=deadline
                )
            except InstantiationRejected:
                return False
            return (
                other is not None
                and "".join(other.split()) == "".join((own_value or "").split())
                and second.type == first.type
            )
        return bool(second.formal) and self._agree(first.formal, second.formal, deadline)
