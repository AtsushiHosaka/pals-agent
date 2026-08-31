"""Contract tests for the isolated CA-5 integral/valuation profile."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import rfc8785

from pals_agent.openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml
from pals_agent.typed_commutative_algebra_integral import (
    TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_OPENMATH_CDBASE as TYPED,
)
from pals_agent.typed_commutative_algebra_integral import (
    canonicalize_typed_commutative_algebra_integral_openmath_xml,
    validate_canonical_typed_commutative_algebra_integral_openmath_xml,
    validate_typed_commutative_algebra_integral_openmath_xml,
)
from pals_agent.typed_commutative_algebra_integral_manifest import (
    TypedCommutativeAlgebraIntegralManifestError,
    load_typed_commutative_algebra_integral_manifest,
    validate_typed_commutative_algebra_integral_manifest,
)
from pals_agent.typed_math import validate_typed_math_openmath_xml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/typed-commutative-algebra-integral-v1-sealed-manifest.proposal.json"
WITNESS = ROOT / "docs/typed-commutative-algebra-integral-v1-authoring-witnesses.lean"
GENERATOR = (
    ROOT / "pals-scripts/generate-typed-commutative-algebra-integral-v1-authoring-manifest.py"
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


def _sort(name: str, *arguments: str) -> str:
    symbol = _typed("integral1", name)
    return symbol if not arguments else _app(symbol, *arguments)


def _elem(carrier: str) -> str:
    return _app(_typed("typed1", "Elem"), _var(carrier))


def _bind(declarations: list[str], body: str) -> str:
    return (
        f'<OMOBJ xmlns="{OPENMATH}" version="2.0"><OMBIND>'
        f"{_typed('typed1', 'forall')}<OMBVAR>{''.join(declarations)}</OMBVAR>"
        f"{body}</OMBIND></OMOBJ>"
    )


def _integral(base: str, target: str, element: str) -> str:
    return _app(_typed("integral1", "is_integral"), _var(base), _var(target), element)


def _valuation_mem(field: str, valuation: str, element: str) -> str:
    return _app(
        _typed("integral1", "valuation_mem"), _var(field), _var(valuation), element
    )


def _payload() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _reseal(payload: dict[str, Any]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256", None)
    payload["manifest_payload_sha256"] = "sha256:" + hashlib.sha256(
        rfc8785.dumps(unsigned)
    ).hexdigest()


def test_integral_manifest_is_current_and_all_cards_use_actual_c14n() -> None:
    payload = load_typed_commutative_algebra_integral_manifest(MANIFEST, repository_root=ROOT)
    assert payload["admitted_card_count"] == 20
    assert payload["hard_reject_count"] == 7
    cards = payload["cards"]
    assert isinstance(cards, list) and len(cards) == 20
    witness = WITNESS.read_text(encoding="utf-8")
    for card in cards:
        assert isinstance(card, dict)
        raw = card["openmath_xml"]
        canonical = card["canonical_openmath_xml"]
        assert isinstance(raw, str) and isinstance(canonical, str)
        assert canonicalize_typed_commutative_algebra_integral_openmath_xml(raw) == canonical
        assert (
            validate_canonical_typed_commutative_algebra_integral_openmath_xml(canonical)
            == canonical
        )
        assert 4 <= len(card["sketch_steps"]) <= 8
        assert f"-- manifest card: {card['id']}" in witness


def test_integral_manifest_generator_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "typed-commalg-integral.json"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "pals-agent")
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output), "--verify-lean"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_bytes() == MANIFEST.read_bytes()


def test_integral_profile_rejects_extension_direction_and_valuation_field_mismatch() -> None:
    comm_ring = _sort("CommRing")
    field = _sort("Field")
    extension_r = _sort("Extension", _var("R"))
    wrong_direction = _bind(
        [
            _decl("R", comm_ring),
            _decl("S", extension_r),
            _decl("T", comm_ring),
            _decl("x", _elem("S")),
        ],
        _integral("R", "T", _var("x")),
    )
    with pytest.raises(MathXMLValidationError, match=r"Extension\(R\)"):
        validate_typed_commutative_algebra_integral_openmath_xml(wrong_direction)

    wrong_base = _bind(
        [
            _decl("R", comm_ring),
            _decl("Q", comm_ring),
            _decl("S", extension_r),
            _decl("x", _elem("S")),
        ],
        _integral("Q", "S", _var("x")),
    )
    with pytest.raises(MathXMLValidationError, match=r"Extension\(Q\)"):
        validate_typed_commutative_algebra_integral_openmath_xml(wrong_base)

    valuation_mismatch = _bind(
        [
            _decl("K", field),
            _decl("L", field),
            _decl("V", _sort("ValuationRing", _var("K"))),
            _decl("x", _elem("K")),
        ],
        _valuation_mem("L", "V", _var("x")),
    )
    with pytest.raises(MathXMLValidationError, match=r"ValuationRing\(L\)"):
        validate_typed_commutative_algebra_integral_openmath_xml(valuation_mismatch)


def test_integral_profile_rejects_deferred_theory_unknown_symbols_and_inherited_cdbase() -> None:
    comm_ring = _sort("CommRing")
    extension_r = _sort("Extension", _var("R"))
    deferred = _bind(
        [_decl("R", comm_ring), _decl("S", extension_r)],
        _app(_typed("integral1", "going_up"), _var("R"), _var("S")),
    )
    with pytest.raises(MathXMLValidationError, match="outside typed integral/valuation"):
        validate_typed_commutative_algebra_integral_openmath_xml(deferred)

    bare_zero = _bind(
        [_decl("R", comm_ring), _decl("S", extension_r)],
        _integral("R", "S", "<OMI>0</OMI>"),
    )
    with pytest.raises(MathXMLValidationError, match="outside typed integral/valuation"):
        validate_typed_commutative_algebra_integral_openmath_xml(bare_zero)

    card = _payload()["cards"][0]
    assert isinstance(card, dict) and isinstance(card["openmath_xml"], str)
    inherited = card["openmath_xml"].replace(
        f'<OMS cdbase="{TYPED}" cd="integral1" name="is_integral"/>',
        '<OMS cd="integral1" name="is_integral"/>',
    )
    with pytest.raises(MathXMLValidationError, match="outside typed integral/valuation"):
        validate_typed_commutative_algebra_integral_openmath_xml(inherited)


def test_integral_profile_rejects_zero_divisor_ambiguity_and_extension_towers() -> None:
    comm_ring = _sort("CommRing")
    extension_r = _sort("Extension", _var("R"))
    field_inverse_over_commutative_ring = _bind(
        [_decl("R", comm_ring), _decl("x", _elem("R"))],
        _app(
            f'<OMS cdbase="{STANDARD}" cd="relation1" name="eq"/>',
            _app(_typed("integral1", "field_inv"), _var("R"), _var("x")),
            _var("x"),
        ),
    )
    with pytest.raises(MathXMLValidationError, match="must have sort `Field`"):
        validate_typed_commutative_algebra_integral_openmath_xml(
            field_inverse_over_commutative_ring
        )

    nested_extension = _bind(
        [
            _decl("R", comm_ring),
            _decl("S", extension_r),
            _decl("T", _sort("Extension", _var("S"))),
            _decl("x", _elem("S")),
        ],
        _integral("R", "S", _var("x")),
    )
    with pytest.raises(MathXMLValidationError, match="expected prior base"):
        validate_typed_commutative_algebra_integral_openmath_xml(nested_extension)


def test_integral_profile_does_not_widen_generic_or_base_typed_math() -> None:
    card = _payload()["cards"][0]
    assert isinstance(card, dict) and isinstance(card["openmath_xml"], str)
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(card["openmath_xml"])
    with pytest.raises(MathXMLValidationError):
        validate_typed_math_openmath_xml(card["openmath_xml"])


def test_integral_manifest_rejects_resealed_staleness_and_bad_c14n() -> None:
    stale = copy.deepcopy(_payload())
    profile = stale["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal(stale)
    with pytest.raises(TypedCommutativeAlgebraIntegralManifestError, match="digest does not match"):
        validate_typed_commutative_algebra_integral_manifest(stale, repository_root=ROOT)

    malformed = copy.deepcopy(_payload())
    cards = malformed["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(malformed)
    with pytest.raises(TypedCommutativeAlgebraIntegralManifestError, match="canonical OpenMath"):
        validate_typed_commutative_algebra_integral_manifest(malformed, repository_root=ROOT)
