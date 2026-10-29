from __future__ import annotations

import json
from pathlib import Path

import pytest

from pals_agent.geometry_diagram import GeometryDiagramUnavailable, geometry_diagram
from pals_agent.geometry_input import GeometryProblem
from pals_agent.synthetic_geometry import PROOF_SHA256

FIXTURE = (
    Path(__file__).resolve().parents[2] / "testdata/synthetic-geometry-v1/isosceles-request.json"
)


def request() -> dict:
    return json.loads(FIXTURE.read_text())


def test_diagram_keeps_ids_and_checked_declaration_binding() -> None:
    data = request()
    problem = GeometryProblem.parse(data)
    diagram = geometry_diagram(problem, proof_sha256=PROOF_SHA256)
    assert diagram["schema_version"] == "pals.diagram.v1"
    assert {point["id"] for point in diagram["points"]} == set(problem.role_ids.values())
    assert next(point for point in diagram["points"] if point["id"] == "m")["role"] == "derived"
    assert diagram["evidence_refs"] == [
        {
            "claim_id": "goal",
            "source_sha256": PROOF_SHA256,
            "declaration": "PalsGeometry.isosceles_midpoint_perpendicular",
        }
    ]
    data.pop("display_coordinates")
    assert geometry_diagram(GeometryProblem.parse(data), proof_sha256=PROOF_SHA256) == diagram


def test_rotated_translated_model_uses_supplied_display_coordinates() -> None:
    data = request()
    data["display_coordinates"] = {"a": [-1, 1], "b": [2, -1], "c": [2, 3], "m": [2, 1]}
    diagram = geometry_diagram(GeometryProblem.parse(data), proof_sha256=PROOF_SHA256)
    assert [(p["x"], p["y"]) for p in diagram["points"]] == [(-1, 1), (2, -1), (2, 3), (2, 1)]


@pytest.mark.parametrize(
    "coordinates",
    [
        {"a": [0, 3]},
        {"a": [1, 3], "b": [-2, 0], "c": [2, 0], "m": [0, 0]},
        {"a": [0, 3], "b": [-2, 0], "c": [2, 0], "m": [1, 0]},
        {"a": [0, 0], "b": [-2, 0], "c": [2, 0], "m": [0, 0]},
        {"a": [0, 30], "b": [-2, 0], "c": [2, 0], "m": [0, 0]},
        {"a": [0, 3], "b": [-0.0000001, 0], "c": [0.0000001, 0], "m": [0, 0]},
    ],
)
def test_drawing_cannot_contradict_the_declared_model(coordinates: dict) -> None:
    data = request()
    data["display_coordinates"] = coordinates
    problem = GeometryProblem.parse(data)
    assert problem.ready  # display checks never supply or remove mathematical premises
    with pytest.raises(GeometryDiagramUnavailable):
        geometry_diagram(problem, proof_sha256=PROOF_SHA256)


def test_unsupported_label_preserves_math_input_but_cannot_become_tex() -> None:
    data = request()
    data["objects"][0]["label"] = r"\input{secret}"
    problem = GeometryProblem.parse(data)
    assert problem.ready
    with pytest.raises(GeometryDiagramUnavailable, match="labels"):
        geometry_diagram(problem, proof_sha256=PROOF_SHA256)
