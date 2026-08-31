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

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_math import validate_typed_math_openmath_xml
from pals_agent.typed_ode import (
    TYPED_ODE_OPENMATH_CDBASE,
    TYPED_ODE_PROFILE,
    canonicalize_typed_ode_openmath_xml,
    validate_canonical_typed_ode_openmath_xml,
    validate_typed_ode_openmath_xml,
)
from pals_agent.typed_ode_manifest import (
    TypedOdeManifestError,
    validate_typed_ode_manifest,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-ode-v1-authoring-manifest.proposal.json"
REGISTRY = ROOT / "pals-agent/pals_agent/content_dictionaries/typed-ode-v1-registry.json"
DESIGN = ROOT / "docs/typed-ode-v1-design.md"
WITNESS = ROOT / "docs/typed-ode-v1-authoring-witnesses.lean"
SOURCE = ROOT / "docs/probability-ode-draft-candidates.json"
GENERATOR = ROOT / "pals-scripts/generate-typed-ode-v1-authoring-manifest.py"


def _manifest() -> dict[str, object]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _typed(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED_ODE_OPENMATH_CDBASE}" cd="{cd}" name="{name}"/>'


def _standard(cd: str, name: str) -> str:
    return f'<OMS cd="{cd}" name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _ode(name: str, *arguments: str) -> str:
    return _app(_typed("ode1", name), *arguments)


def _real(value: int) -> str:
    return _ode("of_int", f"<OMI>{value}</OMI>")


def _decl(name: str) -> str:
    return (
        f"<OMATTR><OMATP>{_typed('typed1', 'type')}{_typed('typed1', 'Real')}</OMATP>"
        f'<OMV name="{name}"/></OMATTR>'
    )


def _forall(name: str, body: str) -> str:
    return (
        f"<OMBIND>{_typed('typed1', 'forall')}<OMBVAR>{_decl(name)}</OMBVAR>"
        f"{body}</OMBIND>"
    )


def _function(body: str) -> str:
    return (
        f"<OMBIND>{_typed('ode1', 'lambda')}<OMBVAR>{_decl('t')}</OMBVAR>"
        f"{body}</OMBIND>"
    )


def _wrapped(body: str) -> str:
    return f'<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">{body}</OMOBJ>'


def _certificate(
    *,
    initial_function: str,
    derivative_function: str,
    applied_function: str | None = None,
    derivative_point: str = '<OMV name="x"/>',
    initial_time: str | None = None,
    include_initial: bool = True,
) -> str:
    applied_function = derivative_function if applied_function is None else applied_function
    equality = _app(
        _standard("relation1", "eq"),
        _ode("deriv_at", derivative_function, derivative_point),
        _ode("apply", applied_function, '<OMV name="x"/>'),
    )
    global_ode = _forall("x", equality)
    if not include_initial:
        return _wrapped(global_ode)
    initial = _ode(
        "initial_value",
        initial_function,
        initial_time or _real(0),
        _real(0),
    )
    return _wrapped(_app(_standard("logic1", "and"), initial, global_ode))


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": (
            "RFC 8785 canonical JSON serialization of this object "
            "with manifest_digest omitted"
        ),
        "sha256": "sha256:" + hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest(),
    }


def test_typed_ode_accepts_and_canonicalizes_all_ten_source_cards() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and len(cards) == 10
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        assert isinstance(raw, str)
        validate_typed_ode_openmath_xml(raw)
        canonical = canonicalize_typed_ode_openmath_xml(raw)
        assert card["canonical_openmath_xml"] == canonical
        assert validate_canonical_typed_ode_openmath_xml(canonical) == canonical


def test_typed_ode_manifest_is_sealed_and_binds_current_artifacts() -> None:
    payload = _manifest()
    validate_typed_ode_manifest(payload, repository_root=ROOT)
    assert payload["schema_version"] == "pals.typed-ode-v1-sealed-manifest.v1"
    assert payload["status"] == "sealed_local_authoring_revision_not_admitted"
    assert payload["admitted_card_count"] == 10
    assert payload["excluded_source_card_count"] == 0
    profile = payload["profile"]
    assert isinstance(profile, dict)
    assert profile["id"] == TYPED_ODE_PROFILE
    assert profile["registry_sha256"] == (
        "sha256:" + hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    )
    assert profile["design_sha256"] == "sha256:" + hashlib.sha256(DESIGN.read_bytes()).hexdigest()
    source = payload["source_catalog"]
    assert isinstance(source, dict)
    assert source["sha256"] == "sha256:" + hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    receipt = payload["lean_witness_bundle"]
    assert isinstance(receipt, dict)
    witness_text = WITNESS.read_text(encoding="utf-8")
    assert receipt["sha256"] == "sha256:" + hashlib.sha256(WITNESS.read_bytes()).hexdigest()
    cards = payload["cards"]
    assert isinstance(cards, list)
    for card in cards:
        assert isinstance(card, dict)
        assert card["source_candidate_id"] == card["id"]
        assert card["openmath_profile"] == TYPED_ODE_PROFILE
        assert card["profile_validation_status"] == "validated_local_typed_ode_v1_sealed"
        assert card["compiler_receipt_status"] == "verified_local_pinned_workspace"
        steps = card["sketch_steps"]
        assert isinstance(steps, list) and 4 <= len(steps) <= 8
        target = card["lean_target"]
        proof = card["lean_witness"]
        assert isinstance(target, str) and isinstance(proof, str)
        assert f"{target} := {proof}" in witness_text


def test_typed_ode_manifest_rejects_digest_and_artifact_staleness() -> None:
    stale_digest = copy.deepcopy(_manifest())
    cards = stale_digest["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_statement"] = "mutated"
    with pytest.raises(TypedOdeManifestError, match="digest"):
        validate_typed_ode_manifest(stale_digest, repository_root=ROOT)

    stale_registry = copy.deepcopy(_manifest())
    profile = stale_registry["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(stale_registry)
    with pytest.raises(TypedOdeManifestError, match="artifact digest"):
        validate_typed_ode_manifest(stale_registry, repository_root=ROOT)


def test_typed_ode_manifest_is_current_generator_output(tmp_path: Path) -> None:
    output = tmp_path / "typed-ode.json"
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


def test_typed_ode_lean_witnesses_compile_in_the_pinned_workspace() -> None:
    completed = subprocess.run(
        ["lake", "env", "lean", "../../docs/typed-ode-v1-authoring-witnesses.lean"],
        cwd=ROOT / "pals-agent/lean-workspace",
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_typed_ode_alpha_normalizes_parameters_and_function_binders() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    raw = cards[0]["openmath_xml"]
    assert isinstance(raw, str)
    renamed = raw.replace('name="C"', 'name="A"').replace('name="k"', 'name="b"').replace(
        'name="t"', 'name="u"'
    )
    assert canonicalize_typed_ode_openmath_xml(raw) == canonicalize_typed_ode_openmath_xml(renamed)


def test_typed_ode_does_not_widen_generic_or_other_typed_profiles() -> None:
    cards = _manifest()["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    raw = cards[0]["openmath_xml"]
    assert isinstance(raw, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(raw)
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(raw)


def test_typed_ode_rejects_missing_or_mismatched_initial_value_and_domain() -> None:
    zero = _function(_real(0))
    identity = _function('<OMV name="t"/>')
    omitted_initial = _certificate(
        initial_function=zero, derivative_function=zero, include_initial=False
    )
    mismatched_function = _certificate(initial_function=zero, derivative_function=identity)
    mismatched_applied_function = _certificate(
        initial_function=zero, derivative_function=zero, applied_function=identity
    )
    nonzero_initial_time = _certificate(
        initial_function=zero, derivative_function=zero, initial_time=_real(1)
    )
    wrong_domain_point = _certificate(
        initial_function=zero, derivative_function=zero, derivative_point=_real(0)
    )
    for invalid in (
        omitted_initial,
        mismatched_function,
        mismatched_applied_function,
        nonzero_initial_time,
        wrong_domain_point,
    ):
        with pytest.raises(MathXMLValidationError):
            validate_typed_ode_openmath_xml(invalid)


def test_typed_ode_rejects_function_scalar_confusion_unknown_attributes_and_inheritance() -> None:
    zero = _function(_real(0))
    scalar_as_function = _certificate(initial_function=zero, derivative_function='<OMV name="x"/>')
    with pytest.raises(MathXMLValidationError, match="RealFunction"):
        validate_typed_ode_openmath_xml(scalar_as_function)

    raw = _certificate(initial_function=zero, derivative_function=zero)
    unknown_attribute = raw.replace('version="2.0"', 'version="2.0" unknown="no"', 1)
    inherited_cdbase = raw.replace(f' cdbase="{TYPED_ODE_OPENMATH_CDBASE}"', "", 1)
    for invalid in (unknown_attribute, inherited_cdbase):
        with pytest.raises(MathXMLValidationError):
            validate_typed_ode_openmath_xml(invalid)
