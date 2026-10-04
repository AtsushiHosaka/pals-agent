"""DCE real runtime evaluator. Produces unsigned observations, never approvals.

Verified completion is read from an actual API-owned proof job with the exact query,
not from corpus booleans. Missing proofs lower the metric and prevent activation.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from typing import Any, cast

import rfc8785

from pals_agent.api_client import PalsApiClient
from pals_agent.draft_embeddings import OpenAIEmbeddingModel
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.private_draft_candidates import _decode_json, _exact_object, _hex64, _text
from pals_agent.private_typed_candidates import PrivateTypedCandidateClient, profile_contract
from pals_agent.proof_flow_reranker import OpenAIDraftReranker
from pals_agent.typed_runtime import TypedProofFlowRuntime


def evaluate(
    corpus: dict[str, Any],
    runtime: TypedProofFlowRuntime,
    proof_api: PalsApiClient,
    evaluator_id: str,
) -> dict[str, Any]:
    _exact_object(corpus, {"schema_version", "profile_id", "layout_sha256", "queries"})
    if corpus["schema_version"] != "pals.typed-catalog-evaluation-corpus.v1":
        raise ValueError("Corpus version invalid")
    _hex64(corpus["layout_sha256"])
    spec, _ = profile_contract(corpus["profile_id"])
    queries = corpus["queries"]
    if not isinstance(queries, list) or not 2 <= len(queries) <= 256:
        raise ValueError("Corpus population invalid")
    # Validate complete corpus before any model spend.
    for row in queries:
        _exact_object(
            row,
            {
                "family_id",
                "statement",
                "canonical_openmath_xml",
                "expected_draft_ids",
                "proof_job_id",
            },
        )
        _text(row["statement"])
        _text(row["family_id"])
        spec.validate_canonical(row["canonical_openmath_xml"])
        if not isinstance(row["expected_draft_ids"], list) or len(
            set(row["expected_draft_ids"])
        ) != len(row["expected_draft_ids"]):
            raise ValueError("Expected IDs invalid")
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in queries:
        expected = set(row["expected_draft_ids"])
        result = runtime.retrieve_for_profile(corpus["profile_id"], row["statement"])
        if result.compatibility.get("seed_manifest_sha256") != "sha256:" + corpus["layout_sha256"]:
            raise ValueError("Evaluation population changed")
        selected = {item.candidate.draft.id for item in result.contexts}
        ranks = [
            index + 1
            for index, identifier in enumerate(result.candidate_ids)
            if identifier in expected
        ]
        verified = False
        if expected and row["proof_job_id"]:
            proof = proof_api.get_proof_job(row["proof_job_id"])
            verified = proof.get("state") == "verified" and " ".join(
                proof.get("theorem_statement", "").split()
            ) == " ".join(row["statement"].split())
        groups.setdefault(row["family_id"], []).append(
            dict(
                positive=bool(expected),
                structured=result.query_openmath == row["canonical_openmath_xml"],
                recall=len(set(result.candidate_ids) & expected) / len(expected)
                if expected
                else 0.0,
                reciprocal_rank=1 / min(ranks) if ranks else 0.0,
                false_match=bool(selected) and not expected,
                false_no_match=bool(expected) and not bool(selected & expected),
                verified=verified,
            )
        )
    families = []
    for family, observations in sorted(groups.items()):
        positives = [row for row in observations if row["positive"]]
        negatives = [row for row in observations if not row["positive"]]
        if not positives or not negatives:
            raise ValueError("Every family requires positive and hard-negative queries")
        families.append(
            dict(
                family_id=family,
                positives=len(positives),
                hard_negatives=len(negatives),
                structuring_success=sum(x["structured"] for x in observations) / len(observations),
                recall_at_8=sum(x["recall"] for x in positives) / len(positives),
                reciprocal_rank=sum(x["reciprocal_rank"] for x in positives) / len(positives),
                false_match_rate=sum(x["false_match"] for x in negatives) / len(negatives),
                false_no_match_rate=sum(x["false_no_match"] for x in positives) / len(positives),
                verified_completion_rate=sum(x["verified"] for x in positives) / len(positives),
            )
        )
    return dict(
        schema_version="pals.typed-catalog-evaluation.v1",
        layout_sha256=corpus["layout_sha256"],
        corpus_sha256=hashlib.sha256(rfc8785.dumps(cast(Any, corpus))).hexdigest(),
        evaluator_id=evaluator_id,
        families=families,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--evaluator-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    try:
        corpus = _decode_json(args.corpus.read_bytes())
        if not isinstance(corpus, dict):
            raise ValueError("Corpus invalid")
        key = os.environ.get("OPENAI_API_KEY") or os.environ["PALS_OPENAI_API_KEY"]
        url = os.environ["PALS_API_BASE_URL"]
        runtime = TypedProofFlowRuntime(
            OpenAIResponsesClient(api_key=key),
            OpenAIEmbeddingModel(
                api_key=key, revision="openai-release-2024-01-25", timeout_seconds=15
            ),
            PrivateTypedCandidateClient(
                url,
                os.environ["PALS_TYPED_CATALOG_RELEASE_SECRET"],
                evaluation_generation_id=args.generation_id,
            ),
            OpenAIDraftReranker(api_key=key),
        )
        proof = PalsApiClient(url, os.environ["PALS_WORKER_SHARED_SECRET"])
        result = evaluate(corpus, runtime, proof, args.evaluator_id)
        args.output.write_bytes(rfc8785.dumps(result) + b"\n")
        print("Recorded actual runtime metrics; signature and activation remain separate.")
        return 0
    except Exception:
        print("Typed runtime evaluation failed; no activation performed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
