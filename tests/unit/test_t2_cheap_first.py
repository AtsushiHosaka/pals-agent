"""Cheap-first: the first attempt at the fast effort, every repair at the role's own effort."""

from pathlib import Path
from typing import Any

import pytest

from pals_agent import t2_lane
from pals_agent.models import Diagnostic, GeneratedProof, VerificationResult
from pals_agent.pipeline import ApiRepairSeed
from tests.unit.test_t2_api_reconcile import _api_pipeline, _run
from tests.unit.test_t2_pipeline import BAD, GOOD, STATEMENT, Generator, _flags


class EffortGenerator(Generator):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.efforts: list[str | None] = []

    def generate_direct_proof(self, request, draft):
        with self.lock:
            self.efforts.append(t2_lane.variant_effort())
        return super().generate_direct_proof(request, draft)


BASE = {t2_lane.NO_DRAFT_ENV: True}


def test_the_first_attempt_runs_at_the_fast_effort_with_no_second_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **BASE, **{t2_lane.CHEAP_FIRST_ENV: True})
    generator = EffortGenerator([GOOD])
    result, _ = _run(_api_pipeline(tmp_path, generator))
    assert generator.efforts == ["low"]
    assert result.generated.lean_code == GOOD
    assert result.background is None or result.background.alternate is None


def test_with_the_switch_off_the_effort_is_the_roles_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **BASE)
    monkeypatch.delenv(t2_lane.CHEAP_FIRST_ENV, raising=False)
    generator = EffortGenerator([GOOD])
    _run(_api_pipeline(tmp_path, generator))
    assert generator.efforts == [None]


def test_a_repair_never_takes_the_fast_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **BASE, **{t2_lane.CHEAP_FIRST_ENV: True})
    generator = EffortGenerator([GOOD, GOOD])
    seed = ApiRepairSeed(
        generated=GeneratedProof(lean_code=BAD, model="m", raw_model_output=BAD),
        verification=VerificationResult(
            success=False, stdout="", stderr="", elapsed_ms=1,
            diagnostics=[Diagnostic(
                severity="error", code="verifier_compile_failed", message="Compiler rejected it.",
            )],
        ),
        attempt=1, repairs_used=0,
    )
    _api_pipeline(tmp_path, generator, max_repair_attempts=3).run_statement(
        statement=STATEMENT, proof_job_id="job-1", api_repair_seed=seed,
        on_status=lambda *_a: None,
    )
    assert "low" not in generator.efforts


def test_the_switch_is_validated_with_the_other_t2_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(t2_lane.CHEAP_FIRST_ENV, "yes")
    with pytest.raises(ValueError):
        t2_lane.validate_flags()
