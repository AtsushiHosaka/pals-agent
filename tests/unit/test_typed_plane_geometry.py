from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import rfc8785

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_geometry_complex import validate_typed_geometry_complex_openmath_xml
from pals_agent.typed_math import validate_typed_math_openmath_xml
from pals_agent.typed_plane_geometry import (
    TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE,
    TYPED_PLANE_GEOMETRY_PROFILE,
    canonicalize_typed_plane_geometry_openmath_xml,
    validate_canonical_typed_plane_geometry_openmath_xml,
    validate_typed_plane_geometry_openmath_xml,
)
from pals_agent.typed_plane_geometry_manifest import (
    TypedPlaneGeometryManifestError,
    load_typed_plane_geometry_manifest,
    validate_typed_plane_geometry_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-plane-geometry-v1-authoring-manifest.proposal.json"
GENERATOR = ROOT / "pals-scripts/generate-typed-plane-geometry-v1-authoring-manifest.py"
DESIGN = ROOT / "docs/typed-plane-geometry-v1-design.md"
REGISTRY = (
    ROOT / "pals-agent/pals_agent/content_dictionaries/typed-plane-geometry-v1-registry.json"
)
WITNESSES = ROOT / "pals-agent/testdata/typed-plane-geometry-v1/plane-geometry-witnesses.lean"
OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"
TYPED = TYPED_PLANE_GEOMETRY_OPENMATH_CDBASE
PRIVATE_CD = "pals_plane_geometry"
DIGEST_INPUT = "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"


def _typed(name: str) -> str:
    return f'<OMS cdbase="{TYPED}" cd="{PRIVATE_CD}" name="{name}"/>'


def _standard(cd: str, name: str) -> str:
    return f'<OMS cdbase="{STANDARD}" cd="{cd}" name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _plane(name: str, *arguments: str) -> str:
    return _app(_typed(name), *arguments)


def _eq(left: str, right: str) -> str:
    return _app(_standard("relation1", "eq"), left, right)


def _declaration(name: str, sort: str) -> str:
    return f"<OMATTR><OMATP>{_typed('type')}{_typed(sort)}</OMATP><OMV name=\"{name}\"/></OMATTR>"


def _binding(declarations: list[tuple[str, str]], body: str) -> str:
    encoded = "".join(_declaration(name, sort) for name, sort in declarations)
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>{_typed("forall")}'
        f"<OMBVAR>{encoded}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


def _manifest() -> dict[str, object]:
    payload = load_typed_plane_geometry_manifest(MANIFEST, repository_root=ROOT)
    return payload


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": DIGEST_INPUT,
        "sha256": "sha256:" + hashlib.sha256(rfc8785.dumps(cast(Any, unsigned))).hexdigest(),
    }


def test_plane_geometry_profile_accepts_and_canonicalizes_every_sealed_card() -> None:
    payload = _manifest()
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_PLANE_GEOMETRY_PROFILE
    cards = payload["admitted_candidate_cards"]
    assert isinstance(cards, list) and len(cards) == 5
    assert {card["id"] for card in cards if isinstance(card, dict)} == {
        "typed_plane_distance_self_zero",
        "typed_plane_line_through_two_points",
        "typed_plane_circle_through_three_points",
        "typed_plane_perpendicular_symmetric",
        "typed_plane_parallel_symmetric",
    }
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        canonical = card["canonical_openmath_xml"]
        assert isinstance(raw, str) and isinstance(canonical, str)
        validate_typed_plane_geometry_openmath_xml(raw)
        assert canonicalize_typed_plane_geometry_openmath_xml(raw) == canonical
        assert validate_canonical_typed_plane_geometry_openmath_xml(canonical) == canonical
        steps = card["sketch_steps"]
        assert isinstance(steps, list) and 4 <= len(steps) <= 8


def test_plane_geometry_profile_keeps_scalar_vector_point_line_and_circle_exact() -> None:
    vector_identity = _binding(
        [("u", "Vector2")],
        _eq(
            _plane("vector_add", '<OMV name="u"/>', '<OMV name="u"/>'),
            _plane("vector_add", '<OMV name="u"/>', '<OMV name="u"/>'),
        ),
    )
    scalar_point_constructor = _binding(
        [("r", "Real")],
        _eq(
            _plane("point2", '<OMV name="r"/>', "<OMI>0</OMI>"),
            _plane("point2", '<OMV name="r"/>', "<OMI>0</OMI>"),
        ),
    )
    midpoint = _plane("midpoint", '<OMV name="p"/>', '<OMV name="q"/>')
    reflected_midpoint = _plane("reflect", midpoint, '<OMV name="line"/>')
    native_plane_operations = _binding(
        [("p", "Point2"), ("q", "Point2"), ("line", "Line2")],
        _eq(reflected_midpoint, reflected_midpoint),
    )
    non_collinear = _binding(
        [("p", "Point2"), ("q", "Point2"), ("r", "Point2")],
        _plane("non_collinear", '<OMV name="p"/>', '<OMV name="q"/>', '<OMV name="r"/>'),
    )
    scalar_point = _binding(
        [("p", "Point2")],
        _eq(_plane("distance_sq", '<OMV name="p"/>', "<OMI>2</OMI>"), "<OMI>0</OMI>"),
    )
    vector_point = _binding(
        [("u", "Vector2"), ("line", "Line2")],
        _plane("incident_point_line", '<OMV name="u"/>', '<OMV name="line"/>'),
    )
    circle_line = _binding(
        [("line", "Line2"), ("circle", "Circle2")],
        _plane("parallel", '<OMV name="line"/>', '<OMV name="circle"/>'),
    )
    point_vector_constructor = _binding(
        [("u", "Vector2")],
        _eq(
            _plane("point2", '<OMV name="u"/>', "<OMI>0</OMI>"),
            _plane("point2", '<OMV name="u"/>', "<OMI>0</OMI>"),
        ),
    )

    validate_typed_plane_geometry_openmath_xml(vector_identity)
    validate_typed_plane_geometry_openmath_xml(scalar_point_constructor)
    validate_typed_plane_geometry_openmath_xml(native_plane_operations)
    validate_typed_plane_geometry_openmath_xml(non_collinear)
    with pytest.raises(MathXMLValidationError, match=r"P2.*R"):
        validate_typed_plane_geometry_openmath_xml(scalar_point)
    with pytest.raises(MathXMLValidationError, match=r"P2.*V2"):
        validate_typed_plane_geometry_openmath_xml(vector_point)
    with pytest.raises(MathXMLValidationError, match=r"L2.*Circle2"):
        validate_typed_plane_geometry_openmath_xml(circle_line)
    with pytest.raises(MathXMLValidationError, match=r"R.*V2"):
        validate_typed_plane_geometry_openmath_xml(point_vector_constructor)


def test_plane_geometry_profile_rejects_complex_cdbase_inheritance_and_unknown_attributes() -> None:
    complex_value = _binding(
        [("p", "Point2")],
        _eq(
            _plane(
                "point2",
                _app(
                    _standard("complex1", "complex_cartesian"),
                    "<OMI>1</OMI>",
                    "<OMI>2</OMI>",
                ),
                "<OMI>0</OMI>",
            ),
            '<OMV name="p"/>',
        ),
    )
    direct = _binding(
        [("p", "Point2")],
        _eq(_plane("distance_sq", '<OMV name="p"/>', '<OMV name="p"/>'), "<OMI>0</OMI>"),
    )
    inherited = direct.replace(f' cdbase="{STANDARD}"', "", 1)
    unknown_attribute = direct.replace("<OMI>0</OMI>", '<OMI proof="forged">0</OMI>')

    with pytest.raises(MathXMLValidationError, match="complex1:complex_cartesian.*outside"):
        validate_typed_plane_geometry_openmath_xml(complex_value)
    with pytest.raises(MathXMLValidationError, match="OMS requires direct `cdbase`"):
        validate_typed_plane_geometry_openmath_xml(inherited)
    with pytest.raises(MathXMLValidationError, match="OMI.*attribute `proof`"):
        validate_typed_plane_geometry_openmath_xml(unknown_attribute)


def test_plane_geometry_profile_alpha_normalizes_typed_binders() -> None:
    first = _binding(
        [("p", "Point2")],
        _eq(_plane("distance_sq", '<OMV name="p"/>', '<OMV name="p"/>'), "<OMI>0</OMI>"),
    )
    second = first.replace('name="p"', 'name="q"')
    assert canonicalize_typed_plane_geometry_openmath_xml(first) == (
        canonicalize_typed_plane_geometry_openmath_xml(second)
    )


def test_plane_geometry_profile_does_not_widen_generic_or_existing_typed_profiles() -> None:
    payload = _manifest()
    cards = payload["admitted_candidate_cards"]
    assert isinstance(cards, list)
    raw = next(
        card["openmath_xml"]
        for card in cards
        if card["id"] == "typed_plane_distance_self_zero"
    )
    assert isinstance(raw, str)

    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_geometry_complex_openmath_xml(raw)


def test_plane_geometry_manifest_binds_current_design_registry_witness_and_generator(
    tmp_path: Path,
) -> None:
    payload = _manifest()
    profile = payload["profile"]
    assert isinstance(profile, dict)
    registry = profile["content_dictionary_bundle"]
    design = profile["profile_design"]
    assert isinstance(registry, dict) and isinstance(design, dict)
    assert registry["sha256"] == "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    assert design["sha256"] == "sha256:" + hashlib.sha256(DESIGN.read_bytes()).hexdigest()
    witnesses = payload["lean_witness_bundle"]
    assert isinstance(witnesses, dict)
    assert witnesses["sha256"] == "sha256:" + hashlib.sha256(WITNESSES.read_bytes()).hexdigest()

    output = tmp_path / "typed-plane-geometry.json"
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "pals-agent")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_plane_geometry_manifest_rejects_resealed_stale_bindings() -> None:
    original = json.loads(MANIFEST.read_text(encoding="utf-8"))

    canonical_tampered = copy.deepcopy(original)
    canonical_tampered["admitted_candidate_cards"][0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(canonical_tampered)
    with pytest.raises(TypedPlaneGeometryManifestError, match="canonical OpenMath"):
        validate_typed_plane_geometry_manifest(canonical_tampered, repository_root=ROOT)

    design_tampered = copy.deepcopy(original)
    design_tampered["profile"]["profile_design"]["sha256"] = "sha256:" + "0" * 64
    _reseal(design_tampered)
    with pytest.raises(TypedPlaneGeometryManifestError, match="artifact digest"):
        validate_typed_plane_geometry_manifest(design_tampered, repository_root=ROOT)

    witness_tampered = copy.deepcopy(original)
    witness_tampered["lean_witness_bundle"]["sha256"] = "sha256:" + "0" * 64
    _reseal(witness_tampered)
    with pytest.raises(TypedPlaneGeometryManifestError, match="artifact digest"):
        validate_typed_plane_geometry_manifest(witness_tampered, repository_root=ROOT)
