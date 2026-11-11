import importlib.util
from pathlib import Path

from pals_agent.evals.analysis import mcnemar_exact, paired_permutation_test

_SPEC = importlib.util.spec_from_file_location(
    "analyze_stages", Path(__file__).parents[2] / "scripts/eval/analyze_stages.py"
)
assert _SPEC and _SPEC.loader
analyze = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analyze)


def _row(problem: str, arm: str, repeat: int, ok: bool, wall: float) -> dict:
    return {
        "schema": "pals.generation-eval.run.v1",
        "problem_id": problem,
        "arm": arm,
        "repeat": repeat,
        "success": ok,
        "first_attempt_ok": ok,
        "wall_s": wall,
        "error": None,
    }


def test_uses_the_shared_statistics_not_a_private_copy() -> None:
    assert analyze.paired_permutation_test is paired_permutation_test
    assert not hasattr(analyze, "sign_flip_p") and not hasattr(analyze, "mcnemar_exact")


def test_single_repeat_reports_mcnemar_and_exact_permutation(capsys) -> None:
    rows = [_row(f"p{i}", "a", 1, False, 10) for i in range(6)]
    rows += [_row(f"p{i}", "b", 1, True, 5) for i in range(6)]
    analyze.report_metric(rows, "a", "b", "success", "success", binary=True)
    out = capsys.readouterr().out
    assert f"'mcnemar_p': {mcnemar_exact(0, 6)}".replace("'", '"') in out
    assert "perm_p=0.031" in out  # exact: 2 / 2**6


def test_agreeing_repeats_do_not_trigger_a_pooled_mcnemar(capsys) -> None:
    # Two repeats per arm, all 0 or all 1 within a problem: averaged values are 0/1, which used to
    # be mistaken for single paired observations. McNemar must be per repeat index instead.
    rows = []
    for i in range(4):
        for r in (1, 2):
            rows.append(_row(f"p{i}", "a", r, False, 10))
            rows.append(_row(f"p{i}", "b", r, True, 5))
    analyze.report_metric(rows, "a", "b", "success", "success", binary=True)
    out = capsys.readouterr().out
    assert "mcnemar_by_repeat" in out and '"mcnemar_p"' not in out
