"""DCE preparation: validate real typed manifests and bind content to real embeddings.

Produces unsigned bytes for an independent reviewer. It cannot approve or publish its
own output. It never treats the existing *_not_admitted authoring status as approval.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import rfc8785

from pals_agent import typed_local_catalog as local


def profile_bindings(repository_root: Path) -> dict[str, dict[str, Any]]:
    bindings = {}
    for value in vars(local).values():
        if isinstance(value, local._ProfileSpec):
            profile = local._profile_binding(value, repository_root=repository_root)
            bindings[profile.profile_id] = {
                "profile_id": profile.profile_id,
                "validator_sha256": profile.validator_module_sha256.removeprefix("sha256:"),
                "registry_sha256": profile.registry_sha256.removeprefix("sha256:"),
                "canonicalizer_version": local.TYPED_OPENMATH_CANONICALIZER_VERSION,
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-small",
                "embedding_dimension": 384,
                "embedding_revision": "openai-release-2024-01-25",
                "embedding_input_version": local.TYPED_EMBEDDING_INPUT_VERSION,
            }
    return bindings


def prepare_layout(
    manifest_path: Path,
    *,
    repository_root: Path,
    author_id: str,
    embeddings: dict[str, list[float]],
    coverage_families: list[str],
) -> bytes:
    manifest = local.load_typed_local_catalog_manifest(
        manifest_path, repository_root=repository_root
    )
    if not author_id.strip() or not 1 <= len(manifest.cards) <= 4096:
        raise ValueError("author or population invalid")
    if set(embeddings) != {card.card_id for card in manifest.cards}:
        raise ValueError("embedding population mismatch")
    rows = []
    for card in manifest.cards:
        vector = embeddings[card.card_id]
        if (
            len(vector) != 384
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
            or not any(vector)
        ):
            raise ValueError("embedding invalid")
        rows.append(
            {
                "id": card.card_id,
                "canonical_statement": card.canonical_statement,
                "openmath_xml": card.canonical_openmath_xml,
                "proof_strategy": card.proof_strategy,
                "sketch_steps": list(card.sketch_steps),
                "embedding": [float(x) for x in vector],
            }
        )
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "pals.typed-catalog-layout.v1",
                "generation_id": str(uuid4()),
                "binding": profile_bindings(repository_root)[manifest.profile.profile_id],
                "author_id": author_id,
                "source_manifest_sha256": manifest.manifest_digest.removeprefix("sha256:"),
                "coverage_families": coverage_families,
                "rows": rows,
            },
        )
    )


def prepare_from_rows(
    *,
    profile_id: str,
    author_id: str,
    rows: list[dict[str, Any]],
    coverage_families: list[str],
    embedding_model: Any,
) -> bytes:
    """New authoring entry: Lean evidence is neither accepted nor required for Drafts."""
    from pals_agent.private_typed_candidates import profile_contract

    spec, binding = profile_contract(profile_id)
    if (
        embedding_model.model,
        embedding_model.dimension,
        embedding_model.revision,
        embedding_model.endpoint_identity,
        embedding_model.deployment_identity,
    ) != (
        "text-embedding-3-small",
        384,
        "openai-release-2024-01-25",
        "https://api.openai.com/v1",
        "text-embedding-3-small",
    ):
        raise ValueError("Embedding binding invalid")
    if not 1 <= len(rows) <= 4096:
        raise ValueError("Draft population invalid")
    normalized = []
    seen_ids = set()
    seen_xml = set()
    for row in rows:
        if set(row) != {
            "id",
            "canonical_statement",
            "openmath_xml",
            "proof_strategy",
            "sketch_steps",
        }:
            raise ValueError("Draft source must have only retrieval fields")
        xml = spec.canonicalize(row["openmath_xml"])
        spec.validate_canonical(xml)
        if row["id"] in seen_ids or xml in seen_xml:
            raise ValueError("Duplicate Draft pattern")
        if any(
            not isinstance(row[k], str) or not row[k].strip()
            for k in ("id", "canonical_statement", "proof_strategy")
        ):
            raise ValueError("Empty Draft field")
        if (
            not isinstance(row["sketch_steps"], list)
            or not row["sketch_steps"]
            or any(not isinstance(x, str) or not x.strip() for x in row["sketch_steps"])
        ):
            raise ValueError("Invalid Sketch")
        seen_ids.add(row["id"])
        seen_xml.add(xml)
        normalized.append({**row, "openmath_xml": xml})
    # Validate every row before spending the provider budget.
    embedded = []
    for row in normalized:
        vector = embedding_model.embed(
            f"{binding['embedding_input_version']}\nprofile_id={profile_id}\ncanonical_openmath_xml={row['openmath_xml']}"
        )
        if len(vector) != 384 or not any(vector) or any(not math.isfinite(x) for x in vector):
            raise ValueError("Embedding response invalid")
        embedded.append({**row, "embedding": vector})
    import hashlib

    return rfc8785.dumps(
        cast(
            Any,
            dict(
                schema_version="pals.typed-catalog-layout.v1",
                generation_id=str(uuid4()),
                binding=binding,
                author_id=author_id,
                source_manifest_sha256=hashlib.sha256(
                    rfc8785.dumps(cast(Any, normalized))
                ).hexdigest(),
                coverage_families=coverage_families,
                rows=embedded,
            ),
        )
    )


def main() -> int:
    import argparse
    import os

    from pals_agent.draft_embeddings import OpenAIEmbeddingModel

    parser = argparse.ArgumentParser(
        description="Prepare typed Draft bytes with real embeddings; independent review required."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--author-id", required=True)
    parser.add_argument("--family", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not exist")
    manifest = local.load_typed_local_catalog_manifest(
        args.manifest, repository_root=args.repository_root
    )
    rows = [
        dict(
            id=c.card_id,
            canonical_statement=c.canonical_statement,
            openmath_xml=c.canonical_openmath_xml,
            proof_strategy=c.proof_strategy,
            sketch_steps=list(c.sketch_steps),
        )
        for c in manifest.cards
    ]
    model = OpenAIEmbeddingModel(
        api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("PALS_OPENAI_API_KEY", ""),
        revision="openai-release-2024-01-25",
        timeout_seconds=15,
    )
    try:
        payload = prepare_from_rows(
            profile_id=manifest.profile.profile_id,
            author_id=args.author_id,
            rows=rows,
            coverage_families=args.family,
            embedding_model=model,
        )
        import hashlib
        import json

        value = json.loads(payload)
        value["source_manifest_sha256"] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        args.output.write_bytes(rfc8785.dumps(value) + b"\n")
    except Exception:
        print("Typed preparation failed; no release approval or activation performed.")
        return 2
    print(f"Prepared {len(rows)} typed Drafts; independent review and runtime evaluation required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
