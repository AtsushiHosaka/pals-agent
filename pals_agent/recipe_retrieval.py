"""Query vectors for API-side Recipe ranking; a vector never establishes correspondence."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from pals_agent.draft_embeddings import EmbeddingError
from pals_agent.http_transport import HardDeadlineHttpError
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_semantic_contract import (
    BINDING_SHA256,
    EMBEDDING_DIMENSION,
    EMBEDDING_ENDPOINT,
    EMBEDDING_MODEL,
    digest,
)

QUERY_SECONDS = 3.0
_ROLE = "recipe_retrieval_embedding"


def retrieval_text(entry: dict[str, Any]) -> str:
    """The exact entry description that the API ranks and that release vectors embed."""
    return "\n".join(
        (entry["statement"], entry["domain"], entry["conclusion"], *entry["assumptions"])
    )


def _model(api_key: str, transport: Any, timeout_seconds: float) -> Any:
    # proof_reuse_catalog imports the reuse runtime, which imports this module.
    from pals_agent.proof_reuse_catalog import BoundedEmbeddingModel

    return BoundedEmbeddingModel(
        api_key=api_key,
        revision=EMBEDDING_MODEL,
        model=EMBEDDING_MODEL,
        dimension=EMBEDDING_DIMENSION,
        timeout_seconds=timeout_seconds,
        role=_ROLE,
        **({"transport": transport} if transport is not None else {}),
    )


def query_embedding(
    client: OpenAIResponsesClient, statement: str, *, deadline: float
) -> list[float] | None:
    """One bounded metered call; no vector only lowers ranking quality, never a gate."""
    remaining = min(QUERY_SECONDS, deadline - time.monotonic())
    if remaining < 0.2 or client.base_url.rstrip("/") + "/embeddings" != EMBEDDING_ENDPOINT:
        return None
    try:
        vector = _model(client.api_key, client.transport, remaining).embed(statement)
    except (EmbeddingError, HardDeadlineHttpError, ValueError, TypeError):
        return None
    return vector if any(vector) and all(math.isfinite(item) for item in vector) else None


def main(arguments: list[str] | None = None) -> int:
    """Release helper: embed canonical search entries for `lean-recipe-retrieval-admit`."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key or args.output.exists():
        print("OPENAI_API_KEY and a new output path are required", file=sys.stderr)
        return 2
    model = _model(key, None, 30.0)
    vectors = [
        {"entry_sha256": digest(entry), "embedding": model.embed(retrieval_text(entry))}
        for entry in json.loads(args.entries.read_text())
    ]
    args.output.write_text(
        json.dumps({"binding_sha256": BINDING_SHA256, "vectors": vectors}, separators=(",", ":"))
    )
    print(json.dumps({"vectors": len(vectors)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
