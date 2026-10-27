from __future__ import annotations

import json
from pathlib import Path

import pytest

from pals_agent.geometry_input import GeometryProblem
from pals_agent.lean import LeanVerifier
from pals_agent.synthetic_geometry import (
    PROOF_SHA256,
    GeometryVerificationError,
    _check_environment,
    _trace,
    check_geometry,
    main,
    parse_axiom_report,
    proof_source,
)

ROOT = Path(__file__).resolve().parents[2]
NAMES = (
    "base_distinct",
    "apex_distinct_midpoint",
    "apex_mem_perpBisector",
    "midpoint_orthogonality",
    "isosceles_midpoint_perpendicular",
)


def request() -> dict:
    return json.loads((ROOT / "testdata/synthetic-geometry-v1/isosceles-request.json").read_text())


def report() -> str:
    return '"4.32.0-rc1"\n' + "\n".join(
        f"'PalsGeometry.{name}' depends on axioms: [propext, Classical.choice, Quot.sound]"
        for name in NAMES
    )


def test_trace_references_checked_source_premises_and_prior_steps() -> None:
    problem = GeometryProblem.parse(request())
    source = proof_source()
    steps = _trace(problem, source)
    known = set()
    premises = {h["id"] for h in problem.to_data()["hypotheses"]}
    for step in steps:
        assert set(step["dependencies"]) <= known
        assert set(step["premises"]) <= premises
        binding = step["source_binding"]
        assert binding["sha256"] == PROOF_SHA256
        fragment = "\n".join(source.splitlines()[binding["start_line"] - 1 : binding["end_line"]])
        assert fragment.startswith("theorem " + step["id"] + " ")
        assert step["role_ids"] == problem.role_ids
        known.add(step["id"])
    assert list(known)  # each declaration is present, including the final conjunction
    assert set(steps[-1]["dependencies"]) == set(NAMES[:-1])


def test_axiom_report_requires_every_declaration_and_active_version() -> None:
    assert set(parse_axiom_report(report())) == set(NAMES)
    for invalid in (
        report().replace("Quot.sound", "SMT_VERIF"),
        report().replace("Quot.sound", "sorryAx"),
        report().replace("4.32.0-rc1", "4.19.0"),
        "\n".join(report().splitlines()[:-1]),
        report() + "\n" + report().splitlines()[1],
        report() + "\n'PalsGeometry.unexpected' depends on axioms: [propext]",
    ):
        with pytest.raises(GeometryVerificationError):
            parse_axiom_report(invalid)


def test_unconfirmed_ambiguity_never_reaches_compiler() -> None:
    data = request()
    data["ambiguities"] = ["Does the figure mark a midpoint or only a point on BC?"]
    problem = GeometryProblem.parse(data)
    # This environment cannot compile. A needs-input result must precede all environment access.
    result = check_geometry(problem, LeanVerifier(project_dir=Path("/nonexistent/geometry")))
    assert result["status"] == "needs_input"
    assert result["input"] == data
    assert "trace" not in result and "verification" not in result


def test_toolchain_drift_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.19.0")
    with pytest.raises(GeometryVerificationError, match="toolchain pin"):
        _check_environment(LeanVerifier(project_dir=tmp_path))


def test_cli_malformed_request_is_failure(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "request.json"
    path.write_text('{"schema_version": "unsupported"}')
    assert main([str(path), "--lean-workspace", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_cli_deep_json_is_failure(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "request.json"
    path.write_text("[" * 2000 + "0" + "]" * 2000)
    assert main([str(path), "--lean-workspace", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
