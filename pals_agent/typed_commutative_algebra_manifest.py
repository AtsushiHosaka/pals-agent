"""Fail-closed validation for sealed local commutative-algebra evidence.

This module validates a proposal artifact only.  It has no generic Draft,
database, embedding, seed, or PFI publishing path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .typed_commutative_algebra import (
    TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_PROFILE,
    canonicalize_typed_commutative_algebra_openmath_xml,
    validate_canonical_typed_commutative_algebra_openmath_xml,
)

_SCHEMA = "pals.typed-commutative-algebra-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_SHA256 = "sha256:"
_PROFILE_FILES = {
    "design_path": "docs/typed-commutative-algebra-v1-design.md",
    "registry_path": "pals_agent/content_dictionaries/typed-commutative-algebra-v1-registry.json",
    "validator_path": "pals_agent/typed_commutative_algebra.py",
}
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


class TypedCommutativeAlgebraManifestError(ValueError):
    """Raised when sealed commutative-algebra evidence is stale or malformed."""


def load_typed_commutative_algebra_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]:
    """Load and fully revalidate one immutable local authoring proposal."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest cannot be read"
        ) from exc
    if not isinstance(payload, dict):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest root must be an object"
        )
    validate_typed_commutative_algebra_manifest(payload, repository_root=repository_root)
    return cast(dict[str, Any], payload)


def validate_typed_commutative_algebra_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Fail closed on stale source, profile, C14N, or Lean evidence."""
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
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest schema or status is invalid"
        )
    _validate_seal(_mapping(payload["seal"], "seal"))
    witness = _validate_profile_and_receipt(
        _mapping(payload["profile"], "profile"),
        _mapping(payload["lean_receipt"], "lean_receipt"),
        repository_root=repository_root,
    )
    _validate_digest(payload)

    cards = payload["cards"]
    if (
        not isinstance(cards, list)
        or len(cards) != 13
        or payload["admitted_card_count"] != len(cards)
    ):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest must seal exactly thirteen cards"
        )
    exclusions = payload["excluded_cards"]
    if (
        not isinstance(exclusions, list)
        or len(exclusions) != 4
        or payload["excluded_card_count"] != len(exclusions)
    ):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest exclusion count is invalid"
        )
    _validate_exclusions(exclusions)

    identifiers: set[str] = set()
    canonical_xml: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"cards[{index}]")
        _validate_card(card, index=index, witness_text=witness)
        identifier = _string(card["id"], f"cards[{index}].id")
        canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].xml")
        if identifier in identifiers:
            raise TypedCommutativeAlgebraManifestError(
                "commutative-algebra manifest repeats a card id"
            )
        if canonical in canonical_xml:
            raise TypedCommutativeAlgebraManifestError(
                "commutative-algebra manifest repeats canonical typed OpenMath"
            )
        identifiers.add(identifier)
        canonical_xml.add(canonical)


def _validate_seal(seal: Mapping[str, object]) -> None:
    _require_keys(seal, {"scope", "admission", "revision"}, "seal")
    if seal != {
        "scope": "local typed-commutative-algebra authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-commutative-algebra-v1-local-r1",
    }:
        raise TypedCommutativeAlgebraManifestError("commutative-algebra manifest seal is invalid")


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
        profile["id"] != TYPED_COMMUTATIVE_ALGEBRA_PROFILE
        or profile["typed_cdbase"] != TYPED_COMMUTATIVE_ALGEBRA_OPENMATH_CDBASE
        or profile["validator"]
        != (
            "pals_agent.typed_commutative_algebra."
            "validate_canonical_typed_commutative_algebra_openmath_xml"
        )
        or profile["canonicalizer_version"] != "openmath-cdbase-alpha-c14n-v4"
    ):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest profile is invalid"
        )
    for field, expected_path in _PROFILE_FILES.items():
        if profile[field] != expected_path:
            raise TypedCommutativeAlgebraManifestError(
                "commutative-algebra manifest profile path is invalid"
            )
    package_root = repository_root / "pals-agent"
    _require_digest(
        _read_relative(repository_root, _string(profile["design_path"], "profile.design_path")),
        _string(profile["design_sha256"], "profile.design_sha256"),
    )
    _require_digest(
        _read_relative(package_root, _string(profile["registry_path"], "profile.registry_path")),
        _string(profile["registry_sha256"], "profile.registry_sha256"),
    )
    _require_digest(
        _read_relative(package_root, _string(profile["validator_path"], "profile.validator_path")),
        _string(profile["validator_sha256"], "profile.validator_sha256"),
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
        "lean_receipt",
    )
    if (
        receipt["witness_path"] != "docs/typed-commutative-algebra-v1-authoring-witnesses.lean"
        or receipt["verification_command"]
        != (
            "cd pals-agent/lean-workspace && lake env lean "
            "../../docs/typed-commutative-algebra-v1-authoring-witnesses.lean"
        )
        or receipt["verification_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedCommutativeAlgebraManifestError("commutative-algebra Lean receipt is invalid")
    toolchain_bytes = _read_relative(package_root, "lean-workspace/lean-toolchain")
    toolchain = toolchain_bytes.decode("utf-8").rstrip("\n")
    if receipt["toolchain"] != toolchain:
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra Lean toolchain is stale or mismatched"
        )
    witness = _read_relative(repository_root, _string(receipt["witness_path"], "witness path"))
    _require_digest(witness, _string(receipt["witness_file_sha256"], "witness digest"))
    return witness.decode("utf-8")


def _validate_digest(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    expected = _string(unsigned.pop("manifest_payload_sha256"), "manifest digest")
    serialized = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if expected != _sha256(serialized.encode("utf-8")):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra manifest digest does not match"
        )


def _validate_exclusions(exclusions: list[object]) -> None:
    identifiers: set[str] = set()
    for index, raw in enumerate(exclusions, start=1):
        item = _mapping(raw, f"excluded_cards[{index}]")
        _require_keys(item, {"id", "reason"}, f"excluded_cards[{index}]")
        identifier = _string(item["id"], f"excluded_cards[{index}].id")
        _string(item["reason"], f"excluded_cards[{index}].reason")
        if identifier in identifiers:
            raise TypedCommutativeAlgebraManifestError(
                "commutative-algebra manifest repeats an exclusion id"
            )
        identifiers.add(identifier)


def _validate_card(card: Mapping[str, object], *, index: int, witness_text: str) -> None:
    _require_keys(card, _CARD_KEYS, f"cards[{index}]")
    for field in ("id", "canonical_statement", "proof_strategy", "lean_target", "lean_witness"):
        _string(card[field], f"cards[{index}].{field}")
    if (
        card["openmath_profile"] != TYPED_COMMUTATIVE_ALGEBRA_PROFILE
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_v1_sealed"
        or card["compiler_receipt_status"] != "verified"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedCommutativeAlgebraManifestError("commutative-algebra card status is invalid")
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra card needs 4..8 sketch steps"
        )
    raw = _string(card["openmath_xml"], f"cards[{index}].openmath_xml")
    canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical_openmath_xml")
    _require_digest(raw.encode("utf-8"), _string(card["openmath_xml_sha256"], "raw XML digest"))
    if canonicalize_typed_commutative_algebra_openmath_xml(raw) != canonical:
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra card canonical OpenMath is stale"
        )
    validate_canonical_typed_commutative_algebra_openmath_xml(canonical)
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "canonical XML digest"),
    )
    statement = _string(card["canonical_statement"], "statement")
    _require_digest(
        statement.encode("utf-8"),
        _string(card["canonical_statement_sha256"], "statement digest"),
    )
    target = _string(card["lean_target"], "Lean target")
    witness = _string(card["lean_witness"], "Lean witness")
    _require_digest(target.encode("utf-8"), _string(card["lean_target_sha256"], "target digest"))
    _require_digest(witness.encode("utf-8"), _string(card["lean_witness_sha256"], "witness digest"))
    marker = f"-- manifest card: {_string(card['id'], 'card id')}\n{target} := {witness}"
    if marker not in witness_text:
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra Lean evidence is not bound to its card"
        )
    alignment = _mapping(card["alignment"], "card alignment")
    _require_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "card alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra card alignment status is invalid"
        )
    for value in alignment.values():
        _string(value, "card alignment value")


def _read_relative(root: Path, relative: str) -> bytes:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra artifact path escapes its root"
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra artifact cannot be read"
        ) from exc


def _require_digest(data: bytes, expected: str) -> None:
    if expected != _sha256(data):
        raise TypedCommutativeAlgebraManifestError(
            "commutative-algebra artifact digest is stale or mismatched"
        )


def _sha256(data: bytes) -> str:
    return _SHA256 + hashlib.sha256(data).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypedCommutativeAlgebraManifestError(f"commutative-algebra {label} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedCommutativeAlgebraManifestError(
            f"commutative-algebra {label} must be a non-empty string"
        )
    return value


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TypedCommutativeAlgebraManifestError(
            f"commutative-algebra {label} has an invalid field set"
        )
