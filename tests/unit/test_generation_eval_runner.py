import json
from dataclasses import dataclass, field

import pytest

from pals_agent.evals.records import ATTEMPT_SCHEMA, JsonlSink, RecordError, read_rows, validate_row
from pals_agent.evals.runner import (
    RecordingGenerator,
    RecordingVerifier,
    Scope,
    estimate_usd,
    interleaved_schedule,
    run_tier0,
    run_tier1,
)


@dataclass
class Diag:
    severity: str
    message: str
    code: str | None = None
    line: int | None = None


@dataclass
class Result:
    success: bool
    diagnostics: list = field(default_factory=list)
    elapsed_ms: int = 5


class FakeVerifier:
    def __init__(self, ok_if="OK"):
        self.ok_if = ok_if

    def verify(self, code):
        if "CRASH" in code:
            raise RuntimeError("boom")
        ok = self.ok_if in code
        return Result(
            ok,
            []
            if ok
            else [
                Diag("error", "unsolved goals", "lean.error", 3),
                Diag("warning", "unused", "lean.lint"),
            ],
        )

    verify_sketch = verify


def make_scope(tmp_path):
    sink = JsonlSink(tmp_path / "r.jsonl", artifacts_dir=tmp_path / "art")
    return Scope(run_id="run1", sink=sink)


def test_schedule_is_interleaved_counterbalanced_and_deterministic():
    ids = [f"p{i}" for i in range(10)]
    plan = interleaved_schedule(ids, ["A", "B"], 2)
    assert plan == interleaved_schedule(ids, ["A", "B"], 2)
    assert len(plan) == 40
    for i in range(0, 40, 2):  # arms of one problem are adjacent
        assert plan[i][0] == plan[i + 1][0] and plan[i][2] == plan[i + 1][2]
        assert {plan[i][1], plan[i + 1][1]} == {"A", "B"}
    first = [plan[i][1] for i in range(0, 40, 2)]
    assert 8 <= first.count("A") <= 12  # roughly balanced who goes first


def test_closed_schema_rejects_unknown_fields_and_bad_stage():
    with pytest.raises(RecordError):
        validate_row(
            {
                "schema": ATTEMPT_SCHEMA,
                "run_id": "r",
                "problem_id": "p",
                "arm": "a",
                "stage": "draft",
                "statement": "leaked text",
            }
        )
    with pytest.raises(RecordError):
        validate_row(
            {
                "schema": ATTEMPT_SCHEMA,
                "run_id": "r",
                "problem_id": "p",
                "arm": "a",
                "stage": "nope",
            }
        )


def test_failed_check_saves_lean_and_codes_but_not_inline(tmp_path):
    scope = make_scope(tmp_path)
    scope.reset("p1", "A", 1)
    rv = RecordingVerifier(FakeVerifier(), scope)
    assert rv.verify("theorem bad").success is False
    assert rv.verify("theorem OK").success is True
    rows = read_rows(tmp_path / "r.jsonl")
    bad, good = rows
    assert bad["stage"] == "lean_check" and bad["error_codes"] == ["lean.error"]
    assert bad["diagnostic_count"] == 1 and bad["diagnostics"][0]["line"] == 3
    assert (tmp_path / "art" / bad["lean_path"]).read_text() == "theorem bad"
    assert bad["lean_sha256"] and good["lean_sha256"] is None
    assert "theorem bad" not in json.dumps(bad)
    assert (bad["ordinal"], good["ordinal"]) == (1, 2)


def test_tier0_records_success_failure_and_crash(tmp_path):
    scope = make_scope(tmp_path)
    rows = run_tier0(
        [
            {"problem_id": "a", "lean_code": "OK"},
            {"problem_id": "b", "lean_code": "x"},
            {"problem_id": "c", "lean_code": "CRASH"},
        ],
        FakeVerifier(),
        scope,
        arm="base",
        splits={"a": "tuning"},
    )
    assert [r["success"] for r in rows] == [True, False, False]
    assert rows[0]["split"] == "tuning" and rows[0]["cost_usd"] == 0.0 and rows[0]["tier"] == 0
    assert rows[2]["error"] == "RuntimeError"
    attempts = [r for r in read_rows(tmp_path / "r.jsonl") if r["schema"] == ATTEMPT_SCHEMA]
    assert [a["stage"] for a in attempts] == [
        "replay_check",
        "replay_check",
    ]  # crash writes no attempt


@dataclass
class Part:
    elapsed_ms: int
    model: str = "gpt-6.1-terra"
    reasoning_effort: str = "medium"
    lean_code: str = "OK"


class FakeGenerator:
    def __init__(self, scope):
        self.scope = scope

    def generate_sketch(self, request, draft):
        self.scope.on_usage(
            {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 2000}
        )
        return Part(3000)


def test_tier1_sketch_cost_tokens_and_record(tmp_path):
    scope = make_scope(tmp_path)
    from contextlib import contextmanager

    @contextmanager
    def usage_scope(reporter):
        yield

    problems = [{"id": "p1", "statement": "s", "split": "held_out"}, {"id": "p2", "statement": "s"}]
    rows = run_tier1(
        problems,
        {"p1": "draft text"},
        FakeGenerator(scope),
        FakeVerifier(),
        lambda **kw: object(),
        scope,
        arm="new",
        model="gpt-6.1-terra",
        usage_scope_factory=usage_scope,
    )
    assert len(rows) == 1  # p2 has no cached draft: skipped, not failed
    r = rows[0]
    assert r["tier"] == 1 and r["success"] is True and r["split"] == "held_out"
    assert (
        r["input_tokens"] == 1000 and r["cached_input_tokens"] == 200 and r["output_tokens"] == 2000
    )
    assert (
        r["cost_usd"]
        == pytest.approx(estimate_usd("gpt-6.1-terra", 1000, 2000))
        == pytest.approx(0.01125)
    )
    stages = [a["stage"] for a in read_rows(tmp_path / "r.jsonl") if a["schema"] == ATTEMPT_SCHEMA]
    assert stages == ["sketch", "sketch_check"]


def test_recording_generator_lays_stages_end_to_end(tmp_path):
    scope = make_scope(tmp_path)
    scope.reset("p1", "A", 1)

    class Inner:
        def generate(self, request):
            draft, sketch = Part(1000), Part(2000)
            proof = Part(4000)
            proof.draft, proof.sketch = draft, sketch
            return proof

        def repair(self, request, feedback):
            return Part(10)

    g = RecordingGenerator(Inner(), scope)
    g.generate(object())
    g.repair(object(), object())
    rows = read_rows(tmp_path / "r.jsonl")
    assert [r["stage"] for r in rows] == ["draft", "sketch", "prove", "repair"]
    assert [r["elapsed_ms"] for r in rows[:3]] == [1000, 2000, 4000]
    assert rows[0]["ended_at"] == rows[1]["started_at"]
    assert rows[1]["model"] == "gpt-6.1-terra"


def test_unknown_model_cost_is_none_not_zero():
    assert estimate_usd("some-new-model", 10, 10) is None
