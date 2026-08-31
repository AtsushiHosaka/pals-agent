from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import rfc8785

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_finite_graph import (
    TYPED_FINITE_GRAPH_OPENMATH_CDBASE,
    canonicalize_typed_finite_graph_openmath_xml,
    validate_canonical_typed_finite_graph_openmath_xml,
    validate_typed_finite_graph_openmath_xml,
)
from pals_agent.typed_math import validate_typed_math_openmath_xml

_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _ROOT / "docs/typed-finite-graph-v1-authoring-manifest.proposal.json"
_DESIGN = _ROOT / "docs/typed-finite-graph-profile-v1-design.md"
_WITNESS = _ROOT / "docs/typed-finite-graph-v1-authoring-witnesses.proposal.lean"
_GENERATOR = _ROOT / "pals-scripts/generate-typed-finite-graph-v1-authoring-manifest-proposal.py"
_STANDARD = "http://www.openmath.org/cd"


def _manifest() -> dict[str, object]:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _cards() -> dict[str, str]:
    cards = _manifest()["admitted_candidate_cards"]
    assert isinstance(cards, list)
    return {card["id"]: card["openmath_xml"] for card in cards if isinstance(card, dict)}


def _typed(name: str) -> str:
    return (
        f'<OMS cdbase="{TYPED_FINITE_GRAPH_OPENMATH_CDBASE}" cd="pals_typed_graph" name="{name}"/>'
    )


def _std(cd: str, name: str) -> str:
    return f'<OMS cdbase="{_STANDARD}" cd="{cd}" name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _declaration(name: str, sort: str) -> str:
    return f'<OMATTR><OMATP>{_typed("type")}{sort}</OMATP><OMV name="{name}"/></OMATTR>'


def _binding(declarations: str, body: str) -> str:
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        f"{_typed('forall')}<OMBVAR>{declarations}</OMBVAR>{body}</OMBIND></OMOBJ>"
    )


def _graph_sort() -> str:
    return _typed("FinSimpleGraph")


def _indexed_sort(name: str, graph: str) -> str:
    return _app(_typed(name), f'<OMV name="{graph}"/>')


def _eq(left: str, right: str) -> str:
    return _app(_std("relation1", "eq"), left, right)


def test_graph_profile_accepts_and_canonicalizes_the_five_safe_cards() -> None:
    cards = _cards()
    assert len(cards) == 5
    for raw in cards.values():
        validate_typed_finite_graph_openmath_xml(raw)
        canonical = canonicalize_typed_finite_graph_openmath_xml(raw)
        assert validate_canonical_typed_finite_graph_openmath_xml(canonical) == canonical


def test_graph_profile_sealed_manifest_binds_strategy_sketch_and_evidence() -> None:
    payload = _manifest()
    registry = (
        _ROOT / "pals-agent/pals_agent/content_dictionaries/typed-finite-graph-v1-registry.json"
    )
    assert payload["schema_version"] == "pals.typed-finite-graph-v1-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["seal"] == {
        "scope": "local typed-finite-graph authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-finite-graph-v1-local-r1",
    }
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == "typed-finite-graph-v1"
    assert profile["validator_status"] == "implemented_isolated_profile"
    bundle = profile["content_dictionary_bundle"]
    assert isinstance(bundle, dict)
    assert bundle["relative_path"] == (
        "pals-agent/pals_agent/content_dictionaries/typed-finite-graph-v1-registry.json"
    )
    assert bundle["sha256"] == "sha256:" + hashlib.sha256(registry.read_bytes()).hexdigest()
    design = profile["profile_design"]
    assert isinstance(design, dict)
    assert design["sha256"] == "sha256:" + hashlib.sha256(_DESIGN.read_bytes()).hexdigest()
    receipt = payload["lean_witness_bundle"]
    assert isinstance(receipt, dict)
    assert receipt["sha256"] == "sha256:" + hashlib.sha256(_WITNESS.read_bytes()).hexdigest()

    cards = payload["admitted_candidate_cards"]
    assert isinstance(cards, list) and len(cards) == 5
    witness_text = _WITNESS.read_text(encoding="utf-8")
    for card in cards:
        assert isinstance(card, dict)
        canonical = canonicalize_typed_finite_graph_openmath_xml(card["openmath_xml"])
        assert card["canonical_openmath_xml"] == canonical
        assert card["proof_strategy_sha256"] == (
            "sha256:" + hashlib.sha256(card["proof_strategy"].encode("utf-8")).hexdigest()
        )
        assert card["sketch_steps_sha256"] == (
            "sha256:" + hashlib.sha256(rfc8785.dumps(card["sketch_steps"])).hexdigest()
        )
        assert card["signature_trace_sha256"] == (
            "sha256:" + hashlib.sha256(rfc8785.dumps(card["signature_trace"])).hexdigest()
        )
        assert isinstance(card["sketch_steps"], list) and 4 <= len(card["sketch_steps"]) <= 8
        lean = card["lean"]
        assert isinstance(lean, dict)
        assert lean["target_sha256"] == (
            "sha256:" + hashlib.sha256(lean["target"].encode("utf-8")).hexdigest()
        )
        assert lean["witness_sha256"] == (
            "sha256:" + hashlib.sha256(lean["witness"].encode("utf-8")).hexdigest()
        )
        assert f"-- manifest card: {card['id']}\n{lean['witness']}" in witness_text

    unsigned = dict(payload)
    digest = unsigned.pop("manifest_digest")
    assert isinstance(digest, dict)
    assert digest["sha256"] == "sha256:" + hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest()


def test_graph_profile_sealed_manifest_is_current_generator_output(tmp_path: Path) -> None:
    output = tmp_path / "typed-finite-graph-sealed.json"
    completed = subprocess.run(
        [sys.executable, str(_GENERATOR), "--output", str(output)],
        cwd=_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == _MANIFEST.read_bytes()


def test_graph_profile_alpha_normalizes_graph_and_trail_binders() -> None:
    raw = _cards()["typed_finite_graph_v1_euler_trail_odd_degree_necessity"]
    renamed = raw.replace('name="G"', 'name="H"').replace('name="t"', 'name="p"')

    assert canonicalize_typed_finite_graph_openmath_xml(raw) == (
        canonicalize_typed_finite_graph_openmath_xml(renamed)
    )


def test_graph_profile_does_not_widen_generic_or_base_typed_math() -> None:
    raw = _cards()["typed_finite_graph_v1_handshaking"]

    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError, match="typed-math-v1 OMBIND"):
        validate_typed_math_openmath_xml(raw)


def test_graph_profile_rejects_dependent_carrier_mismatches() -> None:
    declarations = (
        _declaration("G", _graph_sort())
        + _declaration("H", _graph_sort())
        + _declaration("v", _indexed_sort("Vertex", "G"))
        + _declaration("L", _indexed_sort("VertexClass", "G"))
        + _declaration("R", _indexed_sort("VertexClass", "H"))
        + _declaration("t", _indexed_sort("Trail", "G"))
    )
    degree_other_graph = _binding(
        declarations,
        _eq(_app(_typed("degree"), '<OMV name="H"/>', '<OMV name="v"/>'), "<OMI>0</OMI>"),
    )
    partition_other_graph = _binding(
        declarations,
        _app(
            _typed("proper_bipartition"),
            '<OMV name="G"/>',
            '<OMV name="L"/>',
            '<OMV name="R"/>',
        ),
    )
    trail_other_graph = _binding(
        declarations,
        _app(_typed("is_euler_trail"), '<OMV name="H"/>', '<OMV name="t"/>'),
    )

    with pytest.raises(MathXMLValidationError, match=r"Vertex\(H\).+Vertex\(G\)"):
        validate_typed_finite_graph_openmath_xml(degree_other_graph)
    with pytest.raises(MathXMLValidationError, match=r"VertexClass\(G\).+VertexClass\(H\)"):
        validate_typed_finite_graph_openmath_xml(partition_other_graph)
    with pytest.raises(MathXMLValidationError, match=r"Trail\(H\).+Trail\(G\)"):
        validate_typed_finite_graph_openmath_xml(trail_other_graph)


def test_graph_profile_rejects_graph1_negative_literals_and_inherited_cdbases() -> None:
    graph1 = _binding(
        _declaration("G", _graph_sort()),
        _eq(
            '<OMS cdbase="http://www.openmath.org/cd" cd="graph1" name="graph"/>',
            '<OMV name="G"/>',
        ),
    )
    negative = _binding(
        _declaration("G", _graph_sort()),
        _eq(_app(_typed("edge_count"), '<OMV name="G"/>'), "<OMI>-1</OMI>"),
    )
    inherited = (
        _cards()["typed_finite_graph_v1_handshaking"]
        .replace(f' cdbase="{TYPED_FINITE_GRAPH_OPENMATH_CDBASE}"', "")
        .replace(
            '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">',
            '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0" '
            f'cdbase="{TYPED_FINITE_GRAPH_OPENMATH_CDBASE}">',
        )
    )

    with pytest.raises(MathXMLValidationError, match="outside typed-finite-graph-v1"):
        validate_typed_finite_graph_openmath_xml(graph1)
    with pytest.raises(MathXMLValidationError, match="must be nonnegative"):
        validate_typed_finite_graph_openmath_xml(negative)
    with pytest.raises(MathXMLValidationError, match="OMOBJ.*attribute `cdbase`"):
        validate_typed_finite_graph_openmath_xml(inherited)


def test_graph_profile_hard_rejects_unverified_euler_and_bipartition_converses() -> None:
    declarations = (
        _declaration("G", _graph_sort())
        + _declaration("L", _indexed_sort("VertexClass", "G"))
        + _declaration("R", _indexed_sort("VertexClass", "G"))
        + _declaration("t", _indexed_sort("Trail", "G"))
    )
    euler_existence = _binding(
        declarations,
        _app(
            _std("logic1", "equivalent"),
            _app(_typed("has_euler_trail"), '<OMV name="G"/>'),
            _app(_typed("nonisolated_connected"), '<OMV name="G"/>'),
        ),
    )
    full_bipartition = _binding(
        declarations,
        _app(
            _std("logic1", "equivalent"),
            _app(_typed("bipartite"), '<OMV name="G"/>'),
            _app(
                _typed("proper_bipartition"),
                '<OMV name="G"/>',
                '<OMV name="L"/>',
                '<OMV name="R"/>',
            ),
        ),
    )
    connected_euler_condition = _binding(
        declarations,
        _app(
            _std("logic1", "implies"),
            _app(_typed("is_euler_trail"), '<OMV name="G"/>', '<OMV name="t"/>'),
            _app(_typed("connected"), '<OMV name="G"/>'),
        ),
    )

    with pytest.raises(MathXMLValidationError, match="Euler-existence theorem"):
        validate_typed_finite_graph_openmath_xml(euler_existence)
    with pytest.raises(MathXMLValidationError, match="full bipartition equivalence"):
        validate_typed_finite_graph_openmath_xml(full_bipartition)
    with pytest.raises(MathXMLValidationError, match="nonisolated_connected, not connected"):
        validate_typed_finite_graph_openmath_xml(connected_euler_condition)


def test_graph_profile_accepts_well_typed_bipartition_syntax_without_a_converse() -> None:
    xml = _binding(
        _declaration("G", _graph_sort())
        + _declaration("L", _indexed_sort("VertexClass", "G"))
        + _declaration("R", _indexed_sort("VertexClass", "G")),
        _app(
            _typed("proper_bipartition"),
            '<OMV name="G"/>',
            '<OMV name="L"/>',
            '<OMV name="R"/>',
        ),
    )

    validate_typed_finite_graph_openmath_xml(xml)
