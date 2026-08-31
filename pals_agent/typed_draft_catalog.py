"""Validation for immutable, not-yet-published typed Draft authoring manifests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import rfc8785

from .typed_math import (
    TYPED_MATH_PROFILE,
    canonicalize_typed_math_openmath_xml,
    validate_canonical_typed_math_openmath_xml,
)

_SCHEMA_VERSION = "pals.typed-math-v1-authoring-manifest.v1"
_PROPOSAL_STATUS = "not_admitted_requires_independent_project_review"
_CANONICALIZER = "openmath-cdbase-alpha-c14n-v4"
_REGISTRY_PATH = "pals_agent/content_dictionaries/typed-math-v1-registry.json"
_SHA256_PREFIX = "sha256:"


class TypedAuthoringManifestError(ValueError):
    """Raised when typed authoring evidence is incomplete or inconsistent."""


def load_typed_authoring_manifest(path: Path) -> dict[str, Any]:
    """Read and validate an immutable typed authoring manifest below its package root."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedAuthoringManifestError("Typed authoring manifest cannot be read.") from exc
    if not isinstance(payload, dict):
        raise TypedAuthoringManifestError("Typed authoring manifest root must be an object.")
    validate_typed_authoring_manifest(payload, root=Path(__file__).resolve().parents[1])
    return cast(dict[str, Any], payload)


def validate_typed_authoring_manifest(
    payload: Mapping[str, object],
    *,
    root: Path,
) -> None:
    """Validate one typed authoring manifest without publishing it anywhere."""
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "proposal_status",
            "profile",
            "lean_witness_bundle",
            "cards",
            "manifest_digest",
        },
        "manifest",
    )
    if payload["schema_version"] != _SCHEMA_VERSION:
        raise TypedAuthoringManifestError("Typed authoring manifest schema_version is invalid.")
    if payload["proposal_status"] != _PROPOSAL_STATUS:
        raise TypedAuthoringManifestError("Typed authoring manifest proposal_status is invalid.")

    _validate_manifest_digest(payload)
    profile = _mapping(payload["profile"], "profile")
    _validate_profile(profile, root=root)
    witness_bundle = _mapping(payload["lean_witness_bundle"], "lean_witness_bundle")
    witness_text = _validate_witness_bundle(witness_bundle, root=root)

    cards = payload["cards"]
    if not isinstance(cards, list) or not cards:
        raise TypedAuthoringManifestError(
            "Typed authoring manifest cards must be a non-empty list."
        )
    seen_ids: set[str] = set()
    seen_openmath: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"cards[{index}]")
        _validate_card(card, witness_text=witness_text)
        card_id = _string(card["id"], f"cards[{index}].id")
        canonical = _string(
            card["canonical_openmath_xml"], f"cards[{index}].canonical_openmath_xml"
        )
        if card_id in seen_ids:
            raise TypedAuthoringManifestError(
                f"Typed authoring manifest repeats card id `{card_id}`."
            )
        if canonical in seen_openmath:
            raise TypedAuthoringManifestError(
                "Typed authoring manifest repeats canonical typed OpenMath."
            )
        seen_ids.add(card_id)
        seen_openmath.add(canonical)


def _validate_manifest_digest(payload: Mapping[str, object]) -> None:
    digest = _mapping(payload["manifest_digest"], "manifest_digest")
    _require_exact_keys(digest, {"algorithm", "input", "sha256"}, "manifest_digest")
    if digest["algorithm"] != "sha256" or digest["input"] != (
        "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
    ):
        raise TypedAuthoringManifestError("Typed authoring manifest digest metadata is invalid.")
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    actual = _sha256(rfc8785.dumps(cast(Any, unsigned)))
    if digest["sha256"] != actual:
        raise TypedAuthoringManifestError("Typed authoring manifest digest does not match.")


def _validate_profile(profile: Mapping[str, object], *, root: Path) -> None:
    _require_exact_keys(
        profile,
        {
            "id",
            "validator",
            "canonicalizer",
            "admission_openmath_field",
            "cd_bundle",
            "lean_toolchain",
        },
        "profile",
    )
    if (
        profile["id"] != TYPED_MATH_PROFILE
        or profile["validator"]
        != "pals_agent.typed_math.validate_canonical_typed_math_openmath_xml"
        or profile["canonicalizer"] != _CANONICALIZER
        or profile["admission_openmath_field"] != "canonical_openmath_xml"
    ):
        raise TypedAuthoringManifestError("Typed authoring manifest profile is invalid.")

    cd_bundle = _mapping(profile["cd_bundle"], "profile.cd_bundle")
    _require_exact_keys(cd_bundle, {"registry_path", "sha256", "digest_input"}, "profile.cd_bundle")
    if (
        cd_bundle["registry_path"] != _REGISTRY_PATH
        or cd_bundle["digest_input"] != "exact UTF-8 bytes of the named registry file"
    ):
        raise TypedAuthoringManifestError("Typed authoring manifest registry binding is invalid.")
    _require_artifact_digest(
        root,
        _REGISTRY_PATH,
        _string(cd_bundle["sha256"], "profile.cd_bundle.sha256"),
    )

    toolchain = _mapping(profile["lean_toolchain"], "profile.lean_toolchain")
    _require_exact_keys(
        toolchain, {"path", "value", "sha256", "digest_input"}, "profile.lean_toolchain"
    )
    toolchain_path = _string(toolchain["path"], "profile.lean_toolchain.path")
    if toolchain["digest_input"] != "exact UTF-8 bytes of the named lean-toolchain file":
        raise TypedAuthoringManifestError(
            "Typed authoring manifest Lean toolchain binding is invalid."
        )
    toolchain_bytes = _read_artifact(root, toolchain_path)
    if _string(toolchain["value"], "profile.lean_toolchain.value") != toolchain_bytes.decode(
        "utf-8"
    ).rstrip("\n"):
        raise TypedAuthoringManifestError(
            "Typed authoring manifest Lean toolchain value is invalid."
        )
    _require_digest(toolchain_bytes, _string(toolchain["sha256"], "profile.lean_toolchain.sha256"))


def _validate_witness_bundle(bundle: Mapping[str, object], *, root: Path) -> str:
    _require_exact_keys(
        bundle,
        {"path", "sha256", "digest_input", "verification_command", "verification_status"},
        "lean_witness_bundle",
    )
    path = _string(bundle["path"], "lean_witness_bundle.path")
    if (
        bundle["digest_input"]
        != "exact UTF-8 bytes of the named Lean file, including import and final newline"
        or bundle["verification_status"] != "verified_local_pinned_workspace"
        or not isinstance(bundle["verification_command"], str)
        or not bundle["verification_command"]
    ):
        raise TypedAuthoringManifestError("Typed authoring manifest witness bundle is invalid.")
    source = _read_artifact(root, path)
    _require_digest(source, _string(bundle["sha256"], "lean_witness_bundle.sha256"))
    return source.decode("utf-8")


def _validate_card(card: Mapping[str, object], *, witness_text: str) -> None:
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "canonical_statement",
            "openmath_xml",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "proof_strategy",
            "sketch_steps",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        "card",
    )
    for field in ("id", "domain", "difficulty", "canonical_statement", "proof_strategy"):
        _string(card[field], f"card.{field}")
    raw_openmath = _string(card["openmath_xml"], "card.openmath_xml")
    canonical = _string(card["canonical_openmath_xml"], "card.canonical_openmath_xml")
    if canonicalize_typed_math_openmath_xml(raw_openmath) != canonical:
        raise TypedAuthoringManifestError(
            "Typed card canonical OpenMath does not match its source XML."
        )
    validate_canonical_typed_math_openmath_xml(canonical)
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "card.canonical_openmath_xml_sha256"),
    )

    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 10
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedAuthoringManifestError(
            "Typed card sketch_steps must contain 4..10 non-empty steps."
        )

    lean = _mapping(card["lean"], "card.lean")
    _require_exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "card.lean")
    target = _string(lean["target"], "card.lean.target")
    witness = _string(lean["witness"], "card.lean.witness")
    _require_digest(
        target.encode("utf-8"), _string(lean["target_sha256"], "card.lean.target_sha256")
    )
    _require_digest(
        witness.encode("utf-8"), _string(lean["witness_sha256"], "card.lean.witness_sha256")
    )
    if target not in witness or witness not in witness_text:
        raise TypedAuthoringManifestError(
            "Typed card Lean evidence is not bound to the witness bundle."
        )

    alignment = _mapping(card["statement_openmath_lean_alignment_review"], "card.alignment")
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "card.alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedAuthoringManifestError("Typed card alignment review status is invalid.")
    for field in ("statement_to_openmath", "openmath_to_lean", "admission_gate"):
        _string(alignment[field], f"card.alignment.{field}")


def _read_artifact(root: Path, relative_path: str) -> bytes:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedAuthoringManifestError(
            "Typed authoring artifact path escapes the package root."
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedAuthoringManifestError("Typed authoring artifact cannot be read.") from exc


def _require_artifact_digest(root: Path, relative_path: str, expected: str) -> None:
    _require_digest(_read_artifact(root, relative_path), expected)


def _require_digest(data: bytes, expected: str) -> None:
    if expected != _sha256(data):
        raise TypedAuthoringManifestError("Typed authoring artifact digest does not match.")


def _sha256(data: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypedAuthoringManifestError(f"Typed authoring `{name}` must be an object.")
    return cast(Mapping[str, object], value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedAuthoringManifestError(f"Typed authoring `{name}` must be a non-empty string.")
    return value


def _require_exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise TypedAuthoringManifestError(f"Typed authoring `{name}` has an invalid field set.")
