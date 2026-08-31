"""Fail-closed validation for sealed local ``typed-ode-v1`` authoring evidence.

This module validates a proposal artifact only.  It is intentionally not a
generic Draft loader and performs no database, embedding, seed, or PFI action.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import rfc8785

from .typed_ode import (
    TYPED_ODE_OPENMATH_CDBASE,
    TYPED_ODE_PROFILE,
    canonicalize_typed_ode_openmath_xml,
    validate_canonical_typed_ode_openmath_xml,
)

_SCHEMA = "pals.typed-ode-v1-sealed-manifest.v1"
_STATUS = "sealed_local_authoring_revision_not_admitted"
_PREFIX = "sha256:"


class TypedOdeManifestError(ValueError):
    """Raised when local typed ODE evidence is stale, malformed, or unbound."""


def load_typed_ode_manifest(path: Path, *, repository_root: Path) -> dict[str, Any]:
    """Read and fail-closed validate one sealed ODE proposal manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedOdeManifestError("typed ODE manifest cannot be read") from exc
    if not isinstance(payload, dict):
        raise TypedOdeManifestError("typed ODE manifest root must be an object")
    validate_typed_ode_manifest(payload, repository_root=repository_root)
    return cast(dict[str, Any], payload)


def validate_typed_ode_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> None:
    """Validate an immutable v1 manifest without publishing any card."""
    _exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "immutability_contract",
            "profile",
            "source_catalog",
            "lean_witness_bundle",
            "admitted_card_count",
            "excluded_source_card_count",
            "cards",
            "manifest_digest",
        },
        "manifest",
    )
    if payload["schema_version"] != _SCHEMA or payload["status"] != _STATUS:
        raise TypedOdeManifestError("typed ODE manifest schema or status is invalid")
    _validate_seal(_mapping(payload["seal"], "seal"))
    _validate_immutability(_mapping(payload["immutability_contract"], "immutability_contract"))
    _validate_profile(_mapping(payload["profile"], "profile"), repository_root=repository_root)
    source_candidates = _validate_source(
        _mapping(payload["source_catalog"], "source_catalog"), repository_root
    )
    witness_text = _validate_witness(
        _mapping(payload["lean_witness_bundle"], "lean_witness_bundle"), repository_root
    )
    _validate_digest(payload)

    cards = payload["cards"]
    if not isinstance(cards, list) or len(cards) != 10:
        raise TypedOdeManifestError("typed ODE manifest must seal exactly ten cards")
    if payload["admitted_card_count"] != len(cards) or payload["excluded_source_card_count"] != 0:
        raise TypedOdeManifestError("typed ODE manifest card counts are invalid")
    ids: set[str] = set()
    canonical_xml: set[str] = set()
    for index, raw_card in enumerate(cards, start=1):
        card = _mapping(raw_card, f"cards[{index}]")
        _validate_card(card, witness_text=witness_text, source_candidates=source_candidates)
        card_id = _string(card["id"], f"cards[{index}].id")
        canonical = _string(
            card["canonical_openmath_xml"], f"cards[{index}].canonical_openmath_xml"
        )
        if card_id in ids or canonical in canonical_xml:
            raise TypedOdeManifestError("typed ODE manifest repeats an id or canonical OpenMath")
        ids.add(card_id)
        canonical_xml.add(canonical)


def _validate_seal(seal: Mapping[str, object]) -> None:
    _exact_keys(seal, {"scope", "admission", "revision"}, "seal")
    if seal != {
        "scope": "local typed-ode authoring evidence only",
        "admission": "not admitted to the generic DB, seed, embedding index, or PFI package",
        "revision": "typed-ode-v1-local-r1",
    }:
        raise TypedOdeManifestError("typed ODE manifest seal is invalid")


def _validate_immutability(contract: Mapping[str, object]) -> None:
    _exact_keys(
        contract,
        {"digest_algorithm", "canonical_json", "profile_c14n", "mutation_rule"},
        "immutability_contract",
    )
    if (
        contract["digest_algorithm"] != "sha256"
        or contract["canonical_json"]
        != "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
        or any(not isinstance(value, str) or not value.strip() for value in contract.values())
    ):
        raise TypedOdeManifestError("typed ODE immutability contract is invalid")


def _validate_profile(profile: Mapping[str, object], *, repository_root: Path) -> None:
    _exact_keys(
        profile,
        {
            "id",
            "typed_cdbase",
            "validator",
            "validator_status",
            "registry_path",
            "registry_sha256",
            "design_path",
            "design_sha256",
            "lean_toolchain",
        },
        "profile",
    )
    if (
        profile["id"] != TYPED_ODE_PROFILE
        or profile["typed_cdbase"] != TYPED_ODE_OPENMATH_CDBASE
        or profile["validator"]
        != "pals_agent.typed_ode.validate_canonical_typed_ode_openmath_xml"
        or profile["validator_status"] != "implemented_isolated_profile"
        or profile["registry_path"]
        != "pals_agent/content_dictionaries/typed-ode-v1-registry.json"
        or profile["design_path"] != "docs/typed-ode-v1-design.md"
    ):
        raise TypedOdeManifestError("typed ODE profile binding is invalid")
    _require_digest(
        _read_relative(
            repository_root / "pals-agent",
            _string(profile["registry_path"], "registry_path"),
        ),
        _string(profile["registry_sha256"], "registry_sha256"),
    )
    _require_digest(
        _read_relative(repository_root, _string(profile["design_path"], "design_path")),
        _string(profile["design_sha256"], "design_sha256"),
    )
    toolchain = _mapping(profile["lean_toolchain"], "lean_toolchain")
    _exact_keys(toolchain, {"path", "value", "sha256"}, "lean_toolchain")
    path = _string(toolchain["path"], "lean_toolchain.path")
    source = _read_relative(repository_root, path)
    if toolchain["value"] != source.decode("utf-8").rstrip("\n"):
        raise TypedOdeManifestError("typed ODE Lean toolchain value is invalid")
    _require_digest(source, _string(toolchain["sha256"], "lean_toolchain.sha256"))


def _validate_source(
    source: Mapping[str, object], repository_root: Path
) -> dict[str, str]:
    _exact_keys(source, {"path", "sha256", "selection"}, "source_catalog")
    if (
        source["path"] != "docs/probability-ode-draft-candidates.json"
        or source["selection"]
        != "all ten current_openmath_cards with domain ordinary_differential_equations"
    ):
        raise TypedOdeManifestError("typed ODE source binding is invalid")
    bytes_ = _read_relative(repository_root, _string(source["path"], "source_catalog.path"))
    _require_digest(bytes_, _string(source["sha256"], "source_catalog.sha256"))
    try:
        raw = json.loads(bytes_.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TypedOdeManifestError("typed ODE source catalog is unreadable") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("current_openmath_cards"), list):
        raise TypedOdeManifestError("typed ODE source catalog has no current cards")
    candidates: dict[str, str] = {}
    for candidate in raw["current_openmath_cards"]:
        if (
            not isinstance(candidate, dict)
            or candidate.get("domain") != "ordinary_differential_equations"
        ):
            continue
        card_id = candidate.get("id")
        statement = candidate.get("canonical_statement")
        if not isinstance(card_id, str) or not isinstance(statement, str) or not statement:
            raise TypedOdeManifestError("typed ODE source candidate is invalid")
        candidates[card_id] = statement
    if len(candidates) != 10:
        raise TypedOdeManifestError("typed ODE source catalog must contain exactly ten ODE cards")
    return candidates


def _validate_witness(bundle: Mapping[str, object], repository_root: Path) -> str:
    _exact_keys(
        bundle,
        {"path", "sha256", "verification_command", "verification_status"},
        "lean_witness_bundle",
    )
    if (
        bundle["path"] != "docs/typed-ode-v1-authoring-witnesses.lean"
        or bundle["verification_command"]
        != (
            "cd pals-agent/lean-workspace && lake env lean "
            "../../docs/typed-ode-v1-authoring-witnesses.lean"
        )
        or bundle["verification_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedOdeManifestError("typed ODE Lean witness binding is invalid")
    source = _read_relative(repository_root, _string(bundle["path"], "lean_witness_bundle.path"))
    _require_digest(source, _string(bundle["sha256"], "lean_witness_bundle.sha256"))
    return source.decode("utf-8")


def _validate_digest(payload: Mapping[str, object]) -> None:
    digest = _mapping(payload["manifest_digest"], "manifest_digest")
    _exact_keys(digest, {"algorithm", "input", "sha256"}, "manifest_digest")
    if (
        digest["algorithm"] != "sha256"
        or digest["input"]
        != "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
    ):
        raise TypedOdeManifestError("typed ODE manifest digest metadata is invalid")
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    if digest["sha256"] != _sha(rfc8785.dumps(cast(Any, unsigned))):
        raise TypedOdeManifestError("typed ODE manifest digest is stale or mismatched")


def _validate_card(
    card: Mapping[str, object],
    *,
    witness_text: str,
    source_candidates: Mapping[str, str],
) -> None:
    _exact_keys(
        card,
        {
            "id",
            "source_candidate_id",
            "source_candidate_statement_sha256",
            "openmath_profile",
            "domain",
            "level",
            "topic",
            "difficulty",
            "canonical_statement",
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
            "openmath_to_lean_alignment",
            "profile_validation_status",
            "compiler_receipt_status",
        },
        "card",
    )
    if (
        card["source_candidate_id"] != card["id"]
        or card["openmath_profile"] != TYPED_ODE_PROFILE
        or card["domain"] != "ordinary_differential_equations"
        or card["level"] != "undergraduate_year_2"
        or card["profile_validation_status"] != "validated_local_typed_ode_v1_sealed"
        or card["compiler_receipt_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedOdeManifestError("typed ODE card metadata is invalid")
    card_id = _string(card["id"], "card.id")
    source_statement = source_candidates.get(card_id)
    if source_statement is None or card["source_candidate_statement_sha256"] != _sha(
        source_statement.encode("utf-8")
    ):
        raise TypedOdeManifestError("typed ODE card source statement binding is stale")
    for field in (
        "id",
        "topic",
        "difficulty",
        "canonical_statement",
        "proof_strategy",
        "openmath_to_lean_alignment",
    ):
        _string(card[field], f"card.{field}")
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 8
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedOdeManifestError("typed ODE card sketch must contain 4..8 non-empty steps")
    raw = _string(card["openmath_xml"], "card.openmath_xml")
    canonical = _string(card["canonical_openmath_xml"], "card.canonical_openmath_xml")
    if canonicalize_typed_ode_openmath_xml(raw) != canonical:
        raise TypedOdeManifestError("typed ODE card canonical OpenMath is stale")
    validate_canonical_typed_ode_openmath_xml(canonical)
    _require_digest(
        raw.encode("utf-8"), _string(card["openmath_xml_sha256"], "openmath_xml_sha256")
    )
    _require_digest(
        canonical.encode("utf-8"),
        _string(card["canonical_openmath_xml_sha256"], "canonical_openmath_xml_sha256"),
    )
    target = _string(card["lean_target"], "lean_target")
    witness = _string(card["lean_witness"], "lean_witness")
    _require_digest(
        target.encode("utf-8"),
        _string(card["lean_target_sha256"], "lean_target_sha256"),
    )
    _require_digest(
        witness.encode("utf-8"),
        _string(card["lean_witness_sha256"], "lean_witness_sha256"),
    )
    if f"{target} := {witness}" not in witness_text:
        raise TypedOdeManifestError("typed ODE card Lean evidence is not in the witness bundle")


def _read_relative(root: Path, relative_path: str) -> bytes:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedOdeManifestError("typed ODE artifact path escapes its root") from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedOdeManifestError("typed ODE artifact cannot be read") from exc


def _require_digest(data: bytes, expected: str) -> None:
    if expected != _sha(data):
        raise TypedOdeManifestError("typed ODE artifact digest is stale or mismatched")


def _sha(data: bytes) -> str:
    return _PREFIX + hashlib.sha256(data).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypedOdeManifestError(f"typed ODE {label} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypedOdeManifestError(f"typed ODE {label} must be a non-empty string")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TypedOdeManifestError(f"typed ODE {label} has an invalid field set")
