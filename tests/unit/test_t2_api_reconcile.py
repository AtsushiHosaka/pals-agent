"""The T2 lane under API reconciliation (no compiler in this process): scripted, no model/Lean."""

import threading
from pathlib import Path
from typing import Any

import pytest

from pals_agent import t2_lane
from pals_agent.artifacts import FileArtifactStore
from pals_agent.pipeline import ProofPipeline
from pals_agent.usage import usage_scope
from tests.unit.test_t2_pipeline import BAD, GOOD, STATEMENT, Generator, _flags

NO_TARGET = "import Mathlib\n\n#check Nat\n"  # fails the worker's own preflight


def _api_pipeline(tmp_path: Path, generator: Generator, **kw: Any) -> ProofPipeline:
    kw.setdefault("accounting_wait_seconds", 0.0)
    return ProofPipeline(
        generator=generator,
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
        **kw,
    )


def _run(pipeline: ProofPipeline, usage: list[dict[str, Any]] | None = None):
    sink = usage if usage is not None else []
    with usage_scope(sink.append):
        result = pipeline.run_statement(
            statement=STATEMENT,
            proof_job_id="job-1",
            on_status=lambda *_args: None,
        )
        if result.background is not None:
            result.background.drain(5.0)
    return result, sink


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def explain(self, **kwargs: Any) -> str:
        with self.lock:
            self.calls.append(kwargs)
        return "explanation"

    def review_proof(self, **kwargs: Any) -> str:
        with self.lock:
            self.calls.append(kwargs)
        return "review"


def test_the_race_without_a_compiler_submits_the_faster_candidate_and_counts_the_loser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_DRAFT_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    # The first model call is slow, the second fast: the second wins, and the slow one still bills.
    generator = Generator([GOOD, BAD], proof_delays=[0.4, 0.0])
    result, usage = _run(_api_pipeline(tmp_path, generator))

    assert result.verification_pending
    assert result.generated.lean_code == BAD  # the faster one, since this process cannot compile
    assert generator.calls.count("direct_nodraft") == 2
    assert "draft" not in generator.calls  # no Draft on the answer's path
    assert sum(record["input_tokens"] for record in usage) == 20  # winner and loser, once each


def test_a_candidate_that_fails_the_preflight_never_wins_the_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_DRAFT_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    generator = Generator([NO_TARGET, GOOD], proof_delays=[0.0, 0.2])
    result, _usage = _run(_api_pipeline(tmp_path, generator))

    assert result.verification_pending
    assert result.generated.lean_code == GOOD  # the fast one failed the preflight
    # Two candidates at once, and no model repair step (route, patch, repair) was needed.
    assert generator.calls == ["direct_nodraft", "direct_nodraft"]


def test_without_the_switch_there_is_one_candidate_and_no_background_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch)
    generator = Generator([GOOD])
    result, _usage = _run(_api_pipeline(tmp_path, generator))

    assert result.verification_pending
    assert generator.calls == ["draft", "sketch", "prove"]
    assert result.speculative_explanation is None and result.speculative_review is None


def test_explanation_and_review_start_for_the_submitted_source_and_come_back_on_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(
        monkeypatch,
        **{
            t2_lane.NO_DRAFT_ENV: True,
            t2_lane.PARALLEL_CANDIDATES_ENV: True,
            t2_lane.PARALLEL_EXPLANATION_ENV: True,
            t2_lane.PARALLEL_REVIEW_ENV: True,
        },
    )
    recorder = Recorder()
    generator = Generator([GOOD, GOOD], proof_delays=[0.0, 0.2])
    pipeline = _api_pipeline(tmp_path, generator, explainer=recorder, reviewer=recorder)
    result, _usage = _run(pipeline)

    assert result.verification_pending
    assert result.speculative_explanation is not None
    assert result.speculative_review is not None
    assert result.speculative_explanation.lean_code == GOOD
    # One call each, for the submitted source only (the loser never started either).
    assert len(recorder.calls) == 2
    assert {call["lean_code"] for call in recorder.calls} == {GOOD}


def test_the_speculative_calls_are_dropped_when_the_loop_changes_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A preflight failure repaired locally submits a different source: nothing is kept for it."""
    _flags(
        monkeypatch,
        **{t2_lane.NO_DRAFT_ENV: True, t2_lane.PARALLEL_EXPLANATION_ENV: True},
    )
    recorder = Recorder()
    generator = Generator([NO_TARGET, GOOD])
    result, _usage = _run(_api_pipeline(tmp_path, generator, explainer=recorder))

    assert result.verification_pending
    assert result.generated.lean_code == GOOD
    assert result.speculative_explanation is not None
    assert result.speculative_explanation.lean_code == GOOD
    assert [call["lean_code"] for call in recorder.calls] == [GOOD]


# A request about the continuity of x squared, and a source whose target is `True`.
X2_STATEMENT = "実数全体で x^2 が連続であることを示してください。"
TRIVIAL = "import Mathlib\n\ntheorem trivial_target : True := by\n  trivial\n"
X2_PROOF = (
    "import Mathlib\n\ntheorem x_sq_continuous : Continuous (fun x : ℝ => x ^ 2) := by\n"
    "  exact continuous_pow 2\n"
)


def test_a_fast_candidate_that_proves_another_statement_does_not_win_the_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pals_agent.lean_target import extract_single_target_declaration
    from pals_agent.worker import _target_matches_statement  # the worker's own later check

    _flags(monkeypatch, **{t2_lane.NO_DRAFT_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    target = extract_single_target_declaration(TRIVIAL)
    assert target is not None and not _target_matches_statement(X2_STATEMENT, target)

    generator = Generator([TRIVIAL, X2_PROOF], proof_delays=[0.0, 0.2])
    pipeline = _api_pipeline(tmp_path, generator)
    with usage_scope(lambda _u: None):
        result = pipeline.run_statement(
            statement=X2_STATEMENT, proof_job_id="job-x2", on_status=lambda *_a: None
        )
        if result.background is not None:
            result.background.drain(5.0)

    assert result.verification_pending
    assert result.generated.lean_code == X2_PROOF  # the slow but correct one is submitted


@pytest.mark.parametrize("padding", ["", "  ", "\n\n", "\t \n"])
def test_the_races_target_check_agrees_with_the_workers_for_any_padding_of_the_statement(
    padding: str,
) -> None:
    """The race reads ``request.prompt``; the worker reads the job's ``statement``. The pipeline
    builds the prompt as ``statement.strip()`` on every path, and the check ignores whitespace."""
    from pals_agent.lean_target import extract_single_target_declaration
    from pals_agent.pipeline import _aligned_with_request, _request_for_statement
    from pals_agent.worker import _target_matches_statement

    statement = padding + X2_STATEMENT + padding
    request = _request_for_statement(statement)
    assert request.prompt == statement.strip()
    for code in (TRIVIAL, X2_PROOF):
        target = extract_single_target_declaration(code)
        assert target is not None
        assert _aligned_with_request(request.prompt, code) == _target_matches_statement(
            statement, target
        )
