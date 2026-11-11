"""The heterogeneous race (fast + strong candidate) and the held alternate, scripted: no model."""

import threading
from pathlib import Path
from typing import Any

import pytest

from pals_agent import t2_lane
from pals_agent.models import Diagnostic, GeneratedProof, VerificationResult
from pals_agent.pipeline import ApiRepairSeed
from tests.unit.test_t2_api_reconcile import _api_pipeline, _run
from tests.unit.test_t2_pipeline import BAD, GOOD, STATEMENT, Generator, _flags

ON = {
    t2_lane.NO_DRAFT_ENV: True,
    t2_lane.PARALLEL_CANDIDATES_ENV: True,
    t2_lane.HETERO_RACE_ENV: True,
}


class EffortGenerator(Generator):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.efforts: list[str | None] = []

    def generate_direct_proof(self, request, draft):
        with self.lock:
            self.efforts.append(t2_lane.variant_effort())
        return super().generate_direct_proof(request, draft)


def test_each_candidate_gets_its_own_effort_and_the_loser_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **ON)
    generator = EffortGenerator([GOOD, BAD], proof_delays=[0.0, 0.15])
    result, usage = _run(_api_pipeline(tmp_path, generator))

    assert sorted(e for e in generator.efforts if e) == ["low", "medium"]
    assert result.generated.lean_code == GOOD  # the first one to pass the preflight is submitted
    slot = result.background.alternate
    assert slot is not None
    held = slot.take(2.0)
    assert held is not None and held.lean_code == BAD
    assert slot.take(0.0) is None  # handed out once
    assert sum(r["input_tokens"] for r in usage) == 20  # both candidates billed, once each


def test_without_the_switch_there_is_no_slot_and_no_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **{k: v for k, v in ON.items() if k != t2_lane.HETERO_RACE_ENV})
    monkeypatch.delenv(t2_lane.HETERO_RACE_ENV, raising=False)
    generator = EffortGenerator([GOOD, BAD], proof_delays=[0.0, 0.1])
    result, _ = _run(_api_pipeline(tmp_path, generator))

    assert result.background is None or result.background.alternate is None
    assert generator.efforts == [None, None]


def _seed(code: str, attempt: int = 1) -> ApiRepairSeed:
    return ApiRepairSeed(
        generated=GeneratedProof(lean_code=code, model="m", raw_model_output=code),
        verification=VerificationResult(
            success=False, stdout="", stderr="", elapsed_ms=1,
            diagnostics=[Diagnostic(
                severity="error", code="verifier_compile_failed", message="Compiler rejected it.",
            )],
        ),
        attempt=attempt, repairs_used=attempt - 1,
    )


def _repair_run(tmp_path: Path, generator: Generator, seed: ApiRepairSeed):
    return _api_pipeline(tmp_path, generator, max_repair_attempts=3).run_statement(
        statement=STATEMENT, proof_job_id="job-1", api_repair_seed=seed,
        on_status=lambda *_a: None,
    )


def test_a_failed_compile_submits_the_held_candidate_as_one_repair_with_no_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **ON)
    generator = Generator([])  # any model call would pop from an empty list and fail
    slot = t2_lane.AlternateSlot(1)
    slot.offer(GeneratedProof(lean_code=BAD, model="m", raw_model_output=BAD))
    slot.finished_one()
    with t2_lane.alternate_for_repair(slot):
        result = _repair_run(tmp_path, generator, _seed(GOOD))

    assert result.verification_pending
    assert result.generated.lean_code == BAD
    assert generator.calls == []  # no route, no repair, no patch
    import json

    metadata = json.loads(Path(result.artifact.uri).read_text())
    assert metadata["repairs_used"] == 1  # counted like a model repair
    assert [a["attempt"] for a in metadata["attempts"]] == [1, 2]


def test_a_second_failure_goes_to_the_ordinary_repair_the_alternate_is_single_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **ON)
    slot = t2_lane.AlternateSlot(1)
    slot.offer(GeneratedProof(lean_code=BAD, model="m", raw_model_output=BAD))
    slot.finished_one()
    with t2_lane.alternate_for_repair(slot):
        _repair_run(tmp_path / "a", Generator([]), _seed(GOOD))
        generator = Generator([GOOD])
        result = _repair_run(tmp_path / "b", generator, _seed(BAD, attempt=2))

    assert "route" in generator.calls or "repair" in generator.calls
    assert result.generated.lean_code == GOOD


def test_the_same_source_or_no_alternate_falls_back_to_the_model_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **ON)
    same = t2_lane.AlternateSlot(1)
    same.offer(GeneratedProof(lean_code=GOOD, model="m", raw_model_output=GOOD))
    same.finished_one()
    for index, slot in enumerate((same, t2_lane.AlternateSlot(0), None)):
        generator = Generator([BAD])
        with t2_lane.alternate_for_repair(slot):
            result = _repair_run(tmp_path / str(index), generator, _seed(GOOD))
        assert generator.calls and generator.calls != []
        assert result.generated.lean_code == BAD


def test_a_candidate_still_generating_is_waited_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _flags(monkeypatch, **ON)
    slot = t2_lane.AlternateSlot(1)
    generator = Generator([])
    threading.Timer(
        0.2,
        lambda: (
            slot.offer(GeneratedProof(lean_code=BAD, model="m", raw_model_output=BAD)),
            slot.finished_one(),
        ),
    ).start()
    with t2_lane.alternate_for_repair(slot):
        result = _repair_run(tmp_path, generator, _seed(GOOD))

    assert result.generated.lean_code == BAD and generator.calls == []


def test_the_switch_is_validated_with_the_other_t2_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(t2_lane.HETERO_RACE_ENV, "yes")
    with pytest.raises(ValueError):
        t2_lane.validate_flags()


def test_a_candidate_for_another_statement_is_neither_submitted_nor_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pals_agent.usage import usage_scope
    from tests.unit.test_t2_api_reconcile import TRIVIAL, X2_PROOF, X2_STATEMENT

    _flags(monkeypatch, **ON)
    generator = Generator([TRIVIAL, X2_PROOF], proof_delays=[0.0, 0.15])
    with usage_scope(lambda _u: None):
        result = _api_pipeline(tmp_path, generator).run_statement(
            statement=X2_STATEMENT, proof_job_id="job-x2", on_status=lambda *_a: None
        )
        result.background.drain(5.0)

    assert result.generated.lean_code == X2_PROOF
    assert result.background.alternate.take(0.5) is None  # the misaligned one is not an alternate
