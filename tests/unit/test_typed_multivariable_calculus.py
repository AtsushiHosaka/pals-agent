# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_multivariable_calculus import (
    TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE,
    canonicalize_typed_multivariable_calculus_openmath_xml,
    validate_canonical_typed_multivariable_calculus_openmath_xml,
    validate_typed_multivariable_calculus_openmath_xml,
)
from pals_agent.typed_real_analysis import validate_typed_real_analysis_openmath_xml

_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _ROOT / "docs" / "typed-multivariable-calculus-v1-sealed-manifest.proposal.json"
_DESIGN = _ROOT / "docs" / "typed-multivariable-calculus-v1-design.md"
_WITNESS = _ROOT / "docs" / "typed-multivariable-calculus-v1-authoring-witnesses.lean"
_REGISTRY = (
    _ROOT
    / "pals-agent"
    / "pals_agent"
    / "content_dictionaries"
    / "typed-multivariable-calculus-v1-registry.json"
)
_GENERATOR = _ROOT / "pals-scripts" / "generate-typed-multivariable-calculus-v1-authoring-manifest.py"


def _manifest() -> dict[str, object]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _typed_oms(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED_MULTIVARIABLE_CALCULUS_OPENMATH_CDBASE}" cd="{cd}" name="{name}"/>'


def _declaration(name: str, sort: str) -> str:
    return (
        f"<OMATTR><OMATP>{_typed_oms('typed1', 'type')}{sort}</OMATP>"
        f'<OMV name="{name}"/></OMATTR>'
    )


def _binding(declarations: str, body: str) -> str:
    return (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        f"{_typed_oms('typed1', 'forall')}<OMBVAR>{declarations}</OMBVAR>{body}"
        "</OMBIND></OMOBJ>"
    )


def _app(cd: str, name: str, *arguments: str, typed: bool = False) -> str:
    operator = _typed_oms(cd, name) if typed else f'<OMS cd="{cd}" name="{name}"/>'
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def test_sealed_cards_validate_canonicalize_and_bind_all_evidence() -> None:
    payload = _manifest()
    assert payload["schema_version"] == "pals.typed-multivariable-calculus-v1-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["seal"] == {
        "scope": "local typed multivariable-calculus authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-multivariable-calculus-v1-local-r1",
    }
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["profile_design_sha256"] == "sha256:" + hashlib.sha256(
        _DESIGN.read_bytes()
    ).hexdigest()
    assert profile["registry_digest"] == "sha256:" + hashlib.sha256(_REGISTRY.read_bytes()).hexdigest()
    receipt = payload["lean_receipt"]
    assert isinstance(receipt, dict)
    assert receipt["witness_file_sha256"] == "sha256:" + hashlib.sha256(
        _WITNESS.read_bytes()
    ).hexdigest()
    witness = _WITNESS.read_text(encoding="utf-8")
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 6
    seen: set[str] = set()
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        validate_typed_multivariable_calculus_openmath_xml(raw)
        canonical = canonicalize_typed_multivariable_calculus_openmath_xml(raw)
        assert canonical not in seen
        seen.add(canonical)
        assert card["canonical_openmath_xml"] == canonical
        assert validate_canonical_typed_multivariable_calculus_openmath_xml(canonical) == canonical
        assert card["openmath_xml_sha256"] == "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
        assert card["canonical_openmath_xml_sha256"] == "sha256:" + hashlib.sha256(
            canonical.encode()
        ).hexdigest()
        steps = card["sketch_steps"]
        assert isinstance(steps, list) and 4 <= len(steps) <= 8
        assert all(isinstance(step, str) and step.strip() for step in steps)
        witness_text = card["lean_witness"]
        assert isinstance(witness_text, str)
        assert f"-- manifest card: {card['id']}\n{witness_text}" in witness
    unsigned = dict(payload)
    digest = unsigned.pop("manifest_payload_sha256")
    actual = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest == "sha256:" + hashlib.sha256(actual.encode("utf-8")).hexdigest()


def test_generator_is_stale_if_checked_manifest_or_evidence_changes(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(_GENERATOR), "--output", str(output)],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == _MANIFEST.read_bytes()


def test_pinned_lean_witnesses_compile() -> None:
    result = subprocess.run(
        ["lake", "env", "lean", "../../docs/typed-multivariable-calculus-v1-authoring-witnesses.lean"],
        cwd=_ROOT / "pals-agent" / "lean-workspace",
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_profile_rejects_sort_errors_and_deferred_vocabulary() -> None:
    real = _typed_oms("typed1", "Real")
    real2 = _typed_oms("multicalc1", "Real2")
    scalar_where_point_required = _binding(
        _declaration("f", _typed_oms("multicalc1", "Real2Function")),
        _app(
            "multicalc1",
            "partial_x_at",
            '<OMV name="f"/>',
            _app("multicalc1", "of_int", "<OMI>0</OMI>", typed=True),
            _app("multicalc1", "of_int", "<OMI>0</OMI>", typed=True),
            typed=True,
        ),
    )
    with pytest.raises(MathXMLValidationError, match="Real2"):
        validate_typed_multivariable_calculus_openmath_xml(scalar_where_point_required)

    lambda2_returns_pair = _binding(
        _declaration("a", real),
        _app(
            "relation1",
            "eq",
            f"<OMBIND>{_typed_oms('multicalc1', 'lambda2')}<OMBVAR>"
            f"{_declaration('p', real2)}</OMBVAR>"
            f"{_app('multicalc1', 'pair', '<OMV name=\"a\"/>', '<OMV name=\"a\"/>', typed=True)}"
            "</OMBIND>",
            f"<OMBIND>{_typed_oms('multicalc1', 'lambda2')}<OMBVAR>"
            f"{_declaration('q', real2)}</OMBVAR>"
            f"{_app('multicalc1', 'pair', '<OMV name=\"a\"/>', '<OMV name=\"a\"/>', typed=True)}"
            "</OMBIND>",
        ),
    )
    with pytest.raises(MathXMLValidationError, match="lambda2 body"):
        validate_typed_multivariable_calculus_openmath_xml(lambda2_returns_pair)

    for deferred in (
        "gradient",
        "hessian",
        "local_extremum",
        "partial_xy_at",
        "double_integral",
        "iterated_integral",
        "fubini",
        "change_of_variables",
    ):
        unknown = _binding(
            _declaration("f", _typed_oms("multicalc1", "Real2Function")),
            _app("multicalc1", deferred, '<OMV name="f"/>', typed=True),
        )
        with pytest.raises(MathXMLValidationError, match="outside typed-multivariable-calculus-v1"):
            validate_typed_multivariable_calculus_openmath_xml(unknown)


def test_other_profiles_cannot_treat_multivariable_xml_as_their_own() -> None:
    payload = _manifest()
    cards = payload["cards"]
    assert isinstance(cards, list) and cards
    raw = cards[0]["openmath_xml"]
    assert isinstance(raw, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_real_analysis_openmath_xml(raw)
