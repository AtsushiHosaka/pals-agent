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
        self.repair_efforts: list[str | None] = []

    def generate_direct_proof(self, request, draft):
        with self.lock:
            self.efforts.append(t2_lane.variant_effort())
        return super().generate_direct_proof(request, draft)

    def generate_proof(self, request, draft, sketch, feedback=None):
        with self.lock:
            self.repair_efforts.append(t2_lane.variant_effort())
        return super().generate_proof(request, draft, sketch, feedback)

    def generate_patch(self, request, feedback):
        with self.lock:
            self.repair_efforts.append(t2_lane.variant_effort())
        return super().generate_patch(request, feedback)


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
    generator = EffortGenerator([GOOD, GOOD, GOOD], patches=[GOOD])
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
    # A repair did run (a patch, or the full route to a proof), and none of it took the fast effort.
    assert generator.repair_efforts and "low" not in generator.repair_efforts
    assert "low" not in generator.efforts


def test_the_switch_is_validated_with_the_other_t2_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(t2_lane.CHEAP_FIRST_ENV, "yes")
    with pytest.raises(ValueError):
        t2_lane.validate_flags()


def test_cheap_first_never_reaches_a_race_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A homogeneous race sets its own variants; cheap-first must not hand them efforts."""
    _flags(monkeypatch, **BASE, **{
        t2_lane.CHEAP_FIRST_ENV: True, t2_lane.PARALLEL_CANDIDATES_ENV: True,
    })
    monkeypatch.delenv(t2_lane.HETERO_RACE_ENV, raising=False)
    generator = EffortGenerator([GOOD, GOOD], proof_delays=[0.0, 0.05])
    _run(_api_pipeline(tmp_path, generator))
    assert generator.efforts == [None, None]


def _hybrid(model: str = "gpt-6.1-terra", *, effort: str | None = None):
    from pals_agent.generator import HybridLeanGenerator
    from pals_agent.openai import OpenAIResponsesClient

    return HybridLeanGenerator(
        model=model, provider="openai", use_release_role_bindings=True,
        client=OpenAIResponsesClient(api_key="k", reasoning_effort=effort),  # type: ignore[arg-type]
    )


def _prove_effort(generator: Any) -> str | None:
    from pals_agent.model_roles import ModelRole

    return generator._stage_endpoint(ModelRole.PROVE)[3]


def test_the_effort_the_client_really_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    _flags(monkeypatch)
    monkeypatch.setenv(t2_lane.CHEAP_FIRST_ENV, "true")
    terra = _hybrid()
    with t2_lane.candidate_variant(0):
        assert _prove_effort(terra) == "low"  # the first attempt
    assert _prove_effort(terra) == "medium"  # a repair: the role's own effort
    with t2_lane.candidate_variant(0):
        assert _prove_effort(_hybrid("gpt-6-luna")) == "low"  # the release model is fixed low
    monkeypatch.delenv(t2_lane.CHEAP_FIRST_ENV)
    with t2_lane.candidate_variant(0):
        assert _prove_effort(terra) == "medium"  # switch off


def _failed_seed(repairs_used: int) -> ApiRepairSeed:
    return ApiRepairSeed(
        generated=GeneratedProof(lean_code=BAD, model="m", raw_model_output=BAD),
        verification=VerificationResult(
            success=False, stdout="", stderr="", elapsed_ms=1,
            diagnostics=[Diagnostic(
                severity="error", code="verifier_compile_failed", message="Compiler rejected it.",
            )],
        ),
        attempt=repairs_used + 1, repairs_used=repairs_used,
    )


@pytest.mark.parametrize(
    "rounds,repairs_used,expected",
    [("1", 0, ["low"]), ("1", 1, [None]), (None, 0, [None]), ("2", 1, ["low"])],
)
def test_the_first_patch_rounds_may_take_the_fast_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    rounds: str | None, repairs_used: int, expected: list[str | None],
) -> None:
    _flags(monkeypatch, **BASE, **{t2_lane.CHEAP_FIRST_ENV: True, t2_lane.PATCH_REPAIR_ENV: True})
    if rounds is None:
        monkeypatch.delenv(t2_lane.CHEAP_PATCH_ROUNDS_ENV, raising=False)
    else:
        monkeypatch.setenv(t2_lane.CHEAP_PATCH_ROUNDS_ENV, rounds)
    generator = EffortGenerator([GOOD], patches=[GOOD])
    _api_pipeline(tmp_path, generator, max_repair_attempts=4).run_statement(
        statement=STATEMENT, proof_job_id="job-1", api_repair_seed=_failed_seed(repairs_used),
        on_status=lambda *_a: None,
    )
    assert generator.calls[0] == "patch"
    assert generator.repair_efforts[:1] == expected


def test_a_patch_never_takes_the_fast_effort_without_cheap_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **BASE, **{t2_lane.PATCH_REPAIR_ENV: True})
    monkeypatch.delenv(t2_lane.CHEAP_FIRST_ENV, raising=False)
    monkeypatch.setenv(t2_lane.CHEAP_PATCH_ROUNDS_ENV, "2")
    generator = EffortGenerator([GOOD], patches=[GOOD])
    _api_pipeline(tmp_path, generator, max_repair_attempts=4).run_statement(
        statement=STATEMENT, proof_job_id="job-1", api_repair_seed=_failed_seed(0),
        on_status=lambda *_a: None,
    )
    assert generator.repair_efforts[:1] == [None]


def test_the_patch_rounds_setting_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in ("x", "3", "-1"):
        monkeypatch.setenv(t2_lane.CHEAP_PATCH_ROUNDS_ENV, bad)
        with pytest.raises(ValueError):
            t2_lane.validate_flags()
