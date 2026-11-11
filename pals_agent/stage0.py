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
import contextlib
import contextvars
import hashlib
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from pals_agent import automation_portfolio as ap
from pals_agent import fidelity_gate as gate
from pals_agent import general_recipe_lane as lane
from pals_agent import portfolio_explanation as expl
from pals_agent import sandbox
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


@dataclass(slots=True)
class _Req:
    """The workers ONE request uses.  Per-request state lives here, never on the Stage0."""

    search: ap.WarmWorker
    verify: ap.WarmWorker


MAX_CONCURRENT_DEFAULT: Final = 2


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
        worker_factory: Callable[[], ap.WarmWorker] | None = None,
        exact_in_fresh_search: bool = False,
        prefetch: bool = True,
        max_concurrent: int = MAX_CONCURRENT_DEFAULT,
    ) -> None:
        sandbox.require_containment()  # fail closed: no backend, no stage 0
        self.worker, self.pool, self.model = worker, pool, model
        # With a factory, every model- or learner-written statement gets TWO fresh sandboxed
        # workers started while the formalisation is still running: a search worker and a clean
        # verifier that re-checks the answer.  Without one (tests), both are `worker`.
        self.worker_factory = worker_factory
        self.exact_in_fresh_search = exact_in_fresh_search
        # Start-up (the Mathlib import) is paid off the request path: the next request's pair is
        # started right after a request ends.  Each pair serves exactly ONE request, then dies.
        self.prefetch = prefetch and worker_factory is not None
        self._ready: list[Any] = []
        self._lock = threading.Lock()  # guards `_ready`
        self._starter = futures.ThreadPoolExecutor(max_workers=2)
        # Admission: a model-written request holds TWO fresh Mathlib processes (7-9 GiB each) and
        # one more pair may be prefetched, so processes <= 2 * max_concurrent + 2 (+1 shared).
        self._admission = threading.BoundedSemaphore(max(1, max_concurrent))
        self.require_flags = require_flags
        self.bound_recipes = bound_recipes  # many-alternative Recipe closers (off: costly)
        self.roundtrip_mode = roundtrip_mode  # "two_calls" (blind paraphrase) | "single"

    # -- helpers -----------------------------------------------------------------------------
    def _lemma_info(self, req: _Req, solved: ap.SolveResult) -> expl.LemmaInfo | None:
        if not solved.lemma:
            return None
        try:
            output, _ = req.verify.check(expl.lemma_probe_source(solved.lemma), timeout_s=10.0)
        except (TimeoutError, ValueError):
            return expl.LemmaInfo(solved.lemma, call=solved.call or "")
        return expl.parse_lemma_probe(solved.lemma, output, solved.call or "")

    def _ensure_worker(self) -> None:
        with self._lock:  # concurrent catalog requests must not both restart the shared worker
            if not self.worker.alive():
                self.worker.restart()
                self.worker.prewarm_search()

    def _portfolio(self) -> tuple[ap.Tactic, ...]:
        """``exact?`` needs a ~12-15 s index build: not in a fresh per-request worker by default."""
        if self.worker_factory is not None and not self.exact_in_fresh_search:
            return tuple(t for t in ap.PORTFOLIO if t.name != "exact?")
        return ap.PORTFOLIO

    def _take_pair(self, submit: Any) -> list[Any]:
        with self._lock:
            pair, self._ready = self._ready, []
        if pair:
            return pair
        return [submit(self._spawn_search), submit(self._spawn_verify)]

    def close(self) -> None:
        """Close any prefetched, unused workers."""
        with self._lock:
            pair, self._ready = self._ready, []
        self._release_futures(pair)
        self._starter.shutdown(wait=True)

    def _spawn_search(self) -> ap.WarmWorker:
        assert self.worker_factory is not None
        search = self.worker_factory()
        if self.exact_in_fresh_search:
            search.prewarm_search()
        return search

    def _spawn_verify(self) -> ap.WarmWorker:
        assert self.worker_factory is not None
        verifier = self.worker_factory()
        verifier.prime_checker()  # off the request path
        return verifier

    def _refused_by_lean(self, req: _Req, *terms: str | None) -> str | None:
        """Parse-only allow-list check of every model/user-written term, in the CLEAN worker.

        Nothing the model wrote is elaborated anywhere before this returns True; the Python
        grammar (layer 0) has already run.  Returns a refusal reason, or None when all pass.
        """
        for term in terms:
            if not term:
                continue
            try:  # layer 0 FIRST (length and token limits, characters): Lean never sees more
                text = ap.check_formal_statement(term)
            except InstantiationRejected:
                return "statement_not_plain"
            try:
                ok, reason = req.verify.check_statement(" ".join(text.split()))
            except (TimeoutError, RuntimeError, ValueError):
                return "lean_check_unavailable"
            if not ok:
                return f"statement_refused_by_lean_check: {reason}"[:160]
        return None

    def _agree(self, req: _Req, first: str, second: str, deadline: float) -> bool:
        text, _ = gate.equivalence_source(first, second)
        remaining = max(0.5, deadline - time.monotonic())
        try:
            output, _ = req.search.check(text, timeout_s=min(20.0, remaining))
        except (TimeoutError, RuntimeError):
            return False
        return gate.equivalence_verdict(output)

    def _vacuous(self, req: _Req, formal: str, deadline: float) -> bool:
        """True when simple automation refutes the hypotheses (the theorem says nothing)."""
        probe = gate.vacuity_probe(formal)
        if probe is None:
            return False
        quick = tuple(t for t in ap.PORTFOLIO if t.name in {"omega", "decide", "simp", "norm_num"})
        try:
            solved = ap.solve_warm(
                probe,
                [],
                req.search,
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
        spawned: list[Any] = []
        admitted = False
        pool = futures.ThreadPoolExecutor(max_workers=7)

        def submit(fn: Any, *args: Any) -> Any:
            return pool.submit(contextvars.copy_context().run, fn, *args)

        try:
            if given:
                assert formal is not None
                return self._prove_given(result, language, formal, deadline)
            if self.model is None:
                result.reason = "no_model_for_formalisation"
                return result
            if self.worker_factory is None:  # never the shared persistent worker for model text
                result.reason = "no_fresh_worker_factory"
                return result
            if not self._admission.acquire(blocking=False):
                result.reason = "busy"  # stage 0 never queues: the normal pipeline continues
                return result
            admitted = True
            t1 = time.monotonic()
            spawned.extend(self._take_pair(submit))  # concurrent with the formalisation call
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
            try:
                req = _Req(spawned[0].result(timeout=180.0), spawned[1].result(timeout=180.0))
            except Exception:  # noqa: BLE001
                result.reason = "worker_unavailable"
                return result
            refused = self._refused_by_lean(req, first.formal, first.expression)
            if refused is not None:
                result.reason = refused
                return result
            statement = self._statement(req, result, first, deadline)
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
            proved = self._prove(req, result, first.kind, statement, deadline)
            result.seconds["portfolio"] = round(time.monotonic() - t2, 3)
            if proved is None:
                return result
            if not self._recheck(req, result, proved):
                return result
            self._gate(req, result, request, first, second_f, checks, deadline)
            if result.gate is None or not result.gate.passed:
                result.reason = "fidelity_gate_failed"
                return result
            self._explain(result, language, proved, unverified=True, req=req)
            return result
        finally:
            self._release_fresh(spawned)
            if admitted:
                self._admission.release()
            result.model_calls = calls
            result.seconds["total"] = round(time.monotonic() - t0, 3)
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _close(worker: ap.WarmWorker) -> None:
        try:
            worker.close()
        except Exception:  # noqa: BLE001 - killing is best effort
            with contextlib.suppress(Exception):
                sandbox.kill_group(worker.proc)
            with contextlib.suppress(Exception):
                worker._dir.cleanup()  # the scratch directory goes with the process

    def _release_fresh(self, spawned: list[Any]) -> None:
        """Close every per-request worker, including ones whose start-up is still running."""
        self._release_futures(spawned)
        if self.prefetch:
            with self._lock:
                if not self._ready:
                    self._ready = [
                        self._starter.submit(self._spawn_search),
                        self._starter.submit(self._spawn_verify),
                    ]

    def _release_futures(self, spawned: list[Any]) -> None:
        for future in spawned:
            if future.cancel():
                continue
            if future.done():
                if not future.exception():
                    self._close(future.result())
            else:  # still starting: close it when it arrives
                future.add_done_callback(
                    lambda f: self._close(f.result()) if not f.exception() else None
                )

    def _recheck(self, req: _Req, result: Stage0Result, solved: ap.SolveResult) -> bool:
        """Re-prove the accepted answer in the clean verifier worker; the verdict is THIS one."""
        statement = result.formal_proved or ""
        if solved.by == "exact?":  # the search worker's text: both layers before the verifier
            try:
                tactic = ap.replay_tactic(solved) or ""
                call = tactic.rsplit("exact ", 1)[-1]
            except InstantiationRejected:
                result.reason, result.outcome = "recheck_failed:exact_call_not_plain", "fallthrough"
                return False
            refused = self._refused_by_lean(req, call)
            if refused is not None:
                result.reason, result.outcome = f"recheck_failed:{refused}", "fallthrough"
                return False
        ok, reason = ap.recheck(req.verify, statement, solved)
        if not ok:
            result.reason = f"recheck_failed:{reason}"
            result.outcome = "fallthrough"
            return False
        return True

    # -- routes ------------------------------------------------------------------------------
    def _roundtrip(
        self, request: str, statement: str, language: str, intent: str
    ) -> tuple[bool, str]:
        assert self.model is not None
        fn = gate.roundtrip_single if self.roundtrip_mode == "single" else gate.roundtrip
        return fn(self.model, request, statement, language, intent)

    def _statement(
        self, req: _Req, result: Stage0Result, first: gate.TypedFormal, deadline: float
    ) -> str | None:
        """The statement the gate and the proof are about (None: no statement, fall through)."""
        if first.kind != "compute":
            return first.formal
        try:
            value = ap.derive_value(req.search, first.expression, first.type, deadline=deadline)
            if value is None:
                result.reason = "value_not_derived"
                return None
            result.expression, result.value = first.expression, value
            return ap.closed_value_statement(first.expression, value, first.type)
        except InstantiationRejected:
            result.reason = "statement_not_plain"
            return None

    def _prove(
        self, req: _Req, result: Stage0Result, kind: str, statement: str, deadline: float
    ) -> ap.SolveResult | None:
        """Prove the statement; for a question, attempt P and not-P, exactly one may be proved."""
        solved = ap.solve_warm(
            statement, [], req.search, deadline=deadline, portfolio=self._portfolio()
        )
        if kind == "decide":
            negated = ap.solve_warm(
                f"¬ ({statement})",
                [],
                req.search,
                deadline=min(deadline, time.monotonic() + 4.0),
                portfolio=tuple(t for t in self._portfolio() if t.name != "exact?"),
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
        self,
        result: Stage0Result,
        language: str,
        solved: ap.SolveResult,
        *,
        unverified: bool,
        req: _Req | None = None,
    ) -> None:
        req = req or _Req(self.worker, self.worker)  # catalog statements: the shared worker
        if solved.route == "recipe":
            result.outcome, result.reason = "verified_needs_explanation", "recipe_answer_text"
            return
        proved = result.formal_proved or result.formal or ""
        info = self._lemma_info(req, solved) if solved.by == "exact?" else None
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
        req: _Req,
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
        if second is not None and self._refused_by_lean(req, second.formal, second.expression):
            second = None  # the second formalisation is model text too: refused, so no agreement
        g.numerals_signal = gate.numerals_signal(request, statement)
        g.agree = self._agrees(req, first, second, result.value, deadline)
        g.structure = gate.structure_check(request, statement)
        g.triviality = gate.triviality_check(statement)
        if first.kind != "compute" and not g.triviality and self._vacuous(req, statement, deadline):
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
        req: _Req,
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
                    req.search, second.expression, second.type, deadline=deadline
                )
            except InstantiationRejected:
                return False
            return (
                other is not None
                and "".join(other.split()) == "".join((own_value or "").split())
                and second.type == first.type
            )
        return bool(second.formal) and self._agree(req, first.formal, second.formal, deadline)
