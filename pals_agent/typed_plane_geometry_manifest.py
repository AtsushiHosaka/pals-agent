"""Integrity checks for sealed ``typed-plane-geometry-v1`` authoring evidence.

This is not a Draft loader.  It binds the isolated validator, profile design,
and local Lean witnesses without publishing any card to a catalog or database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import rfc8785

from .typed_plane_geometry import (
    TYPED_PLANE_GEOMETRY_PROFILE,
    canonicalize_typed_plane_geometry_openmath_xml,
    validate_canonical_typed_plane_geometry_openmath_xml,
)

_SCHEMA = "pals.typed-plane-geometry-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_CANONICALIZER = "openmath-cdbase-alpha-c14n-v4"
_SHA256_PREFIX = "sha256:"
_REGISTRY = "pals-agent/pals_agent/content_dictionaries/typed-plane-geometry-v1-registry.json"
_DESIGN = "docs/typed-plane-geometry-v1-design.md"
_TOOLCHAIN = "pals-agent/lean-workspace/lean-toolchain"
_CARD_IDS = frozenset(
    {
        "typed_plane_distance_self_zero",
        "typed_plane_line_through_two_points",
        "typed_plane_circle_through_three_points",
        "typed_plane_perpendicular_symmetric",
        "typed_plane_parallel_symmetric",
    }
)


class TypedPlaneGeometryManifestError(ValueError):
    """Raised when sealed native-plane authoring evidence is inconsistent."""


def load_typed_plane_geometry_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]:
    """Load and fail-closed validate the sealed native-plane proposal."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedPlaneGeometryManifestError("plane-geometry manifest cannot be read.") from exc
    if not isinstance(payload, dict):
        raise TypedPlaneGeometryManifestError("plane-geometry manifest root must be an object.")
    validate_typed_plane_geometry_manifest(payload, repository_root=repository_root)
    return cast(dict[str, Any], payload)


def validate_typed_plane_geometry_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Validate immutable proposal bindings without loading or admitting a Draft."""
    _exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "profile",
            "lean_witness_bundle",
            "admitted_candidate_cards",
            "manifest_digest",
        },
        "manifest",
    )
    if payload["schema_version"] != _SCHEMA or payload["status"] != _STATUS:
        raise TypedPlaneGeometryManifestError(
            "plane-geometry manifest schema or status is invalid."
        )
    _validate_manifest_digest(payload)
    _validate_seal(_mapping(payload["seal"], "seal"))
    _validate_profile(_mapping(payload["profile"], "profile"), repository_root=repository_root)
    witness_text = _validate_witness_bundle(
        _mapping(payload["lean_witness_bundle"], "lean_witness_bundle"),
        repository_root=repository_root,
    )
    cards = payload["admitted_candidate_cards"]
    if not isinstance(cards, list) or len(cards) != len(_CARD_IDS):
        raise TypedPlaneGeometryManifestError("plane-geometry manifest has an invalid card count.")
    seen_ids: set[str] = set()
    seen_canonical: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"admitted_candidate_cards[{index}]")
        _validate_card(card, witness_text=witness_text)
        identifier = _string(card["id"], f"admitted_candidate_cards[{index}].id")
        canonical = _string(
            card["canonical_openmath_xml"],
            f"admitted_candidate_cards[{index}].canonical_openmath_xml",
        )
        if identifier in seen_ids or canonical in seen_canonical:
            raise TypedPlaneGeometryManifestError("plane-geometry manifest has a card collision.")
        seen_ids.add(identifier)
        seen_canonical.add(canonical)
    if seen_ids != _CARD_IDS:
        raise TypedPlaneGeometryManifestError("plane-geometry manifest card set is invalid.")


def _validate_manifest_digest(payload: Mapping[str, object]) -> None:
    digest = _mapping(payload["manifest_digest"], "manifest_digest")
    _exact_keys(digest, {"algorithm", "input", "sha256"}, "manifest_digest")
    if digest["algorithm"] != "sha256" or digest["input"] != (
        "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
    ):
        raise TypedPlaneGeometryManifestError("plane-geometry manifest digest metadata is invalid.")
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    _require_digest(
        rfc8785.dumps(cast(Any, unsigned)),
        _string(digest["sha256"], "manifest_digest.sha256"),
    )


def _validate_seal(seal: Mapping[str, object]) -> None:
    _exact_keys(seal, {"scope", "admission", "revision"}, "seal")
    if seal != {
        "scope": "native planar-geometry typed authoring evidence only",
        "admission": (
            "not admitted to the generic DB, seed, embedding index, local typed catalog, "
            "or PFI package"
        ),
        "revision": "typed-plane-geometry-v1-local-r1",
    }:
        raise TypedPlaneGeometryManifestError("plane-geometry manifest seal is invalid.")


def _validate_profile(profile: Mapping[str, object], *, repository_root: Path) -> None:
    _exact_keys(
        profile,
        {
            "id",
            "validator",
            "canonicalizer",
            "validator_status",
            "content_dictionary_bundle",
            "profile_design",
            "lean_toolchain",
        },
        "profile",
    )
    if (
        profile["id"] != TYPED_PLANE_GEOMETRY_PROFILE
        or profile["validator"]
        != (
            "pals_agent.typed_plane_geometry."
            "validate_canonical_typed_plane_geometry_openmath_xml"
        )
        or profile["canonicalizer"] != _CANONICALIZER
        or profile["validator_status"] != "implemented_isolated_profile"
    ):
        raise TypedPlaneGeometryManifestError("plane-geometry profile identity is invalid.")
    _validate_digest_bound_artifact(
        _mapping(profile["content_dictionary_bundle"], "profile.content_dictionary_bundle"),
        expected_path=_REGISTRY,
        expected_input="exact UTF-8 bytes of the named registry/CD bundle",
        repository_root=repository_root,
    )
    _validate_digest_bound_artifact(
        _mapping(profile["profile_design"], "profile.profile_design"),
        expected_path=_DESIGN,
        expected_input="exact UTF-8 bytes of the named profile design document",
        repository_root=repository_root,
    )
    toolchain = _mapping(profile["lean_toolchain"], "profile.lean_toolchain")
    _exact_keys(toolchain, {"relative_path", "value", "sha256", "digest_input"}, "toolchain")
    if toolchain["relative_path"] != _TOOLCHAIN or toolchain["digest_input"] != (
        "exact UTF-8 bytes of the named lean-toolchain file"
    ):
        raise TypedPlaneGeometryManifestError("plane-geometry Lean toolchain binding is invalid.")
    source = _read_relative(repository_root, _TOOLCHAIN)
    if _string(toolchain["value"], "lean_toolchain.value") != source.decode("utf-8").rstrip("\n"):
        raise TypedPlaneGeometryManifestError("plane-geometry Lean toolchain value is invalid.")
    _require_digest(source, _string(toolchain["sha256"], "lean_toolchain.sha256"))


def _validate_digest_bound_artifact(
    artifact: Mapping[str, object],
    *,
    expected_path: str,
    expected_input: str,
    repository_root: Path,
) -> None:
    _exact_keys(artifact, {"relative_path", "sha256", "digest_input"}, "artifact")
    if artifact["relative_path"] != expected_path or artifact["digest_input"] != expected_input:
        raise TypedPlaneGeometryManifestError("plane-geometry artifact binding is invalid.")
    _require_digest(
        _read_relative(repository_root, expected_path),
        _string(artifact["sha256"], "artifact.sha256"),
    )


def _validate_witness_bundle(bundle: Mapping[str, object], *, repository_root: Path) -> str:
    _exact_keys(
        bundle,
        {"relative_path", "sha256", "digest_input", "verification_command", "verification_status"},
        "lean_witness_bundle",
    )
    relative_path = _string(bundle["relative_path"], "lean_witness_bundle.relative_path")
    if (
        bundle["digest_input"]
        != "exact UTF-8 bytes of the named Lean file, including imports and final newline"
        or bundle["verification_status"] != "verified_local_pinned_workspace"
        or not isinstance(bundle["verification_command"], str)
        or not bundle["verification_command"]
    ):
        raise TypedPlaneGeometryManifestError("plane-geometry witness binding is invalid.")
    source = _read_relative(repository_root, relative_path)
    _require_digest(source, _string(bundle["sha256"], "lean_witness_bundle.sha256"))
    return source.decode("utf-8")


def _validate_card(card: Mapping[str, object], *, witness_text: str) -> None:
    _exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "canonical_statement",
            "openmath_xml",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "signature_trace",
            "signature_trace_sha256",
            "proof_strategy",
            "proof_strategy_sha256",
            "sketch_steps",
            "sketch_steps_sha256",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        "card",
    )
    for field in ("id", "domain", "difficulty", "canonical_statement", "proof_strategy"):
        _string(card[field], f"card.{field}")
    raw = _string(card["openmath_xml"], "card.openmath_xml")
    canonical = _string(card["canonical_openmath_xml"], "card.canonical_openmath_xml")
    if canonicalize_typed_plane_geometry_openmath_xml(raw) != canonical:
        raise TypedPlaneGeometryManifestError("plane-geometry card canonical OpenMath is invalid.")
    validate_canonical_typed_plane_geometry_openmath_xml(canonical)
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "card.canonical_openmath_xml_sha256"),
    )
    trace = _mapping(card["signature_trace"], "card.signature_trace")
    _exact_keys(trace, {"result_sort", "symbols"}, "signature_trace")
    if trace["result_sort"] != "Prop" or not isinstance(trace["symbols"], list):
        raise TypedPlaneGeometryManifestError("plane-geometry signature trace is invalid.")
    _require_digest(
        rfc8785.dumps(cast(Any, trace)),
        _string(card["signature_trace_sha256"], "card.signature_trace_sha256"),
    )
    strategy = _string(card["proof_strategy"], "card.proof_strategy")
    _require_digest(
        strategy.encode("utf-8"),
        _string(card["proof_strategy_sha256"], "card.proof_strategy_sha256"),
    )
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedPlaneGeometryManifestError("plane-geometry card sketch steps are invalid.")
    _require_digest(
        rfc8785.dumps(cast(Any, steps)),
        _string(card["sketch_steps_sha256"], "card.sketch_steps_sha256"),
    )
    _validate_lean(_mapping(card["lean"], "card.lean"), witness_text=witness_text)
    alignment = _mapping(card["statement_openmath_lean_alignment_review"], "card.alignment")
    _exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedPlaneGeometryManifestError("plane-geometry card alignment status is invalid.")
    for field in ("statement_to_openmath", "openmath_to_lean", "admission_gate"):
        _string(alignment[field], f"card.alignment.{field}")


def _validate_lean(lean: Mapping[str, object], *, witness_text: str) -> None:
    _exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "lean")
    target = _string(lean["target"], "card.lean.target")
    witness = _string(lean["witness"], "card.lean.witness")
    _require_digest(target.encode("utf-8"), _string(lean["target_sha256"], "target_sha256"))
    _require_digest(witness.encode("utf-8"), _string(lean["witness_sha256"], "witness_sha256"))
    if target not in witness or witness not in witness_text:
        raise TypedPlaneGeometryManifestError("plane-geometry Lean witness is not bundle-bound.")


def _read_relative(repository_root: Path, relative_path: str) -> bytes:
    candidate = (repository_root / relative_path).resolve()
    try:
        candidate.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise TypedPlaneGeometryManifestError(
            "plane-geometry artifact path escapes repository root."
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedPlaneGeometryManifestError("plane-geometry artifact cannot be read.") from exc


def _require_digest(source: bytes, expected: str) -> None:
    actual = _SHA256_PREFIX + hashlib.sha256(source).hexdigest()
    if actual != expected:
        raise TypedPlaneGeometryManifestError("plane-geometry artifact digest does not match.")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypedPlaneGeometryManifestError(f"plane-geometry `{name}` must be an object.")
    return cast(Mapping[str, object], value)


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedPlaneGeometryManifestError(
            f"plane-geometry `{name}` must be a non-empty string."
        )
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise TypedPlaneGeometryManifestError(f"plane-geometry `{name}` has an invalid field set.")
