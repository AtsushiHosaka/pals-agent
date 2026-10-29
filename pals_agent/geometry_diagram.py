"""Mathematical content producer for T3's working pals.diagram.v1 contract.

Transport, validation, TeX generation, persistence and rendering remain T3-owned.
Only a safe subset of its labels is emitted. Drawing checks establish display
consistency only, and never establish mathematical hypotheses or proof status.
"""

from __future__ import annotations

import math
import re
from typing import Any

from pals_agent.geometry_input import GeometryProblem

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}\Z", re.ASCII)
_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9]{0,31}\Z", re.ASCII)


class GeometryDiagramUnavailable(ValueError):
    """Proof remains readable when the diagram cannot preserve the input model."""


def geometry_diagram(problem: GeometryProblem, *, proof_sha256: str) -> dict[str, Any]:
    if not problem.ready:
        raise GeometryDiagramUnavailable("unconfirmed_geometry")
    data = problem.to_data()
    objects = data["objects"]
    claim_id = data["conclusion"]["id"]
    if not _ID.fullmatch(claim_id) or any(not _ID.fullmatch(p["id"]) for p in objects):
        raise GeometryDiagramUnavailable("object_ids_outside_diagram_v1")
    if any(not _LABEL.fullmatch(p["label"]) for p in objects):
        raise GeometryDiagramUnavailable("labels_outside_producer_subset")
    roles = problem.role_ids
    coordinates = data.get("display_coordinates") or {
        roles["A"]: [0.0, 3.0],
        roles["B"]: [-2.0, 0.0],
        roles["C"]: [2.0, 0.0],
        roles["M"]: [0.0, 0.0],
    }
    if set(coordinates) != set(roles.values()):
        raise GeometryDiagramUnavailable("incomplete_display_coordinates")
    if any(abs(v) > 10 for point in coordinates.values() for v in point):
        raise GeometryDiagramUnavailable("display_coordinates_outside_diagram_v1")
    # T3 emits six decimal places; inspect that actual drawing rather than a
    # higher-precision shape that could collapse during source generation.
    coordinates = {key: [round(float(v), 6) for v in pair] for key, pair in coordinates.items()}
    a, b, c, m = (coordinates[roles[role]] for role in ("A", "B", "C", "M"))

    def close(x: float, y: float) -> bool:
        return math.isclose(x, y, abs_tol=1e-8, rel_tol=1e-8)

    area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if (
        close(area, 0)
        or not close(math.dist(a, b), math.dist(a, c))
        or not all(close(m[i], (b[i] + c[i]) / 2) for i in (0, 1))
    ):
        raise GeometryDiagramUnavailable("display_inconsistent_with_declared_geometry")
    occupied = {p["id"] for p in objects}
    segments: list[dict[str, str]] = []
    for start, end, role in (
        ("A", "B", "given"),
        ("A", "C", "given"),
        ("B", "C", "given"),
        ("A", "M", "derived"),
    ):
        index = len(segments) + 1
        identity = f"geometry_segment_{index}"
        while identity in occupied:
            index += 1
            identity = f"geometry_segment_{index}"
        occupied.add(identity)
        segments.append({"id": identity, "start": roles[start], "end": roles[end], "role": role})
    return {
        "schema_version": "pals.diagram.v1",
        "id": "isosceles_midpoint",
        "kind": "geometry",
        "alt": "Isosceles triangle with its base midpoint and the segment from apex to midpoint. "
        "Coordinates illustrate the declared model; rendering does not verify the proof.",
        "evidence_refs": [
            {
                "claim_id": claim_id,
                "source_sha256": proof_sha256,
                "declaration": "PalsGeometry.isosceles_midpoint_perpendicular",
            }
        ],
        "points": [
            {
                "id": point["id"],
                "label": point["label"],
                "x": float(coordinates[point["id"]][0]),
                "y": float(coordinates[point["id"]][1]),
                "role": "derived" if point["role"] == "M" else "given",
            }
            for point in objects
        ],
        "segments": segments,
        "circles": [],
    }
