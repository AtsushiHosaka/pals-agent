"""Fail-closed validation for sealed CA-5 integral/valuation evidence only.

The manifest remains local authoring evidence.  This module has no generic
Draft, database, embedding, seed, or PFI publishing path.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import rfc8785

from .typed_commutative_algebra_integral import (
    TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE,
    canonicalize_typed_commutative_algebra_integral_openmath_xml,
    validate_canonical_typed_commutative_algebra_integral_openmath_xml,
)

_SCHEMA = "pals.typed-commutative-algebra-integral-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_PREFIX = "sha256:"
_CARD_COUNT = 20
_PROFILE_FILES = {
    "design_path": "docs/typed-commutative-algebra-integral-v1-design.md",
    "registry_path": (
        "pals_agent/content_dictionaries/typed-commutative-algebra-integral-v1-registry.json"
    ),
    "validator_path": "pals_agent/typed_commutative_algebra_integral.py",
}
_WITNESS = "docs/typed-commutative-algebra-integral-v1-authoring-witnesses.lean"
_TOOLCHAIN = "pals-agent/lean-workspace/lean-toolchain"
_VERIFY = (
    "cd pals-agent/lean-workspace && lake env lean "
    "../../docs/typed-commutative-algebra-integral-v1-authoring-witnesses.lean"
)
_HARD_REJECTS = [
    "implicit_extension_direction",
    "implicit_fraction_field",
    "zero_divisor_as_domain_or_field",
    "unproved_integral_tower_transitivity",
    "lying_over_going_up_going_down",
    "fractional_ideal_dvr_dedekind",
    "valuation_value_group_or_uniformizer",
]
_CARD_KEYS = {
    "id",
    "domain",
    "difficulty",
    "canonical_statement",
    "canonical_statement_sha256",
    "proof_strategy",
    "sketch_steps",
    "openmath_xml",
    "openmath_xml_sha256",
    "canonical_openmath_xml",
    "canonical_openmath_xml_sha256",
    "lean_target",
    "lean_target_sha256",
    "lean_witness",
    "lean_witness_sha256",
    "openmath_profile",
    "profile_validation_status",
    "compiler_receipt_status",
    "admission_status",
    "alignment",
}


class TypedCommutativeAlgebraIntegralManifestError(ValueError):
    """Raised when CA-5 evidence is malformed, stale, or outside its seal."""


def load_typed_commutative_algebra_integral_manifest(
    path: Path, *, repository_root: Path
) -> dict[str, Any]:
    """Load and fully revalidate one immutable local CA-5 proposal."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest cannot be read"
        ) from exc
    if not isinstance(payload, dict):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest root must be an object"
        )
    validate_typed_commutative_algebra_integral_manifest(payload, repository_root=repository_root)
    return cast(dict[str, Any], payload)


def validate_typed_commutative_algebra_integral_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Fail closed before any catalog, embedding, database, or seed action."""
    _require_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "profile",
            "lean_receipt",
            "admitted_card_count",
            "hard_rejects",
            "hard_reject_count",
            "cards",
            "manifest_payload_sha256",
        },
        "manifest",
    )
    if payload["schema_version"] != _SCHEMA or payload["status"] != _STATUS:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest schema or status is invalid"
        )
    _validate_seal(_mapping(payload["seal"], "seal"))
    witness_text = _validate_profile_and_receipt(
        _mapping(payload["profile"], "profile"),
        _mapping(payload["lean_receipt"], "lean_receipt"),
        repository_root=repository_root,
    )
    _validate_manifest_digest(payload)
    if payload["hard_rejects"] != _HARD_REJECTS or payload["hard_reject_count"] != len(
        _HARD_REJECTS
    ):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation hard-reject boundary is invalid"
        )
    cards = payload["cards"]
    if (
        not isinstance(cards, list)
        or len(cards) != _CARD_COUNT
        or payload["admitted_card_count"] != _CARD_COUNT
    ):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest card count is invalid"
        )
    identifiers: set[str] = set()
    canonical_xml: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"cards[{index}]")
        _validate_card(card, index=index, witness_text=witness_text)
        identifier = _string(card["id"], f"cards[{index}].id")
        canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical OpenMath")
        if identifier in identifiers:
            raise TypedCommutativeAlgebraIntegralManifestError(
                "integral/valuation manifest repeats a card id"
            )
        if canonical in canonical_xml:
            raise TypedCommutativeAlgebraIntegralManifestError(
                "integral/valuation manifest repeats canonical typed OpenMath"
            )
        identifiers.add(identifier)
        canonical_xml.add(canonical)


def _validate_seal(seal: Mapping[str, object]) -> None:
    _require_keys(seal, {"scope", "admission", "revision"}, "seal")
    if seal != {
        "scope": "local typed commutative-algebra integral/valuation authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-commutative-algebra-integral-v1-local-r1",
    }:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest seal is invalid"
        )


def _validate_profile_and_receipt(
    profile: Mapping[str, object],
    receipt: Mapping[str, object],
    *,
    repository_root: Path,
) -> str:
    _require_keys(
        profile,
        {
            "id",
            "typed_cdbase",
            "design_path",
            "design_sha256",
            "registry_path",
            "registry_sha256",
            "validator",
            "validator_path",
            "validator_sha256",
            "canonicalizer_version",
        },
        "profile",
    )
    if (
        profile["id"] != TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE
        or profile["typed_cdbase"] != TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_OPENMATH_CDBASE
        or profile["validator"]
        != (
            "pals_agent.typed_commutative_algebra_integral."
            "validate_canonical_typed_commutative_algebra_integral_openmath_xml"
        )
        or profile["canonicalizer_version"] != "openmath-cdbase-alpha-c14n-v4"
    ):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest profile binding is invalid"
        )
    for field, expected_path in _PROFILE_FILES.items():
        if profile[field] != expected_path:
            raise TypedCommutativeAlgebraIntegralManifestError(
                "integral/valuation manifest profile artifact path is invalid"
            )
    package_root = repository_root / "pals-agent"
    _require_digest(
        _read_relative(repository_root, _string(profile["design_path"], "design path")),
        _string(profile["design_sha256"], "design digest"),
    )
    _require_digest(
        _read_relative(package_root, _string(profile["registry_path"], "registry path")),
        _string(profile["registry_sha256"], "registry digest"),
    )
    _require_digest(
        _read_relative(package_root, _string(profile["validator_path"], "validator path")),
        _string(profile["validator_sha256"], "validator digest"),
    )
    _require_keys(
        receipt,
        {
            "witness_path",
            "witness_file_sha256",
            "toolchain_path",
            "toolchain",
            "toolchain_sha256",
            "verification_command",
            "verification_status",
        },
        "lean_receipt",
    )
    if (
        receipt["witness_path"] != _WITNESS
        or receipt["toolchain_path"] != _TOOLCHAIN
        or receipt["verification_command"] != _VERIFY
        or receipt["verification_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation Lean receipt binding is invalid"
        )
    toolchain = _read_relative(repository_root, _TOOLCHAIN)
    if receipt["toolchain"] != toolchain.decode("utf-8").rstrip("\n"):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation Lean toolchain value is stale"
        )
    _require_digest(toolchain, _string(receipt["toolchain_sha256"], "toolchain digest"))
    witness = _read_relative(repository_root, _WITNESS)
    _require_digest(witness, _string(receipt["witness_file_sha256"], "witness digest"))
    return witness.decode("utf-8")


def _validate_manifest_digest(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    expected = _string(unsigned.pop("manifest_payload_sha256"), "manifest digest")
    actual = _sha256(rfc8785.dumps(cast(Any, unsigned)))
    if expected != actual:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation manifest digest does not match"
        )


def _validate_card(card: Mapping[str, object], *, index: int, witness_text: str) -> None:
    _require_keys(card, _CARD_KEYS, f"cards[{index}]")
    if (
        card["domain"] != "commutative_algebra.integral_dependence_and_valuation"
        or card["difficulty"] != "undergraduate_year_2"
        or card["openmath_profile"] != TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_integral_v1_sealed"
        or card["compiler_receipt_status"] != "verified_local_pinned_workspace"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation card sealed status is invalid"
        )
    statement = _string(card["canonical_statement"], f"cards[{index}].statement")
    _require_digest(
        statement.encode("utf-8"), _string(card["canonical_statement_sha256"], "statement digest")
    )
    _string(card["proof_strategy"], f"cards[{index}].strategy")
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation sketch_steps must contain 4..8 non-empty strings"
        )
    raw = _string(card["openmath_xml"], f"cards[{index}].raw OpenMath")
    _require_digest(raw.encode("utf-8"), _string(card["openmath_xml_sha256"], "raw XML digest"))
    canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical OpenMath")
    if canonicalize_typed_commutative_algebra_integral_openmath_xml(raw) != canonical:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation canonical OpenMath does not match source XML"
        )
    try:
        validate_canonical_typed_commutative_algebra_integral_openmath_xml(canonical)
    except ValueError as exc:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation canonical OpenMath fails its actual validator"
        ) from exc
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "canonical XML digest"),
    )
    target = _string(card["lean_target"], f"cards[{index}].Lean target")
    witness = _string(card["lean_witness"], f"cards[{index}].Lean witness")
    _require_digest(target.encode("utf-8"), _string(card["lean_target_sha256"], "target digest"))
    _require_digest(witness.encode("utf-8"), _string(card["lean_witness_sha256"], "witness digest"))
    identifier = _string(card["id"], f"cards[{index}].id")
    _require_witness_binding(identifier, target, witness, witness_text)
    alignment = _mapping(card["alignment"], f"cards[{index}].alignment")
    _require_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation alignment status is invalid"
        )
    for value in alignment.values():
        _string(value, "alignment field")


def _require_witness_binding(identifier: str, target: str, witness: str, bundle: str) -> None:
    marker = f"-- manifest card: {identifier}"
    start = bundle.find(marker)
    if start < 0:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation Lean evidence lacks its manifest marker"
        )
    end = bundle.find("-- manifest card:", start + len(marker))
    section = bundle[start:] if end < 0 else bundle[start:end]
    expected = _lean_normalize(f"{target} := {witness}")
    if expected not in _lean_normalize(section):
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation Lean evidence is not bound to its card"
        )


def _read_relative(root: Path, relative: str) -> bytes:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation artifact path escapes its allowed root"
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation artifact cannot be read"
        ) from exc


def _sha256(value: bytes) -> str:
    return _PREFIX + hashlib.sha256(value).hexdigest()


def _require_digest(value: bytes, expected: str) -> None:
    if not expected.startswith(_PREFIX) or len(expected) != len(_PREFIX) + 64:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation digest is invalid"
        )
    if _sha256(value) != expected:
        raise TypedCommutativeAlgebraIntegralManifestError(
            "integral/valuation artifact digest does not match"
        )


def _lean_normalize(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypedCommutativeAlgebraIntegralManifestError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedCommutativeAlgebraIntegralManifestError(f"{label} must be a non-empty string")
    return value


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TypedCommutativeAlgebraIntegralManifestError(f"{label} has unexpected fields")
