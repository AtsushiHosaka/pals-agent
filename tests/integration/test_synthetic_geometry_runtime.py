"""Real Lean checks; set PALS_GEOMETRY_LEAN_WORKSPACE to the existing pinned workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pals_agent.geometry_input import GeometryProblem
from pals_agent.lean import LeanVerifier
from pals_agent.synthetic_geometry import ALLOWED_AXIOMS, check_geometry

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def verifier() -> LeanVerifier:
    workspace = os.environ.get("PALS_GEOMETRY_LEAN_WORKSPACE")
    if workspace is None:
        pytest.skip("real pinned Lean workspace not configured")
    return LeanVerifier(
        project_dir=Path(workspace),
        lean_binary=os.environ.get("PALS_GEOMETRY_LEAN", "lean"),
        lake_binary=os.environ.get("PALS_GEOMETRY_LAKE", "lake"),
        elan_home=os.environ.get("ELAN_HOME", "/opt/elan"),
        child_path=os.environ.get("PATH", "/opt/elan/bin:/usr/bin:/bin"),
        timeout_seconds=60,
    )


def test_real_isosceles_trace_and_transitive_axioms(verifier: LeanVerifier) -> None:
    data = json.loads((ROOT / "testdata/synthetic-geometry-v1/isosceles-request.json").read_text())
    result = check_geometry(GeometryProblem.parse(data), verifier)
    assert result["status"] == "checked"
    assert result["verification"]["success"] is True
    assert len(result["trace"]) == 5
    assert all(set(axioms) <= ALLOWED_AXIOMS for axioms in result["axioms"].values())
    assert result["diagram_status"] == "prepared_unrendered"
    assert result["diagrams"][0]["evidence_refs"][0]["source_sha256"] == result["proof_sha256"]


def test_real_hard_negative_and_degenerate_counterexamples(verifier: LeanVerifier) -> None:
    source = (ROOT / "testdata/synthetic-geometry-v1/negative-counterexamples.lean").read_text()
    result = verifier.verify(source)
    assert result.success, result.stdout + result.stderr + str(result.diagnostics)
