"""The T2 switches inside ProofPipeline with scripted generators and verifiers (no model/Lean)."""

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from pals_agent import t2_lane
from pals_agent.artifacts import FileArtifactStore
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import ProofPipeline
from pals_agent.usage import _reporter, usage_scope

JOB = "job-1"
STATEMENT = "For every natural number n, n + 0 = n."
GOOD = "import Mathlib\n\ntheorem add_zero_nat (n : Nat) : n + 0 = n := by\n  simp\n"
BAD = "import Mathlib\n\ntheorem add_zero_nat (n : Nat) : n + 0 = n := by\n  nlinarith [n]\n"
SKETCH = (
    "import Mathlib\n\ntheorem add_zero_nat (n : Nat) : n + 0 = n := by\n  have h : n = n := by\n"
    "    sorry\n  simp\n"
)


def _result(ok: bool, message: str = "linarith failed\n⊢ n + 0 = n") -> VerificationResult:
    diagnostics = (
        []
        if ok
        else [Diagnostic(severity="error", code="lean.error", line=4, column=2, message=message)]
    )
    return VerificationResult(
        success=ok, diagnostics=diagnostics, stdout="", stderr="", elapsed_ms=1
    )


class ScriptedVerifier:
    def __init__(self, accept: set[str], delay: float = 0.0) -> None:
        self.accept = accept
        self.delay = delay
        self.compiled: list[str] = []
        self.lock = threading.Lock()

    def verify(self, lean_code: str) -> VerificationResult:
        time.sleep(self.delay)
        with self.lock:
            self.compiled.append(lean_code)
        return _result(lean_code in self.accept)

    def verify_sketch(self, lean_code: str) -> VerificationResult:
        return _result(True)


def _spend(tokens: int) -> None:
    reporter = _reporter.get()
    if reporter is not None:
        reporter({"input_tokens": tokens, "output_tokens": 1, "model": "m"})


class Generator:
    """Staged generator; ``proofs`` are returned in call order (each call may sleep first)."""

    model = "m"
    prove_model = "m"

    def __init__(
        self,
        proofs: list[str],
        patches: list[str | None] | None = None,
        proof_delays: list[float] | None = None,
    ) -> None:
        self.proofs = list(proofs)
        self.proof_delays = list(proof_delays or [])
        self.patches = list(patches or [])
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def _next_proof(self) -> tuple[str, float]:
        with self.lock:
            code = self.proofs.pop(0)
            delay = self.proof_delays.pop(0) if self.proof_delays else 0.0
        return code, delay

    def generate_draft(self, request: ProofRequest, feedback: GenerationFeedback | None = None):
        self.calls.append("draft")
        _spend(1)
        return GeneratedDraft(text="Use simp.", model="m", raw_model_output="Use simp.")

    def generate_sketch(self, request, draft, feedback=None):
        self.calls.append("sketch")
        return GeneratedSketch(SKETCH, "m", SKETCH, has_gaps=True)

    def generate_proof(self, request, draft, sketch, feedback=None):
        self.calls.append("prove")
        code, delay = self._next_proof()
        time.sleep(delay)
        _spend(10)
        return GeneratedProof(
            lean_code=code, model="m", raw_model_output=code, draft=draft, sketch=sketch
        )

    def generate_direct_proof(self, request, draft):
        self.calls.append("direct" if draft is not None else "direct_nodraft")
        code, delay = self._next_proof()
        time.sleep(delay)
        _spend(10)
        return GeneratedProof(lean_code=code, model="m", raw_model_output=code, draft=draft)

    def generate_patch(self, request, feedback: GenerationFeedback):
        self.calls.append("patch")
        patched = self.patches.pop(0) if self.patches else None
        self.last_patch_feedback = feedback
        return (
            None
            if patched is None
            else GeneratedProof(
                lean_code=patched,
                model="m",
                raw_model_output="REPLACE",
                draft=feedback.previous_draft,
                sketch=feedback.previous_sketch,
            )
        )

    def select_repair_route(self, request, feedback):
        self.calls.append("route")
        return RepairRouteDecision(route="prove", rationale="r", raw_model_output="{}")

    def repair(self, request, feedback):
        self.calls.append("repair")
        code, _ = self._next_proof()
        return GeneratedProof(
            lean_code=code,
            model="m",
            raw_model_output=code,
            draft=feedback.previous_draft,
            sketch=feedback.previous_sketch,
        )


def _pipeline(tmp_path: Path, generator: Generator, verifier: ScriptedVerifier, **kw: Any):
    return ProofPipeline(
        generator=generator, verifier=verifier, artifact_store=FileArtifactStore(tmp_path), **kw
    )


def _flags(monkeypatch: pytest.MonkeyPatch, **on: bool) -> None:
    for env in (
        t2_lane.NO_SKETCH_ENV,
        t2_lane.PARALLEL_CANDIDATES_ENV,
        t2_lane.PATCH_REPAIR_ENV,
        t2_lane.PARALLEL_EXPLANATION_ENV,
        t2_lane.NO_DRAFT_ENV,
        t2_lane.NAME_SAFETY_ENV,
        t2_lane.PARALLEL_REVIEW_ENV,
    ):
        monkeypatch.delenv(env, raising=False)
    for env in on:
        monkeypatch.setenv(env, "true")


def test_defaults_keep_the_sketch_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _flags(monkeypatch)
    gen = Generator([GOOD])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    assert gen.calls == ["draft", "sketch", "prove"]


def test_no_sketch_goes_from_the_draft_to_one_proof_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True})
    gen = Generator([GOOD])
    verifier = ScriptedVerifier({GOOD})
    result = _pipeline(tmp_path, gen, verifier).run_statement(statement=STATEMENT, proof_job_id=JOB)
    assert result.state == "verified"
    assert gen.calls == ["draft", "direct"]
    assert verifier.compiled == [GOOD]  # still checked by Lean


def test_no_sketch_does_not_skip_lean_when_the_proof_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True})
    gen = Generator([BAD, GOOD])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    assert result.model_attempt_success is False  # first attempt failed Lean


def test_race_first_verified_wins_loser_cancelled_and_not_recompiled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    # candidate 1 is slow and wrong; candidate 0 is fast and right
    gen = Generator([GOOD, BAD], proof_delays=[0.0, 0.6])
    verifier = ScriptedVerifier({GOOD})
    seen: list[dict[str, Any]] = []
    started = time.monotonic()
    with usage_scope(seen.append):
        result = _pipeline(tmp_path, gen, verifier).run_statement(
            statement=STATEMENT, proof_job_id=JOB
        )
        elapsed = time.monotonic() - started
        assert result.state == "verified" and result.generated.lean_code == GOOD
        assert elapsed < 0.5  # did not wait for the slow candidate
        assert verifier.compiled == [GOOD]  # one compile: the memo served the main loop
        assert t2_lane.drain_background(5) == 0
    assert verifier.compiled == [GOOD]  # the cancelled loser never reached Lean
    # draft (1) + winner (10) + loser (10): both candidates are counted
    assert sorted(r["input_tokens"] for r in seen) == [1, 10, 10]


def test_race_with_no_winner_repairs_the_best_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    gen = Generator([BAD, BAD, GOOD])
    verifier = ScriptedVerifier({GOOD})
    result = _pipeline(tmp_path, gen, verifier).run_statement(statement=STATEMENT, proof_job_id=JOB)
    assert result.state == "verified"
    assert result.model_attempt_success is False
    assert verifier.compiled.count(BAD) == 2  # both candidates compiled concurrently


def test_race_over_the_sketch_path_shares_one_sketch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.PARALLEL_CANDIDATES_ENV: True})
    gen = Generator([BAD, GOOD], proof_delays=[0.3, 0.0])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    assert gen.calls.count("sketch") == 1 and gen.calls.count("prove") == 2


def test_patch_repair_skips_route_and_regeneration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PATCH_REPAIR_ENV: True})
    gen = Generator([BAD], patches=[GOOD])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    assert gen.calls == ["draft", "direct", "patch"]  # no route call, no repair call
    # the patcher got the diagnostics; sanitisation happens inside it (see test_failure_brief)
    assert gen.last_patch_feedback.previous_lean_code == BAD


def test_failed_patch_falls_back_to_the_full_repair_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PATCH_REPAIR_ENV: True})
    gen = Generator([BAD, GOOD], patches=[None])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    # the ordinary path: route call, then (no Sketch exists in the no-Sketch lane) Sketch + Prove
    assert gen.calls == ["draft", "direct", "patch", "route", "sketch", "prove"]


def test_patch_repair_is_bounded_then_the_ordinary_path_takes_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PATCH_REPAIR_ENV: True})
    other = BAD.replace("nlinarith [n]", "omega")
    third = BAD.replace("nlinarith [n]", "decide")
    gen = Generator([BAD, GOOD], patches=[other, third])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    assert gen.calls.count("patch") == t2_lane.PATCH_REPAIR_MAX_ROUNDS
    assert gen.calls[-3:] == ["route", "sketch", "prove"]


class RecordingExplainer:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.started = threading.Event()

    def explain(self, **kwargs: Any) -> str:
        self.codes.append(kwargs["lean_code"])
        self.started.set()
        _spend(5)
        return "explanation"


def test_explanation_starts_beside_verification_and_is_attached_to_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_EXPLANATION_ENV: True})
    explainer = RecordingExplainer()
    seen_by_verifier: list[bool] = []

    class Slow(ScriptedVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            seen_by_verifier.append(
                explainer.started.wait(2)
            )  # explanation began before Lean ended
            return super().verify(lean_code)

    result = _pipeline(
        tmp_path, Generator([GOOD]), Slow({GOOD}), explainer=explainer
    ).run_statement(statement=STATEMENT, proof_job_id=JOB)
    assert seen_by_verifier == [True]
    assert result.speculative_explanation is not None
    seen: list[dict[str, Any]] = []
    with usage_scope(seen.append):
        text = result.speculative_explanation.adopt(
            theorem_statement=STATEMENT, lean_code=GOOD, language="ja", wait_seconds=5
        )
    assert text == "explanation" and len(seen) == 1


def test_explanation_is_discarded_when_the_proof_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_EXPLANATION_ENV: True})
    explainer = RecordingExplainer()
    result = _pipeline(
        tmp_path, Generator([BAD, GOOD]), ScriptedVerifier({GOOD}), explainer=explainer
    ).run_statement(statement=STATEMENT, proof_job_id=JOB)
    assert result.state == "verified"
    assert sorted(explainer.codes) == sorted([BAD, GOOD])
    handle = result.speculative_explanation
    assert handle is not None and handle.lean_code == GOOD  # the BAD one was discarded


def test_no_explanation_when_the_proof_never_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.PARALLEL_EXPLANATION_ENV: True})
    explainer = RecordingExplainer()
    result = _pipeline(
        tmp_path,
        Generator([BAD] * 20),
        ScriptedVerifier(set()),
        explainer=explainer,
        max_repair_attempts=1,
    ).run_statement(statement=STATEMENT, proof_job_id=JOB)
    assert result.state == "failed" and result.speculative_explanation is None


def test_no_draft_routine_request_never_calls_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_DRAFT_ENV: True})
    gen = Generator([GOOD])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB, routine=True
    )
    assert result.state == "verified"
    assert gen.calls == ["direct_nodraft"]


def test_no_draft_non_routine_runs_the_draft_beside_the_proof_and_keeps_it_for_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(
        monkeypatch,
        **{t2_lane.NO_DRAFT_ENV: True, t2_lane.PATCH_REPAIR_ENV: True},
    )
    gen = Generator([BAD], patches=[GOOD])
    result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert result.state == "verified"
    assert sorted(gen.calls[:2]) == ["direct_nodraft", "draft"]
    # the Draft was not used for the first attempt, but it seeds the repair
    assert gen.last_patch_feedback.previous_draft is not None


def test_no_draft_with_a_verified_race_winner_does_not_wait_for_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(
        monkeypatch,
        **{t2_lane.NO_DRAFT_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True},
    )

    class SlowDraft(Generator):
        def generate_draft(self, request, feedback=None):
            time.sleep(0.8)
            return super().generate_draft(request, feedback)

    gen = SlowDraft([GOOD, GOOD], proof_delays=[0.0, 0.0])
    started = time.monotonic()
    seen: list[dict[str, Any]] = []
    with usage_scope(seen.append):
        result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
            statement=STATEMENT, proof_job_id=JOB
        )
        assert result.state == "verified"
        assert time.monotonic() - started < 0.7
        assert t2_lane.drain_background(5) == 0
    assert 1 in [r["input_tokens"] for r in seen]  # the slow Draft was still billed


def test_pipeline_runs_leave_no_state_behind_for_a_pre_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stage 0 in front of the pipeline may return early (the pipeline is then never entered)
    or hand over to it; T2 keeps no process-wide state, so both compose."""
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    assert t2_lane.current_memo() is None and t2_lane.current_explanation_run() is None
    for index in range(2):
        gen = Generator([GOOD, GOOD])
        result = _pipeline(tmp_path, gen, ScriptedVerifier({GOOD})).run_statement(
            statement=STATEMENT, proof_job_id=f"{JOB}-{index}"
        )
        assert result.state == "verified"
        assert t2_lane.current_memo() is None and t2_lane.current_explanation_run() is None
    assert t2_lane.drain_background(5) == 0


class RecordingReviewer:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.started = threading.Event()

    def review_proof(self, **kwargs: Any) -> str:
        self.codes.append(kwargs["lean_code"])
        self.started.set()
        _spend(3)
        return f"approved:{kwargs['lean_code']}"


def test_review_starts_while_lean_compiles_and_the_exact_proof_keeps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_REVIEW_ENV: True})
    reviewer = RecordingReviewer()
    began_before_lean_ended: list[bool] = []

    class Slow(ScriptedVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            began_before_lean_ended.append(reviewer.started.wait(2))
            return super().verify(lean_code)

    result = _pipeline(tmp_path, Generator([GOOD]), Slow({GOOD}), reviewer=reviewer).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )
    assert began_before_lean_ended == [True]
    handle = result.speculative_review
    assert handle is not None and handle.lean_code == GOOD
    # Adoption requires the exact statement and source: a different source gets nothing.
    assert (
        handle.adopt(
            theorem_statement=STATEMENT, lean_code=GOOD + " ", language="ja", wait_seconds=1
        )
        is None
    )


def test_race_starts_a_review_per_candidate_and_keeps_only_the_winners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(
        monkeypatch,
        **{
            t2_lane.NO_SKETCH_ENV: True,
            t2_lane.PARALLEL_CANDIDATES_ENV: True,
            t2_lane.PARALLEL_REVIEW_ENV: True,
        },
    )
    reviewer = RecordingReviewer()
    discarded: list[dict[str, Any]] = []
    gen = Generator([BAD, GOOD], proof_delays=[0.0, 0.1])
    with t2_lane.discarded_usage_scope(discarded.append):
        result = _pipeline(
            tmp_path, gen, ScriptedVerifier({GOOD}), reviewer=reviewer
        ).run_statement(statement=STATEMENT, proof_job_id=JOB)
        assert t2_lane.drain_background(5) == 0
    assert result.state == "verified" and result.speculative_review is not None
    assert result.speculative_review.lean_code == GOOD
    assert sorted(reviewer.codes) == sorted([BAD, GOOD])
    assert [r["input_tokens"] for r in discarded] == [3]  # the losing candidate's review


def test_a_rewritten_statement_is_never_accepted_with_the_template_flags_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixed statement is a harness: a proof of a different statement must not reach a
    verdict of success, with or without the splice (which only repairs layout differences)."""
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True})
    fixed = "theorem add_zero_nat (n : Nat) : n + 0 = n"
    rewritten = GOOD.replace("n + 0 = n", "n = n")
    verifier = ScriptedVerifier({rewritten})  # Lean itself would accept the rewrite
    gen = Generator([rewritten] * 4)
    result = _pipeline(
        tmp_path, gen, verifier, harness_splice=True, max_repair_attempts=1
    ).run_statement(statement=STATEMENT, formal_statement=fixed, proof_job_id=JOB)
    assert result.state == "failed"
    assert rewritten not in verifier.compiled  # rejected by the harness check before Lean
