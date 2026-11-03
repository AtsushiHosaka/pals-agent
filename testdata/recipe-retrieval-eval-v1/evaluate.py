"""Recall, false reuse and judge cost by catalog size through the real semantic path."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import random
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pals_agent import recipe_semantic
from pals_agent.openai import OpenAIError, OpenAIResponsesClient
from pals_agent.recipe_semantic_contract import (
    CONTENT_FIELDS,
    CONTENT_SCHEMA,
    EMBEDDING_ENDPOINT,
    digest,
)
from pals_agent.usage import usage_scope

HERE = Path(__file__).parent
SEEDS = HERE.parent / "requested-math-seeds-v1"
DIMENSION = 1024
WINDOW = 5
CONVENTIONS = {"policy": "default", "choices": {}}


def load_catalog(cards: Path) -> list[dict[str, Any]]:
    rows = []
    for card in json.loads((cards / "generated/search-candidates.json").read_text())["candidates"]:
        manifest = json.loads(
            (cards / "generated/manifests" / f"{card['recipe_id']}.json").read_text()
        )
        target = manifest["target_source"]
        rows.append(
            {
                **{
                    key: card[key]
                    for key in (
                        "recipe_id",
                        "recipe_revision",
                        "statement",
                        "domain",
                        "assumptions",
                        "quantifiers",
                        "conclusion",
                        "proof_method_tag",
                        "answer",
                    )
                },
                "target_source": target,
                "lean_code": f"import Mathlib\n\nexample : {target} := {manifest['proof_body']}\n",
            }
        )
    for case in json.loads((SEEDS / "corpus.json").read_text())["cases"]:
        manifest = json.loads((SEEDS / "publication" / f"{case['id']}.json").read_text())
        rows.append(
            {
                "recipe_id": case["id"],
                "recipe_revision": 1,
                "statement": case["statement"],
                "domain": case["family_id"],
                "assumptions": case["assumptions"],
                "quantifiers": [],
                "conclusion": manifest["target_source"],
                "proof_method_tag": None,
                "answer": case["answer"],
                "target_source": manifest["target_source"],
                "lean_code": (SEEDS / case["source_path"]).read_text(),
            }
        )
    return rows


def retrieval_text(row: dict[str, Any]) -> str:
    return "\n".join((row["statement"], row["domain"], row["conclusion"], *row["assumptions"]))


def embed(client: OpenAIResponsesClient, texts: list[str]) -> list[list[float]]:
    import urllib.request

    vectors: list[list[float]] = []
    for start in range(0, len(texts), 128):
        request = urllib.request.Request(
            EMBEDDING_ENDPOINT,
            json.dumps(
                {
                    "model": "text-embedding-3-large",
                    "input": texts[start : start + 128],
                    "dimensions": DIMENSION,
                }
            ).encode(),
            {"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            vectors.extend(item["embedding"] for item in json.load(response)["data"])
    return vectors


def cached_vectors(
    client: OpenAIResponsesClient, cache: Path, texts: list[str]
) -> dict[str, list[float]]:
    known = json.loads(cache.read_text()) if cache.exists() else {}
    keys = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    missing = sorted({t for t, k in zip(texts, keys, strict=True) if k not in known})
    if missing:
        for text, vector in zip(missing, embed(client, missing), strict=True):
            known[hashlib.sha256(text.encode()).hexdigest()] = vector
        cache.write_text(json.dumps(known))
    return {text: known[key] for text, key in zip(texts, keys, strict=True)}


def catalog_ids(target: str, ids: list[str], size: int) -> list[str]:
    """The target plus the same seeded distractors for this size; never the query's text."""
    rng = random.Random(f"20261102:{size}")
    others = sorted(i for i in ids if i != target)
    rng.shuffle(others)
    return [target, *others[: size - 1]]


def ranked(ids: list[str], vectors: dict[str, list[float]], query: list[float]) -> list[str]:
    def score(item: str) -> float:
        return math.fsum(a * b for a, b in zip(query, vectors[item], strict=True))

    return sorted(ids, key=lambda item: (-score(item), hashlib.sha256(item.encode()).hexdigest()))


def window(request: dict[str, Any], claim: str, rows: list[dict[str, Any]], count: int) -> dict:
    toolchain = "a" * 64
    shown = [
        {
            **row,
            "entry_sha256": hashlib.sha256(row["recipe_id"].encode()).hexdigest(),
            "output_language": "ja",
            "lean_sha256": hashlib.sha256(row["lean_code"].encode()).hexdigest(),
            "answer_sha256": hashlib.sha256(row["answer"].encode()).hexdigest(),
            "compiler_receipt_sha256": "b" * 64,
            "toolchain_sha256": toolchain,
        }
        for row in rows
    ]
    value = {
        "schema_version": "pals.recipe-catalog-window.v1",
        "request_id": request["id"],
        "claim_id": claim,
        "request_revision": 1,
        "request_context_sha256": digest(
            {"statement": request["statement"], "context_turns": [], "output_language": "ja"}
        ),
        "output_language": "ja",
        "toolchain_sha256": toolchain,
        "complete": True,
        "reason": None,
        "catalog_count": count,
        "catalog_sha256": "c" * 64,
        "retrieval_profile": "pals.recipe-retrieval.embedding-cosine.v1",
        "recipes": shown,
    }
    value["batch_sha256"] = digest(
        {"schema_version": CONTENT_SCHEMA, **{k: value[k] for k in CONTENT_FIELDS}}
    )
    return value


def judge(
    client: OpenAIResponsesClient, query: dict[str, Any], shown: list[dict[str, Any]], count: int
) -> dict[str, Any]:
    request = {
        "id": str(uuid4()),
        "revision": 1,
        "statement": query["text"],
        "output_language": "ja",
        "context_turns": [],
        "retry_count": 0,
        "formal_job_id": None,
        "project_id": None,
        "math_conventions": CONVENTIONS,
    }
    claim = str(uuid4())
    batch = window(request, claim, shown, count)
    usage: list[dict[str, Any]] = []
    started = time.perf_counter()
    try:
        with usage_scope(usage.append):
            result = recipe_semantic.attempt(
                client, request, claim, lambda _vector: batch, deadline=time.monotonic() + 90
            )
    except (recipe_semantic.SemanticReuseError, OpenAIError) as error:
        return {"error": getattr(error, "code", type(error).__name__), "usage": usage}
    seconds = time.perf_counter() - started
    assert result is not None
    selected = result.answer["lean"]["recipe_id"] if result.answer else None
    calls = result.evidence.get("recipe_semantic_attempt") or result.evidence.get(
        "recipe_semantic_correspondence"
    )
    individual = [
        {
            k: calls[role]["result"].get(k)
            for k in (
                "action",
                "recipe_id",
                "rationale",
                "tasks",
                "relevant_conventions",
                "request_scope",
                "unresolved",
            )
        }
        for role in ("assessment", "review")
    ]
    return {"selected": selected, "judges": individual, "seconds": seconds, "usage": usage}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vector-cache", type=Path, required=True)
    parser.add_argument("--sizes", default="32,100,1045")
    parser.add_argument("--polarities", default="positive,negative")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    # Near neighbours only: drop the paraphrase's own card, so any reuse is a false reuse.
    parser.add_argument("--exclude-target", action="store_true")
    # Precomputed `{"size|text": [recipe ids]}` for rankers other than the embedding profile.
    parser.add_argument("--windows", type=Path)
    args = parser.parse_args()
    # The evaluated window is already chosen, so the attempt must not call the provider again.
    recipe_semantic.query_embedding = lambda *a, **k: None
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"])
    catalog = load_catalog(args.cards)
    by_id = {row["recipe_id"]: row for row in catalog}
    ids = sorted(by_id)
    corpus = json.loads((HERE / "corpus.json").read_text())
    queries = [
        {**query, "polarity": polarity}
        for polarity, key in (("positive", "positives"), ("negative", "negatives"))
        if polarity in args.polarities.split(",")
        for query in corpus[key]
    ]
    texts = {row["recipe_id"]: retrieval_text(row) for row in catalog}
    embedded = cached_vectors(client, args.vector_cache, list(texts.values()))
    vectors = {key: embedded[text] for key, text in texts.items()}
    query_vectors = cached_vectors(client, args.vector_cache, [q["text"] for q in queries])
    done = set()
    label = "absent" if args.exclude_target else None
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            row = json.loads(line)
            done.add((row["catalog"], label or row["polarity"], row["text"]))
    lock = threading.Lock()
    windows = json.loads(args.windows.read_text()) if args.windows else None

    def run(item: tuple[int, dict[str, Any]]) -> None:
        size, query = item
        pool = catalog_ids(query["recipe_id"], ids, size)
        if args.exclude_target:
            pool = pool[1:]
        if windows is not None:
            order = windows[f"{size}|{query['text']}"]
        else:
            order = ranked(pool, vectors, query_vectors[query["text"]])
        rank = order.index(query["recipe_id"]) + 1 if query["recipe_id"] in order else 9999
        shown = [by_id[name] for name in order[:WINDOW]]
        result = judge(client, query, shown, len(pool))
        with lock, args.output.open("a") as output:
            output.write(
                json.dumps(
                    {
                        **query,
                        **({"polarity": label} if label else {}),
                        "catalog": size,
                        "rank": rank,
                        "window": order[:WINDOW],
                        **result,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    work = [
        (int(size), query)
        for size in args.sizes.split(",")
        for query in queries
        if (int(size), label or query["polarity"], query["text"]) not in done
    ]
    if args.limit:
        work = random.Random(7).sample(work, min(args.limit, len(work)))
    print(json.dumps({"queries": len(queries), "remaining": len(work)}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        for _ in pool.map(run, work):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
