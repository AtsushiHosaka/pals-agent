from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import rfc8785

from pals_agent.typed_geometry_complex import (
    TYPED_GEOMETRY_COMPLEX_PROFILE,
    canonicalize_typed_geometry_complex_openmath_xml,
)
from pals_agent.typed_geometry_complex_manifest import (
    TypedGeometryComplexManifestError,
    load_typed_geometry_complex_manifest,
    validate_typed_geometry_complex_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-geometry-complex-v1-authoring-manifest.proposal.json"
GENERATOR = ROOT / "pals-scripts/generate-typed-geometry-complex-v1-authoring-manifest.py"
REGISTRY = (
    ROOT / "pals-agent/pals_agent/content_dictionaries/typed-geometry-complex-v1-registry.json"
)
DESIGN = ROOT / "docs/vector-complex-typed-extension.md"
WITNESSES = (
    ROOT / "pals-agent/testdata/typed-geometry-complex-v1/vector-complex-phase-a-witnesses.lean"
)
_DIGEST_INPUT = "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": _DIGEST_INPUT,
        "sha256": "sha256:" + hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest(),
    }


def test_phase_a_manifest_binds_actual_profile_design_registry_and_witnesses() -> None:
    payload = load_typed_geometry_complex_manifest(MANIFEST, repository_root=ROOT)

    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_GEOMETRY_COMPLEX_PROFILE
    bundle = profile["content_dictionary_bundle"]
    assert isinstance(bundle, dict)
    assert bundle["sha256"] == "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    design = profile["profile_design"]
    assert isinstance(design, dict)
    assert design["sha256"] == "sha256:" + hashlib.sha256(DESIGN.read_bytes()).hexdigest()
    witnesses = payload["lean_witness_bundle"]
    assert isinstance(witnesses, dict)
    assert witnesses["sha256"] == "sha256:" + hashlib.sha256(WITNESSES.read_bytes()).hexdigest()

    cards = payload["admitted_candidate_cards"]
    assert isinstance(cards, list) and len(cards) == 8
    assert {card["id"] for card in cards if isinstance(card, dict)} == {
        "typed_vector2_component_addition",
        "typed_vector2_scalar_multiple",
        "typed_vector2_dot_product_orthogonality",
        "typed_vector2_triangle_area_determinant",
        "typed_complex_cartesian_multiplication",
        "typed_complex_conjugate_norm_square",
        "typed_complex_multiply_i_quarter_turn",
        "typed_complex_argument_quadrant_two",
    }
    for card in cards:
        assert isinstance(card, dict)
        assert (
            canonicalize_typed_geometry_complex_openmath_xml(card["openmath_xml"])
            == card["canonical_openmath_xml"]
        )
        assert 4 <= len(card["sketch_steps"]) <= 8

    deferred = payload["deferred_backlog_cards"]
    assert isinstance(deferred, list) and len(deferred) == 4
    assert {entry["id"] for entry in deferred if isinstance(entry, dict)} == {
        "geometry_line_through_two_points",
        "geometry_circle_through_three_points",
        "geometry_perpendicular_bisector_locus",
        "geometry_reflection_in_line",
    }


def test_manifest_is_reproducible_from_the_generator(tmp_path: Path) -> None:
    output = tmp_path / "typed-geometry-complex.json"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "pals-agent")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_manifest_rejects_resealed_canonical_and_design_binding_tampering() -> None:
    original = json.loads(MANIFEST.read_text(encoding="utf-8"))

    canonical_tampered = copy.deepcopy(original)
    canonical_tampered["admitted_candidate_cards"][0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(canonical_tampered)
    with pytest.raises(TypedGeometryComplexManifestError, match="canonical OpenMath"):
        validate_typed_geometry_complex_manifest(canonical_tampered, repository_root=ROOT)

    design_tampered = copy.deepcopy(original)
    design_tampered["profile"]["profile_design"]["sha256"] = "sha256:" + "0" * 64
    _reseal(design_tampered)
    with pytest.raises(TypedGeometryComplexManifestError, match="artifact digest"):
        validate_typed_geometry_complex_manifest(design_tampered, repository_root=ROOT)

    phase_b_tampered = copy.deepcopy(original)
    phase_b_tampered["deferred_backlog_cards"][0]["id"] = "typed_vector2_component_addition"
    _reseal(phase_b_tampered)
    with pytest.raises(TypedGeometryComplexManifestError, match="deferred phase-B"):
        validate_typed_geometry_complex_manifest(phase_b_tampered, repository_root=ROOT)
