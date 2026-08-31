"""Fail-closed validation for sealed CA-4 primary-decomposition evidence only."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import rfc8785

from .typed_commutative_algebra_decomposition import (
    TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_OPENMATH_CDBASE,
    TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE,
    canonicalize_typed_commutative_algebra_decomposition_openmath_xml,
    validate_canonical_typed_commutative_algebra_decomposition_openmath_xml,
)

_SCHEMA = "pals.typed-commutative-algebra-decomposition-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_PREFIX = "sha256:"
_CARD_COUNT = 22
_HARD_REJECTS = [
    "associated_primes_requires_module_and_annihilator",
    "noetherian_primary_decomposition_existence",
    "arbitrary_finite_family_decomposition",
    "quotient_or_localized_primary_component",
]
_PROFILE_FILES = {
    "design_path": "docs/typed-commutative-algebra-decomposition-v1-design.md",
    "registry_path": (
        "pals_agent/content_dictionaries/typed-commutative-algebra-decomposition-v1-registry.json"
    ),
    "validator_path": "pals_agent/typed_commutative_algebra_decomposition.py",
}
_WITNESS = "docs/typed-commutative-algebra-decomposition-v1-authoring-witnesses.lean"
_TOOLCHAIN = "pals-agent/lean-workspace/lean-toolchain"
_VERIFY = (
    "cd pals-agent/lean-workspace && lake env lean "
    "../../docs/typed-commutative-algebra-decomposition-v1-authoring-witnesses.lean"
)
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


class TypedCommutativeAlgebraDecompositionManifestError(ValueError):
    """Raised when CA-4 authoring evidence is stale or malformed."""


def load_typed_commutative_algebra_decomposition_manifest(
    path: Path, *, repository_root: Path
) -> dict[str, Any]:
    """Load and fully revalidate one local-only CA-4 proposal manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition manifest cannot be read"
        ) from exc
    if not isinstance(payload, dict):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition manifest root must be an object"
        )
    validate_typed_commutative_algebra_decomposition_manifest(
        payload, repository_root=repository_root
    )
    return cast(dict[str, Any], payload)


def validate_typed_commutative_algebra_decomposition_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Reject stale source/C14N/Lean evidence before any catalog or DB action."""
    _exact_keys(
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
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition manifest schema or status is invalid"
        )
    _validate_seal(_mapping(payload["seal"], "seal"))
    witness_text = _validate_profile_and_receipt(
        _mapping(payload["profile"], "profile"),
        _mapping(payload["lean_receipt"], "lean_receipt"),
        repository_root=repository_root,
    )
    _validate_digest(payload)
    if payload["hard_rejects"] != _HARD_REJECTS or payload["hard_reject_count"] != len(
        _HARD_REJECTS
    ):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition hard-reject boundary is invalid"
        )
    cards = payload["cards"]
    if (
        not isinstance(cards, list)
        or len(cards) != _CARD_COUNT
        or payload["admitted_card_count"] != _CARD_COUNT
    ):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition manifest card count is invalid"
        )
    seen_ids: set[str] = set()
    seen_canonical: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"cards[{index}]")
        _validate_card(card, index=index, witness_text=witness_text)
        identifier = _string(card["id"], f"cards[{index}].id")
        canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical XML")
        if identifier in seen_ids or canonical in seen_canonical:
            raise TypedCommutativeAlgebraDecompositionManifestError(
                "primary-decomposition manifest repeats a card id or canonical OpenMath"
            )
        seen_ids.add(identifier)
        seen_canonical.add(canonical)


def _validate_seal(seal: Mapping[str, object]) -> None:
    _exact_keys(seal, {"scope", "admission", "revision"}, "seal")
    if seal != {
        "scope": "local typed commutative-algebra primary-decomposition authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-commutative-algebra-decomposition-v1-local-r1",
    }:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition manifest seal is invalid"
        )


def _validate_profile_and_receipt(
    profile: Mapping[str, object],
    receipt: Mapping[str, object],
    *,
    repository_root: Path,
) -> str:
    _exact_keys(
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
        profile["id"] != TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE
        or profile["typed_cdbase"] != TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_OPENMATH_CDBASE
        or profile["validator"]
        != (
            "pals_agent.typed_commutative_algebra_decomposition."
            "validate_canonical_typed_commutative_algebra_decomposition_openmath_xml"
        )
        or profile["canonicalizer_version"] != "openmath-cdbase-alpha-c14n-v4"
    ):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition profile binding is invalid"
        )
    for field, expected in _PROFILE_FILES.items():
        if profile[field] != expected:
            raise TypedCommutativeAlgebraDecompositionManifestError(
                "primary-decomposition profile artifact path is invalid"
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
    _exact_keys(
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
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition Lean receipt binding is invalid"
        )
    toolchain = _read_relative(repository_root, _TOOLCHAIN)
    if receipt["toolchain"] != toolchain.decode("utf-8").rstrip("\n"):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition Lean toolchain is stale"
        )
    _require_digest(toolchain, _string(receipt["toolchain_sha256"], "toolchain digest"))
    witness = _read_relative(repository_root, _WITNESS)
    _require_digest(witness, _string(receipt["witness_file_sha256"], "witness digest"))
    return witness.decode("utf-8")


def _validate_digest(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    expected = _string(unsigned.pop("manifest_payload_sha256"), "manifest digest")
    if _sha256(rfc8785.dumps(cast(Any, unsigned))) != expected:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition manifest digest does not match"
        )


def _validate_card(card: Mapping[str, object], *, index: int, witness_text: str) -> None:
    _exact_keys(card, _CARD_KEYS, f"cards[{index}]")
    if (
        card["domain"] != "commutative_algebra.primary_decomposition"
        or card["difficulty"] != "undergraduate_year_2"
        or card["openmath_profile"] != TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_decomposition_v1_sealed"
        or card["compiler_receipt_status"] != "verified_local_pinned_workspace"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition card status is invalid"
        )
    statement = _string(card["canonical_statement"], f"cards[{index}].statement")
    _require_digest(
        statement.encode("utf-8"), _string(card["canonical_statement_sha256"], "statement digest")
    )
    raw = _string(card["openmath_xml"], f"cards[{index}].raw XML")
    _require_digest(raw.encode("utf-8"), _string(card["openmath_xml_sha256"], "raw XML digest"))
    canonical = _string(card["canonical_openmath_xml"], f"cards[{index}].canonical XML")
    if canonicalize_typed_commutative_algebra_decomposition_openmath_xml(raw) != canonical:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition canonical OpenMath does not match source XML"
        )
    try:
        validate_canonical_typed_commutative_algebra_decomposition_openmath_xml(canonical)
    except ValueError as exc:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition canonical OpenMath fails actual profile validator"
        ) from exc
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "canonical XML digest"),
    )
    _string(card["proof_strategy"], f"cards[{index}].strategy")
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition sketch_steps must contain 4..8 non-empty strings"
        )
    target = _string(card["lean_target"], f"cards[{index}].Lean target")
    proof = _string(card["lean_witness"], f"cards[{index}].Lean witness")
    _require_digest(target.encode("utf-8"), _string(card["lean_target_sha256"], "target digest"))
    _require_digest(proof.encode("utf-8"), _string(card["lean_witness_sha256"], "witness digest"))
    identifier = _string(card["id"], f"cards[{index}].id")
    block = _lean_card_block(witness_text, identifier)
    if _lean_normalize(target) not in _lean_normalize(block) or proof not in block:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition Lean evidence is not bound to its card"
        )
    alignment = _mapping(card["alignment"], f"cards[{index}].alignment")
    _exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition alignment status is invalid"
        )
    if any(not isinstance(value, str) or not value.strip() for value in alignment.values()):
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition alignment fields must be non-empty strings"
        )


def _lean_card_block(witness_text: str, identifier: str) -> str:
    marker = f"-- manifest card: {identifier}\n"
    start = witness_text.find(marker)
    if start < 0 or witness_text.find(marker, start + len(marker)) >= 0:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition Lean card marker is absent or repeated"
        )
    next_marker = witness_text.find("-- manifest card:", start + len(marker))
    return witness_text[start : len(witness_text) if next_marker < 0 else next_marker]


def _read_relative(root: Path, relative_path: str) -> bytes:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition artifact path escapes its allowed root"
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition artifact cannot be read"
        ) from exc


def _sha256(value: bytes) -> str:
    return _PREFIX + hashlib.sha256(value).hexdigest()


def _lean_normalize(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _require_digest(value: bytes, expected: str) -> None:
    if not expected.startswith(_PREFIX) or len(expected) != len(_PREFIX) + 64:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition digest is invalid"
        )
    if _sha256(value) != expected:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            "primary-decomposition artifact digest does not match"
        )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypedCommutativeAlgebraDecompositionManifestError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedCommutativeAlgebraDecompositionManifestError(
            f"{label} must be a non-empty string"
        )
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TypedCommutativeAlgebraDecompositionManifestError(f"{label} has unexpected fields")
