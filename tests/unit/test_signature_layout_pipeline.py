"""Every source the pipeline produces reaches Lean, the API and the user in one normalised layout.

A theorem conclusion that starts a line with ``|`` (an absolute value) is read as a pattern-matching
alternative by the deployed verifier's statement audit, so the pipeline joins that line upward
(pals_agent/lean_layout.py) before the preflight, the local compile, the speculative calls and the
submission. These tests script generators and verifiers (no model, no Lean).
"""

from pathlib import Path
from typing import Any

import pytest

from pals_agent import t2_lane
from pals_agent.lean_layout import normalise_signature_layout
from pals_agent.pipeline import ProofPipeline
from tests.unit.test_t2_api_reconcile import Recorder, _api_pipeline, _run
from tests.unit.test_t2_pipeline import (
    GOOD,
    JOB,
    STATEMENT,
    Generator,
    ScriptedVerifier,
    _flags,
    _pipeline,
)

SPLIT = "import Mathlib\n\ntheorem add_zero_nat (n : Nat) :\n    n + 0 = n := by\n  simp\n"
# Same statement, with an absolute value on its own conclusion line.
ABS = (
    "import Mathlib\n\ntheorem add_zero_nat (n : Nat) :\n    |(n : ℤ)| = n ∧ n + 0 = n := by\n"
    "  constructor <;> simp\n"
)
ABS_JOINED = normalise_signature_layout(ABS)


def test_the_fixture_really_has_a_line_leading_bar() -> None:
    assert "\n    |" in ABS and "\n    |" not in ABS_JOINED
    assert ABS.replace(":\n    |", ": |") == ABS_JOINED


def _local(tmp_path: Path, generator: Generator, verifier: ScriptedVerifier, **kw: Any):
    return _pipeline(tmp_path, generator, verifier, **kw).run_statement(
        statement=STATEMENT, proof_job_id=JOB
    )


def test_local_compile_and_result_use_the_normalised_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch)
    verifier = ScriptedVerifier({ABS_JOINED})
    result = _local(tmp_path, Generator([ABS]), verifier)
    assert verifier.compiled == [ABS_JOINED]
    assert result.state == "verified"
    assert result.generated.lean_code == ABS_JOINED
    assert result.model_attempt is not None and result.model_attempt.lean_code == ABS_JOINED


def test_switch_off_keeps_the_old_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _flags(monkeypatch)
    verifier = ScriptedVerifier({ABS})
    result = _local(tmp_path, Generator([ABS]), verifier, signature_layout_normalisation=False)
    assert verifier.compiled == [ABS]
    assert result.generated.lean_code == ABS


def test_unchanged_sources_are_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _flags(monkeypatch)
    verifier = ScriptedVerifier({SPLIT})
    result = _local(tmp_path, Generator([SPLIT]), verifier)
    assert verifier.compiled == [SPLIT] and result.generated.lean_code == SPLIT


def test_the_race_memo_and_the_main_loop_see_the_same_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True})
    verifier = ScriptedVerifier({ABS_JOINED})
    result = _local(tmp_path, Generator([ABS, ABS], proof_delays=[0.0, 0.6]), verifier)
    assert result.state == "verified" and result.generated.lean_code == ABS_JOINED
    assert set(verifier.compiled) == {ABS_JOINED}  # never the raw layout
    assert len(verifier.compiled) == 1  # the memo served the main loop: no second compile


def test_model_repair_output_is_normalised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _flags(monkeypatch)
    verifier = ScriptedVerifier({ABS_JOINED})
    # The first source fails Lean; the repair returns the bar layout.
    bad = GOOD.replace("simp", "omega")
    result = _local(tmp_path, Generator([bad, ABS]), verifier)
    assert result.state == "verified" and result.generated.lean_code == ABS_JOINED
    assert verifier.compiled == [bad, ABS_JOINED]


def test_patch_repair_output_is_normalised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _flags(monkeypatch, **{t2_lane.NO_SKETCH_ENV: True, t2_lane.PATCH_REPAIR_ENV: True})
    verifier = ScriptedVerifier({ABS_JOINED})
    bad = GOOD.replace("simp", "omega")
    result = _local(tmp_path, Generator([bad], patches=[ABS]), verifier)
    assert result.state == "verified" and result.generated.lean_code == ABS_JOINED
    assert verifier.compiled == [bad, ABS_JOINED]


def test_api_reconcile_submits_the_normalised_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch)
    result, _usage = _run(_api_pipeline(tmp_path, Generator([ABS])))
    assert result.verification_pending
    assert result.generated.lean_code == ABS_JOINED


def test_the_alternate_candidate_race_without_a_compiler_is_normalised(
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
    generator = Generator([ABS, ABS], proof_delays=[0.0, 0.2])
    result, _usage = _run(
        _api_pipeline(tmp_path, generator, explainer=recorder, reviewer=recorder)
    )
    assert result.verification_pending and result.generated.lean_code == ABS_JOINED
    # Speculative explanation and review were started for, and kept for, the submitted source.
    assert result.speculative_explanation is not None
    assert result.speculative_explanation.lean_code == ABS_JOINED
    assert {call["lean_code"] for call in recorder.calls} == {ABS_JOINED}


def test_api_reconcile_switch_off_submits_the_old_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch)
    pipeline = _api_pipeline(tmp_path, Generator([ABS]), signature_layout_normalisation=False)
    result, _usage = _run(pipeline)
    assert result.generated.lean_code == ABS


def test_the_pipeline_default_is_on() -> None:
    assert ProofPipeline.__dataclass_fields__["signature_layout_normalisation"].default is True
