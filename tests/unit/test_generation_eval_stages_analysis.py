import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/eval/analyze_stages.py"
spec = importlib.util.spec_from_file_location("analyze_stages", SCRIPT)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)


def test_error_totals_ignore_unselected_arms():
    errs = [
        {"arm": "base", "problem_id": "p", "errors": 1},
        {"arm": "static", "problem_id": "p", "errors": 5},
        {"arm": "combined", "problem_id": "p", "errors": 2},
    ]
    a, t = analyze.error_totals(errs, "base", "combined", "errors")
    assert dict(a) == {"p": 1} and dict(t) == {"p": 2}


def test_empty_pairing_reports_and_continues(capsys):
    def run(problem, arm, **kw):
        return {"schema": "pals.generation-eval.run.v1", "problem_id": problem, "arm": arm,
                "error": None, **kw}

    runs = [run("p", "a", success=True, wall_s=1.0), run("q", "b", success=True, wall_s=3.0)]
    analyze.report_metric(runs, "a", "b", "success", "success", binary=True)
    analyze.report_metric(runs, "a", "b", "wall_s", "wall_s", binary=False)
    out = capsys.readouterr().out
    assert out.count("nothing to compare") == 2


def test_main_survives_runs_with_no_paired_problems(tmp_path, monkeypatch, capsys):
    run = {
        "schema": "pals.generation-eval.run.v1",
        "problem_id": "p",
        "arm": "base",
        "error": None,
        "first_attempt_ok": True,
        "success": True,
        "input_tokens": 1,
        "output_tokens": 1,
        "wall_s": 1.0,
        "cost_usd": 0.0,
        "repairs_used": 0,
        "model_calls": 1,
    }
    (tmp_path / "records.jsonl").write_text(json.dumps(run) + "\n")
    monkeypatch.setattr("sys.argv", ["analyze_stages.py", str(tmp_path)])
    analyze.main()
    assert "nothing to compare" in capsys.readouterr().out
