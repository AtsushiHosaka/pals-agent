"""Append-only authoring batches using existing, exactly pinned typed profiles.

This adapter binds optional Lean evidence to the retrieval content, but does not
infer semantic alignment, compiler success, independent review or publication.
The ordinary typed release gates still apply to these authoring-only rows.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import rfc8785

from pals_agent import typed_local_catalog as local

SCHEMA = "pals.typed-catalog-expansion-batch.v1"
AUTHORING_STATUS = "local_authoring_evidence_bound_not_admitted"
_CARD_KEYS = {
    "id",
    "canonical_statement",
    "proof_strategy",
    "sketch_steps",
    "openmath_xml",
    "lean_target",
    "lean_witness",
}
_EVIDENCE_KEYS = {
    "witness_path",
    "witness_sha256",
    "toolchain",
    "mathlib_revision",
    "validator_sha256",
    "registry_sha256",
}


def witness_source(cards: Sequence[Mapping[str, Any]]) -> str:
    """The entire compiled source, with no unbound auxiliary declarations."""
    return (
        "import Mathlib\n\n"
        + "\n\n".join(
            f"-- manifest card: {card['id']}\n{card['lean_target']} := "
            f"{card['lean_witness'].rstrip()}"
            for card in cards
        )
        + "\n"
    )


def _text(value: object, name: str, limit: int = 65536) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise local.TypedLocalCatalogError(f"Invalid expansion {name}")
    return value


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_expansion_batch(
    payload: Mapping[str, object],
    *,
    repository_root: Path,
) -> local.TypedCatalogManifest:
    local._require_exact_keys(
        payload, {"schema_version", "profile_id", "cards", "evidence"}, "expansion batch"
    )
    if payload["schema_version"] != SCHEMA:
        raise local.TypedLocalCatalogError("Unsupported expansion schema")
    profile_id = _text(payload["profile_id"], "profile_id", 128)
    specs = {
        spec.profile_id: spec
        for spec in vars(local).values()
        if isinstance(spec, local._ProfileSpec)
    }
    if profile_id not in specs:
        from .typed_expansion_profiles import expansion_profile_spec

        spec = expansion_profile_spec(profile_id)
        if spec is not None:
            specs[profile_id] = spec
    if profile_id not in specs:
        raise local.TypedLocalCatalogError("Unsupported expansion profile")
    spec = specs[profile_id]
    profile = local._profile_binding(spec, repository_root=repository_root)
    evidence = local._mapping(payload["evidence"], "expansion evidence")
    local._require_exact_keys(evidence, _EVIDENCE_KEYS, "expansion evidence")
    if (evidence["validator_sha256"], evidence["registry_sha256"]) != (
        profile.validator_module_sha256,
        profile.registry_sha256,
    ):
        raise local.TypedLocalCatalogError("Expansion profile evidence is stale")
    toolchain = (
        local._read_relative(repository_root, "pals-agent/lean-workspace/lean-toolchain")
        .decode()
        .strip()
    )
    packages = json.loads(
        local._read_relative(repository_root, "pals-agent/lean-workspace/lake-manifest.json")
    )["packages"]
    mathlib = next(p["rev"] for p in packages if p["name"] == "mathlib")
    if (evidence["toolchain"], evidence["mathlib_revision"]) != (toolchain, mathlib):
        raise local.TypedLocalCatalogError("Expansion Lean environment is stale")
    rows = payload["cards"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise local.TypedLocalCatalogError("Expansion population must be 1..256")
    digest = _digest(rfc8785.dumps(cast(Any, dict(payload))))
    cards = []
    source_cards = []
    ids: set[str] = set()
    xmls: set[str] = set()
    for raw in rows:
        row = local._mapping(raw, "expansion card")
        local._require_exact_keys(row, _CARD_KEYS, "expansion card")
        identifier = _text(row["id"], "id", 128)
        if re.fullmatch(r"[a-z][a-z0-9_.-]*", identifier) is None:
            raise local.TypedLocalCatalogError("Invalid expansion card id")
        statement = _text(row["canonical_statement"], "statement")
        strategy = _text(row["proof_strategy"], "strategy")
        xml = spec.validate_canonical(_text(row["openmath_xml"], "OpenMath"))
        steps = local._require_nonempty_string_list(row["sketch_steps"], "expansion Sketch")
        if not 4 <= len(steps) <= 10 or any(len(s.encode()) > 20000 for s in steps):
            raise local.TypedLocalCatalogError("Expansion Sketch must contain 4..10 bounded steps")
        target = _text(row["lean_target"], "Lean target")
        proof = _text(row["lean_witness"], "Lean proof")
        if not target.startswith("example ") or not proof.startswith("by"):
            raise local.TypedLocalCatalogError("Expansion requires an example and tactic proof")
        # This is an authoring lint, not a replacement for Lean or semantic review.
        if re.search(r"\b(sorry|admit|axiom|unsafe)\b", target + "\n" + proof):
            raise local.TypedLocalCatalogError("Expansion proof contains an unchecked construct")
        if identifier in ids or xml in xmls:
            raise local.TypedLocalCatalogError("Expansion repeats an id or canonical OpenMath")
        ids.add(identifier)
        xmls.add(xml)
        source_cards.append(dict(row))
        cards.append(
            local.TypedCatalogCard(
                profile_id=profile_id,
                manifest_digest=digest,
                card_id=identifier,
                canonical_statement=statement,
                canonical_openmath_xml=xml,
                canonical_openmath_xml_sha256=_digest(xml.encode()),
                proof_strategy=strategy,
                sketch_steps=tuple(steps),
                openmath_canonicalizer_version=local.TYPED_OPENMATH_CANONICALIZER_VERSION,
            )
        )
    source_path = _text(evidence["witness_path"], "witness_path", 512)
    if not source_path.startswith("docs/") or not source_path.endswith(".lean"):
        raise local.TypedLocalCatalogError("Expansion witness must be a docs Lean artifact")
    source = local._read_relative(repository_root, source_path)
    if source != witness_source(source_cards).encode() or evidence["witness_sha256"] != _digest(
        source
    ):
        raise local.TypedLocalCatalogError("Expansion witness bytes do not match its cards")
    return local.TypedCatalogManifest(
        profile=profile,
        manifest_digest=digest,
        manifest_schema_version=SCHEMA,
        authoring_status=AUTHORING_STATUS,
        cards=tuple(cards),
    )
