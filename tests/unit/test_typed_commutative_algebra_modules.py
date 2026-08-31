"""Contract tests for the isolated CA-2 module-theory profile."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_commutative_algebra_modules import (
    TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE as TYPED,
)
from pals_agent.typed_commutative_algebra_modules import (
    canonicalize_typed_commutative_algebra_modules_openmath_xml,
    validate_canonical_typed_commutative_algebra_modules_openmath_xml,
    validate_typed_commutative_algebra_modules_openmath_xml,
)
from pals_agent.typed_commutative_algebra_modules_manifest import (
    TypedCommutativeAlgebraModulesManifestError,
    load_typed_commutative_algebra_modules_manifest,
    validate_typed_commutative_algebra_modules_manifest,
)
from pals_agent.typed_math import validate_typed_math_openmath_xml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-commutative-algebra-modules-v1-sealed-manifest.proposal.json"
WITNESS = ROOT / "docs/typed-commutative-algebra-modules-v1-authoring-witnesses.lean"
GENERATOR = (
    ROOT / "pals-scripts/generate-typed-commutative-algebra-modules-v1-authoring-manifest.py"
)
OPENMATH = "http://www.openmath.org/OpenMath"
STANDARD = "http://www.openmath.org/cd"


def _typed(cd: str, name: str) -> str:
    return f'<OMS cdbase="{TYPED}" cd="{cd}" name="{name}"/>'


def _var(name: str) -> str:
    return f'<OMV name="{name}"/>'


def _app(operator: str, *arguments: str) -> str:
    return f"<OMA>{operator}{''.join(arguments)}</OMA>"


def _decl(name: str, sort: str) -> str:
    return f"<OMATTR><OMATP>{_typed('typed1', 'type')}{sort}</OMATP>{_var(name)}</OMATTR>"


def _module_type(ring: str) -> str:
    return _app(_typed("module1", "Module"), _var(ring))


def _submodule_type(ring: str, module: str) -> str:
    return _app(_typed("module1", "Submodule"), _var(ring), _var(module))


def _map_type(ring: str, source: str, target: str) -> str:
    return _app(_typed("module1", "LinearMap"), _var(ring), _var(source), _var(target))


def _bind(declarations: list[str], body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        f"{_typed('typed1', 'forall')}<OMBVAR>{''.join(declarations)}</OMBVAR>"
        f"{body}</OMBIND></OMOBJ>"
    )


def _module(name: str, *arguments: str) -> str:
    return _app(_typed("module1", name), *arguments)


def _eq(left: str, right: str) -> str:
    return _app(
        f'<OMS cdbase="{STANDARD}" cd="relation1" name="eq"/>',
        left,
        right,
    )


def _payload() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256", None)
    payload["manifest_payload_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def test_module_manifest_is_current_and_all_cards_use_actual_c14n() -> None:
    payload = load_typed_commutative_algebra_modules_manifest(MANIFEST, repository_root=ROOT)
    assert payload["admitted_card_count"] == 24
    assert payload["excluded_card_count"] == 4
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 24
    witness = WITNESS.read_text(encoding="utf-8")
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        canonical = card["canonical_openmath_xml"]
        assert isinstance(raw, str) and isinstance(canonical, str)
        assert canonicalize_typed_commutative_algebra_modules_openmath_xml(raw) == canonical
        assert (
            validate_canonical_typed_commutative_algebra_modules_openmath_xml(canonical)
            == canonical
        )
        assert 4 <= len(card["sketch_steps"]) <= 8
        marker = f"-- manifest card: {card['id']}\n{card['lean_target']} := {card['lean_witness']}"
        assert marker in witness


def test_module_manifest_generator_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "typed-commalg-modules.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "pals-agent")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_module_profile_rejects_scalar_and_map_carrier_mismatch() -> None:
    ring = _typed("module1", "CommRing")
    mismatched_scalar = _bind(
        [_decl("R", ring), _decl("S", ring), _decl("M", _module_type("R"))],
        _eq(
            _module("submodule_top", _var("R"), _var("M")),
            _module("submodule_top", _var("S"), _var("M")),
        ),
    )
    with pytest.raises(MathXMLValidationError, match=r"Module\(S\)"):
        validate_typed_commutative_algebra_modules_openmath_xml(mismatched_scalar)

    map_mismatch = _bind(
        [
            _decl("R", ring),
            _decl("M", _module_type("R")),
            _decl("N", _module_type("R")),
            _decl("P", _module_type("R")),
            _decl("f", _map_type("R", "M", "N")),
        ],
        _eq(
            _module("linear_kernel", _var("R"), _var("N"), _var("P"), _var("f")),
            _module("submodule_top", _var("R"), _var("N")),
        ),
    )
    with pytest.raises(MathXMLValidationError, match=r"LinearMap\(R,N,P\)"):
        validate_typed_commutative_algebra_modules_openmath_xml(map_mismatch)


def test_module_profile_rejects_free_variables_and_deferred_general_exactness() -> None:
    ring = _typed("module1", "CommRing")
    free_submodule = _bind(
        [_decl("R", ring), _decl("M", _module_type("R"))],
        _module(
            "submodule_le",
            _var("R"),
            _var("M"),
            _var("I"),
            _module("submodule_top", _var("R"), _var("M")),
        ),
    )
    with pytest.raises(MathXMLValidationError, match="free or undeclared"):
        validate_typed_commutative_algebra_modules_openmath_xml(free_submodule)

    unknown_sequence = _bind(
        [_decl("R", ring), _decl("M", _module_type("R"))],
        _module("exact_sequence", _var("R"), _var("M")),
    )
    with pytest.raises(MathXMLValidationError, match="outside typed module-theory"):
        validate_typed_commutative_algebra_modules_openmath_xml(unknown_sequence)


def test_module_profile_does_not_widen_generic_or_base_typed_math() -> None:
    card = _payload()["cards"][0]
    assert isinstance(card, dict)
    xml = card["openmath_xml"]
    assert isinstance(xml, str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(xml)
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(xml)


def test_module_manifest_rejects_resealed_staleness_and_bad_c14n() -> None:
    stale = copy.deepcopy(_payload())
    profile = stale["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(stale)
    with pytest.raises(TypedCommutativeAlgebraModulesManifestError, match="stale or mismatched"):
        validate_typed_commutative_algebra_modules_manifest(stale, repository_root=ROOT)

    malformed = copy.deepcopy(_payload())
    cards = malformed["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(malformed)
    with pytest.raises(TypedCommutativeAlgebraModulesManifestError, match="canonical OpenMath"):
        validate_typed_commutative_algebra_modules_manifest(malformed, repository_root=ROOT)
