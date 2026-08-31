"""Fail-closed validation for sealed CA-2 module-theory authoring evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from .typed_commutative_algebra_modules import (
    TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE,
    canonicalize_typed_commutative_algebra_modules_openmath_xml,
    validate_canonical_typed_commutative_algebra_modules_openmath_xml,
)

_SCHEMA = "pals.typed-commutative-algebra-modules-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_SHA256 = "sha256:"
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


class TypedCommutativeAlgebraModulesManifestError(ValueError):
    """Raised when one piece of sealed CA-2 evidence is stale or malformed."""


def load_typed_commutative_algebra_modules_manifest(
    path: Path, *, repository_root: Path
) -> dict[str, Any]:
    """Load and fully revalidate one local-only module-theory manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedCommutativeAlgebraModulesManifestError("module manifest cannot be read") from exc
    if not isinstance(payload, dict):
        raise TypedCommutativeAlgebraModulesManifestError("module manifest root must be an object")
    validate_typed_commutative_algebra_modules_manifest(payload, repository_root=repository_root)
    return cast(dict[str, Any], payload)


def validate_typed_commutative_algebra_modules_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Reject stale source, profile, C14N, toolchain, or Lean bindings."""
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
        raise TypedCommutativeAlgebraModulesManifestError(
            "module manifest schema or status is invalid"
        )
    if _mapping(payload["seal"], "seal") != {
        "scope": "local typed commutative-algebra module authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-commutative-algebra-modules-v1-local-r1",
    }:
        raise TypedCommutativeAlgebraModulesManifestError("module manifest seal is invalid")
    _validate_digest(payload)
    witness = _validate_profile_and_receipt(
        _mapping(payload["profile"], "profile"),
        _mapping(payload["lean_receipt"], "lean receipt"),
        repository_root=repository_root,
    )
    cards = payload["cards"]
    if not isinstance(cards, list) or len(cards) != 24 or payload["admitted_card_count"] != 24:
        raise TypedCommutativeAlgebraModulesManifestError(
            "module manifest must seal exactly 24 cards"
        )
    exclusions = payload["excluded_cards"]
    if (
        not isinstance(exclusions, list)
        or len(exclusions) != 4
        or payload["excluded_card_count"] != 4
    ):
        raise TypedCommutativeAlgebraModulesManifestError("module manifest exclusions are invalid")
    _validate_exclusions(exclusions)
    identifiers: set[str] = set()
    canonical_xml: set[str] = set()
    for index, item in enumerate(cards, start=1):
        card = _mapping(item, f"cards[{index}]")
        _validate_card(card, index=index, witness_text=witness)
        identifier = _string(card["id"], f"cards[{index}].id")
        canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical XML")
        if identifier in identifiers or canonical in canonical_xml:
            raise TypedCommutativeAlgebraModulesManifestError(
                "module manifest repeats a card id or canonical OpenMath proposition"
            )
        identifiers.add(identifier)
        canonical_xml.add(canonical)


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
        profile["id"] != TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE
        or profile["typed_cdbase"] != TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE
        or profile["validator"]
        != (
            "pals_agent.typed_commutative_algebra_modules."
            "validate_canonical_typed_commutative_algebra_modules_openmath_xml"
        )
        or profile["canonicalizer_version"] != "openmath-cdbase-alpha-c14n-v4"
    ):
        raise TypedCommutativeAlgebraModulesManifestError("module manifest profile is invalid")
    expected = {
        "design_path": "docs/typed-commutative-algebra-modules-v1-design.md",
        "registry_path": (
            "pals_agent/content_dictionaries/"
            "typed-commutative-algebra-modules-v1-registry.json"
        ),
        "validator_path": "pals_agent/typed_commutative_algebra_modules.py",
    }
    for field, path in expected.items():
        if profile[field] != path:
            raise TypedCommutativeAlgebraModulesManifestError(
                "module manifest profile path is invalid"
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
            "toolchain",
            "verification_command",
            "verification_status",
        },
        "lean receipt",
    )
    if (
        receipt["witness_path"]
        != "docs/typed-commutative-algebra-modules-v1-authoring-witnesses.lean"
        or receipt["verification_command"]
        != (
            "cd pals-agent/lean-workspace && lake env lean "
            "../../docs/typed-commutative-algebra-modules-v1-authoring-witnesses.lean"
        )
        or receipt["verification_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedCommutativeAlgebraModulesManifestError("module manifest Lean receipt is invalid")
    toolchain = (
        _read_relative(package_root, "lean-workspace/lean-toolchain").decode("utf-8").rstrip("\n")
    )
    if receipt["toolchain"] != toolchain:
        raise TypedCommutativeAlgebraModulesManifestError("module manifest Lean toolchain is stale")
    witness = _read_relative(repository_root, _string(receipt["witness_path"], "witness path"))
    _require_digest(witness, _string(receipt["witness_file_sha256"], "witness digest"))
    return witness.decode("utf-8")


def _validate_card(card: Mapping[str, object], *, index: int, witness_text: str) -> None:
    _require_keys(card, _CARD_KEYS, f"cards[{index}]")
    for field in ("id", "canonical_statement", "proof_strategy", "lean_target", "lean_witness"):
        _string(card[field], f"cards[{index}].{field}")
    if (
        card["openmath_profile"] != TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_modules_v1_sealed"
        or card["compiler_receipt_status"] != "verified"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedCommutativeAlgebraModulesManifestError("module card status is invalid")
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedCommutativeAlgebraModulesManifestError("module card needs 4..8 sketch steps")
    raw = _string(card["openmath_xml"], "raw XML")
    canonical = _string(card["canonical_openmath_xml"], "canonical XML")
    _require_digest(raw.encode("utf-8"), _string(card["openmath_xml_sha256"], "raw XML digest"))
    if canonicalize_typed_commutative_algebra_modules_openmath_xml(raw) != canonical:
        raise TypedCommutativeAlgebraModulesManifestError("module card canonical OpenMath is stale")
    validate_canonical_typed_commutative_algebra_modules_openmath_xml(canonical)
    _require_digest(
        canonical.encode("utf-8"), _string(card["canonical_openmath_xml_sha256"], "C14N digest")
    )
    statement = _string(card["canonical_statement"], "statement")
    target = _string(card["lean_target"], "Lean target")
    proof = _string(card["lean_witness"], "Lean witness")
    _require_digest(
        statement.encode("utf-8"), _string(card["canonical_statement_sha256"], "statement digest")
    )
    _require_digest(target.encode("utf-8"), _string(card["lean_target_sha256"], "target digest"))
    _require_digest(proof.encode("utf-8"), _string(card["lean_witness_sha256"], "witness digest"))
    marker = f"-- manifest card: {_string(card['id'], 'id')}\n{target} := {proof}"
    if marker not in witness_text:
        raise TypedCommutativeAlgebraModulesManifestError(
            "module Lean evidence is not bound to its card"
        )
    alignment = _mapping(card["alignment"], "alignment")
    _require_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedCommutativeAlgebraModulesManifestError("module card alignment is invalid")
    for value in alignment.values():
        _string(value, "alignment value")


def _validate_exclusions(exclusions: list[object]) -> None:
    identifiers: set[str] = set()
    for index, item in enumerate(exclusions, start=1):
        entry = _mapping(item, f"excluded[{index}]")
        _require_keys(entry, {"id", "reason"}, f"excluded[{index}]")
        identifier = _string(entry["id"], "excluded id")
        _string(entry["reason"], "excluded reason")
        if identifier in identifiers:
            raise TypedCommutativeAlgebraModulesManifestError(
                "module manifest repeats an exclusion id"
            )
        identifiers.add(identifier)


def _validate_digest(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    expected = _string(unsigned.pop("manifest_payload_sha256"), "manifest digest")
    actual = _sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    if actual != expected:
        raise TypedCommutativeAlgebraModulesManifestError("module manifest digest does not match")


def _read_relative(root: Path, relative: str) -> bytes:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedCommutativeAlgebraModulesManifestError(
            "module artifact path escapes its root"
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedCommutativeAlgebraModulesManifestError("module artifact cannot be read") from exc


def _require_digest(data: bytes, expected: str) -> None:
    if expected != _sha256(data):
        raise TypedCommutativeAlgebraModulesManifestError(
            "module artifact digest is stale or mismatched"
        )


def _sha256(data: bytes) -> str:
    return _SHA256 + hashlib.sha256(data).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypedCommutativeAlgebraModulesManifestError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedCommutativeAlgebraModulesManifestError(f"{label} must be a non-empty string")
    return value


def _require_keys(mapping: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(mapping) != expected:
        raise TypedCommutativeAlgebraModulesManifestError(f"{label} fields are invalid")
