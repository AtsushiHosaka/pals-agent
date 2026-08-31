"""Fail-closed validation for sealed local CA-6 authoring evidence.

The artifact is intentionally local-only: it has no generic Draft, database,
embedding, seed, or PFI publishing path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .typed_commutative_algebra_chain_dimension import (
    TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE,
    canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml,
    validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml,
)

_SCHEMA = "pals.typed-commutative-algebra-chain-dimension-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_SHA256 = "sha256:"
_CARD_COUNT = 17
_EXCLUSION_COUNT = 5
_DESIGN_PATH = "docs/typed-commutative-algebra-chain-dimension-v1-design.md"
_REGISTRY_PATH = (
    "pals_agent/content_dictionaries/typed-commutative-algebra-chain-dimension-v1-registry.json"
)
_VALIDATOR_PATH = "pals_agent/typed_commutative_algebra_chain_dimension.py"
_VALIDATOR = (
    "pals_agent.typed_commutative_algebra_chain_dimension."
    "validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml"
)
_WITNESS_PATH = "docs/typed-commutative-algebra-chain-dimension-v1-authoring-witnesses.lean"
_VERIFY_COMMAND = (
    "cd pals-agent/lean-workspace && lake env lean "
    "../../docs/typed-commutative-algebra-chain-dimension-v1-authoring-witnesses.lean"
)
_SEAL = {
    "scope": "local typed commutative-algebra CA-6 authoring evidence only",
    "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
    "revision": "typed-commutative-algebra-chain-dimension-v1-local-r1",
}
_ADMISSION = (
    "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
    "translation receipt"
)
_CARD_KEYS = {
    "id",
    "canonical_statement",
    "proof_strategy",
    "sketch_steps",
    "openmath_xml",
    "openmath_xml_sha256",
    "canonical_openmath_xml",
    "canonical_openmath_xml_sha256",
    "canonical_statement_sha256",
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


class TypedCommutativeAlgebraChainDimensionManifestError(ValueError):
    """Raised when a CA-6 manifest is malformed, stale, or unsealed."""


def load_typed_commutative_algebra_chain_dimension_manifest(
    path: Path, *, repository_root: Path
) -> dict[str, Any]:
    """Read and fully revalidate one immutable local CA-6 authoring proposal."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest cannot be read"
        ) from exc
    if not isinstance(payload, dict):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest root must be an object"
        )
    validate_typed_commutative_algebra_chain_dimension_manifest(
        payload, repository_root=repository_root
    )
    return cast(dict[str, Any], payload)


def validate_typed_commutative_algebra_chain_dimension_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Fail closed on malformed payloads or stale byte-bound evidence."""
    _require_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "profile",
            "lean_receipt",
            "admitted_card_count",
            "excluded_cards",
            "excluded_card_count",
            "cards",
            "manifest_payload_sha256",
        },
        "manifest",
    )
    if payload["schema_version"] != _SCHEMA or payload["status"] != _STATUS:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest schema or status is invalid"
        )
    if _mapping(payload["seal"], "seal") != _SEAL:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest seal is invalid"
        )
    _validate_manifest_digest(payload)
    witness = _validate_profile_and_receipt(
        _mapping(payload["profile"], "profile"),
        _mapping(payload["lean_receipt"], "Lean receipt"),
        repository_root=repository_root,
    )
    cards = payload["cards"]
    if not isinstance(cards, list) or payload["admitted_card_count"] != _CARD_COUNT:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest card count is invalid"
        )
    if len(cards) != _CARD_COUNT:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest must seal exactly seventeen cards"
        )
    _validate_exclusions(payload)
    identifiers: set[str] = set()
    canonical_xml: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"cards[{index}]")
        _validate_card(card, index=index, witness_text=witness)
        identifier = _string(card["id"], f"cards[{index}].id")
        canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical XML")
        if identifier in identifiers or canonical in canonical_xml:
            raise TypedCommutativeAlgebraChainDimensionManifestError(
                "chain/dimension manifest repeats card identity or canonical OpenMath"
            )
        identifiers.add(identifier)
        canonical_xml.add(canonical)


def _validate_manifest_digest(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    expected = _string(unsigned.pop("manifest_payload_sha256"), "manifest digest")
    serialized = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _require_digest(serialized.encode("utf-8"), expected, "manifest digest")


def _validate_profile_and_receipt(
    profile: Mapping[str, object], receipt: Mapping[str, object], *, repository_root: Path
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
        profile["id"] != TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE
        or profile["typed_cdbase"] != TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_OPENMATH_CDBASE
        or profile["design_path"] != _DESIGN_PATH
        or profile["registry_path"] != _REGISTRY_PATH
        or profile["validator"] != _VALIDATOR
        or profile["validator_path"] != _VALIDATOR_PATH
        or profile["canonicalizer_version"] != "openmath-cdbase-alpha-c14n-v4"
    ):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension manifest profile is invalid"
        )
    package_root = repository_root / "pals-agent"
    _require_digest(
        _read_relative(repository_root, _DESIGN_PATH),
        _string(profile["design_sha256"], "design digest"),
        "design artifact",
    )
    _require_digest(
        _read_relative(package_root, _REGISTRY_PATH),
        _string(profile["registry_sha256"], "registry digest"),
        "registry artifact",
    )
    _require_digest(
        _read_relative(package_root, _VALIDATOR_PATH),
        _string(profile["validator_sha256"], "validator digest"),
        "validator artifact",
    )
    _require_keys(
        receipt,
        {
            "witness_path",
            "witness_file_sha256",
            "toolchain",
            "verification_command",
            "verification_status",
        },
        "Lean receipt",
    )
    if (
        receipt["witness_path"] != _WITNESS_PATH
        or receipt["verification_command"] != _VERIFY_COMMAND
        or receipt["verification_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension Lean receipt is invalid"
        )
    toolchain = (
        _read_relative(package_root, "lean-workspace/lean-toolchain").decode("utf-8").rstrip("\n")
    )
    if receipt["toolchain"] != toolchain:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension Lean toolchain is stale or mismatched"
        )
    witness = _read_relative(repository_root, _WITNESS_PATH)
    _require_digest(
        witness,
        _string(receipt["witness_file_sha256"], "witness digest"),
        "Lean witness artifact",
    )
    return witness.decode("utf-8")


def _validate_exclusions(payload: Mapping[str, object]) -> None:
    exclusions = payload["excluded_cards"]
    if (
        not isinstance(exclusions, list)
        or len(exclusions) != _EXCLUSION_COUNT
        or payload["excluded_card_count"] != _EXCLUSION_COUNT
    ):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension exclusions are invalid"
        )
    identifiers: set[str] = set()
    for index, raw in enumerate(exclusions, start=1):
        item = _mapping(raw, f"excluded_cards[{index}]")
        _require_keys(item, {"id", "reason"}, f"excluded_cards[{index}]")
        identifier = _string(item["id"], f"excluded_cards[{index}].id")
        _string(item["reason"], f"excluded_cards[{index}].reason")
        if identifier in identifiers:
            raise TypedCommutativeAlgebraChainDimensionManifestError(
                "chain/dimension exclusions repeat an id"
            )
        identifiers.add(identifier)


def _validate_card(card: Mapping[str, object], *, index: int, witness_text: str) -> None:
    _require_keys(card, _CARD_KEYS, f"cards[{index}]")
    for field in ("id", "canonical_statement", "proof_strategy", "lean_target", "lean_witness"):
        _string(card[field], f"cards[{index}].{field}")
    if (
        card["openmath_profile"] != TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_chain_dimension_v1_sealed"
        or card["compiler_receipt_status"] != "verified"
        or card["admission_status"] != _ADMISSION
    ):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension card status is invalid"
        )
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension card needs four to eight Sketch steps"
        )
    raw = _string(card["openmath_xml"], "raw OpenMath")
    canonical = _string(card["canonical_openmath_xml"], "canonical OpenMath")
    _require_digest(
        raw.encode("utf-8"), _string(card["openmath_xml_sha256"], "raw digest"), "raw XML"
    )
    if canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml(raw) != canonical:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension card canonical OpenMath is stale"
        )
    validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml(canonical)
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "canonical digest"),
        "canonical XML",
    )
    statement = _string(card["canonical_statement"], "statement")
    _require_digest(
        statement.encode("utf-8"),
        _string(card["canonical_statement_sha256"], "statement digest"),
        "statement",
    )
    target = _string(card["lean_target"], "Lean target")
    witness = _string(card["lean_witness"], "Lean witness")
    _require_digest(
        target.encode("utf-8"), _string(card["lean_target_sha256"], "target digest"), "target"
    )
    _require_digest(
        witness.encode("utf-8"), _string(card["lean_witness_sha256"], "witness digest"), "witness"
    )
    if f"-- manifest card: {card['id']}\n{target} := {witness}" not in witness_text:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension Lean evidence is not bound to its card"
        )
    alignment = _mapping(card["alignment"], "alignment")
    _require_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension alignment status is invalid"
        )
    for value in alignment.values():
        _string(value, "alignment value")


def _read_relative(root: Path, relative: str) -> bytes:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension artifact path escapes its root"
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            "chain/dimension artifact cannot be read"
        ) from exc


def _require_digest(data: bytes, expected: str, label: str) -> None:
    if expected != _SHA256 + hashlib.sha256(data).hexdigest():
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            f"chain/dimension {label} digest is stale or mismatched"
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            f"chain/dimension {label} must be an object"
        )
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            f"chain/dimension {label} must be a non-empty string"
        )
    return value


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TypedCommutativeAlgebraChainDimensionManifestError(
            f"chain/dimension {label} has an invalid field set"
        )
