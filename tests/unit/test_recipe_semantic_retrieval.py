"""Trust-boundary and prompt parity tests; synthetic HTTP never proves model accuracy."""

import copy
import hashlib
import json
import time
from uuid import uuid4

import pytest

from pals_agent import recipe_semantic_contract as contract
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_retrieval import BINDING_SHA256, query_embedding, retrieval_text
from pals_agent.recipe_semantic import SemanticReuseError, attempt
from pals_agent.token_meter import TokenMeter, token_meter_scope
from pals_agent.usage import usage_scope
from tests.unit.test_recipe_semantic import Provider, inputs
from tests.unit.test_token_meter import OP, Ledger

PROFILE = "pals.recipe-retrieval.embedding-cosine.v1"


def window_inputs(shown=5, catalog=1045):
    request, batch, verdict = inputs()
    template = batch["recipes"][0]
    batch["recipes"] = []
    for i in range(shown):
        row = copy.deepcopy(template)
        row["recipe_id"] = f"unit.catalog.{i:02}"
        row["entry_sha256"] = hashlib.sha256(f"unit.catalog.{i:02}".encode()).hexdigest()
        batch["recipes"].append(row)
    batch["catalog_count"] = catalog
    if catalog == 0:
        batch["retrieval_profile"] = None
    reseal(batch)
    return request, batch, verdict


def reseal(batch):
    batch["batch_sha256"] = contract.digest(
        {
            "schema_version": contract.CONTENT_SCHEMA,
            **{k: batch[k] for k in contract.CONTENT_FIELDS},
        }
    )


def prompt_pair(request, batch):
    return contract.prompts(
        request,
        batch,
        {"natural_zero": "include", "zero_pow_zero": "include"},
        assessment_session="00000000-0000-4000-8000-000000000001",
        review_session="00000000-0000-4000-8000-000000000002",
    )


def run(request, batch, provider):
    return attempt(
        OpenAIResponsesClient(api_key="unit-only", transport=provider),
        request,
        batch["claim_id"],
        lambda _vector: batch,
        deadline=time.monotonic() + 30,
    )


def model_catalog(prompt):
    return json.loads(prompt.split("CATALOG_DATA:\n", 1)[1].split("\nROLE: ", 1)[0])


def test_only_model_projection_omits_five_hashes_and_keeps_rank_order_and_exact_sources():
    request, batch, _ = window_inputs()
    before = copy.deepcopy(batch)
    pair = prompt_pair(request, batch)
    catalogs = [model_catalog(p) for p in pair.values()]
    assert catalogs[0] == catalogs[1] and batch == before
    data = catalogs[0]
    assert data["catalog_batch_sha256"] == batch["batch_sha256"]
    assert data["catalog_candidate_count"] == 1045 and data["shown_candidate_count"] == 5
    assert data["candidate_scope"] == "retrieved_subset_not_complete_catalog"
    assert "unseen entries" in pair["assessment"] and request["statement"] in pair["assessment"]
    assert "COMPLETE bounded catalog" not in pair["assessment"]
    for model, source in zip(data["candidates"], batch["recipes"], strict=True):
        assert model["recipe_id"] == source["recipe_id"]
        assert set(model) == contract.MODEL_CANDIDATE_FIELDS
        assert not set(model) & contract.OMITTED_MODEL_FIELDS
        assert model["lean_code"] == source["lean_code"] and model["answer"] == source["answer"]
        assert model["target_source"] == source["target_source"]
        assert (
            model["target_sha256"] == hashlib.sha256(source["target_source"].encode()).hexdigest()
        )
        for key in contract.OMITTED_MODEL_FIELDS:
            assert key in source
    assert "\nSession: 00000000-0000-4000-8000-000000000001" in pair["assessment"]
    assert "\nSession: 00000000-0000-4000-8000-000000000002" in pair["review"]


@pytest.mark.parametrize("count", [1, 2, 5])
def test_full_shown_small_catalog_scope_is_truthful(count):
    request, batch, _ = window_inputs(count, count)
    pair = prompt_pair(request, batch)
    assert model_catalog(pair["assessment"])["candidate_scope"] == "full_catalog_shown"
    assert "contains ALL catalog entries" in pair["assessment"]
    assert "not every catalog entry" not in pair["assessment"]


@pytest.mark.parametrize(
    "change", ["duplicate", "too_many", "over_catalog", "digest", "profile", "count", "catalog"]
)
def test_malformed_window_is_not_model_input(change):
    request, batch, _ = window_inputs(5, 6 if change == "over_catalog" else 1045)
    if change == "duplicate":
        batch["recipes"][1] = copy.deepcopy(batch["recipes"][0])
    elif change == "too_many":
        batch["recipes"].append(copy.deepcopy(batch["recipes"][0]))
        batch["recipes"][-1].update(recipe_id="unit.catalog.99", entry_sha256="e" * 64)
    elif change == "over_catalog":
        batch["catalog_count"] = 4
    elif change == "profile":
        batch["retrieval_profile"] = "unknown.profile"
    elif change == "count":
        batch["catalog_count"] = 4097
    elif change == "catalog":
        batch["catalog_sha256"] = "not-a-digest"
    if change == "digest":
        batch["batch_sha256"] = "0" * 64
    else:
        reseal(batch)
    with pytest.raises(ValueError):
        prompt_pair(request, batch)


def test_valid_catalog_source_outside_window_is_rejected_after_both_spent_calls():
    request, batch, verdict = window_inputs()
    verdict.update(recipe_id="unit.catalog.other", recipe_revision=1)
    provider = Provider(verdict)
    usage = []
    with (
        usage_scope(usage.append),
        pytest.raises(SemanticReuseError, match="proof_reuse_invalid_response"),
    ):
        run(request, batch, provider)
    judged = [item for item in usage if item["model"] == "gpt-6-luna"]
    assert len(provider.calls) == len(judged) == 2


def test_shown_source_tampering_fails_before_any_judge_call():
    request, batch, verdict = window_inputs()
    batch["recipes"][3]["lean_code"] += "\n-- modified source"
    reseal(batch)
    provider = Provider(verdict)
    with pytest.raises(SemanticReuseError, match="proof_reuse_recipe_invalid"):
        run(request, batch, provider)
    assert provider.calls == []


@pytest.mark.parametrize(
    "refusal",
    [
        {"reason": "catalog_limit", "catalog_count": 4097, "retrieval_profile": None},
        {"reason": "byte_limit", "catalog_count": 1045, "retrieval_profile": PROFILE},
    ],
)
def test_empty_and_explicit_refusal_preserve_ordinary_fallback_without_judges(refusal):
    request, batch, verdict = window_inputs(0, 0)
    provider = Provider(verdict)
    assert run(request, batch, provider) is None
    batch.update(complete=False, recipes=[], batch_sha256=None, **refusal)
    assert run(request, batch, provider) is None
    assert provider.calls == []


@pytest.mark.parametrize(
    "refusal",
    [
        {"reason": "count_limit"},
        {"reason": "catalog_limit", "catalog_count": 1045, "retrieval_profile": None},
        {"reason": "byte_limit", "catalog_count": 4097, "retrieval_profile": PROFILE},
    ],
)
def test_inconsistent_refusal_is_integrity_failure(refusal):
    request, batch, verdict = window_inputs()
    batch.update(complete=False, recipes=[], batch_sha256=None, **refusal)
    provider = Provider(verdict)
    with pytest.raises(SemanticReuseError, match="proof_reuse_recipe_invalid"):
        run(request, batch, provider)
    assert provider.calls == []


def test_nonempty_catalog_with_empty_window_is_integrity_failure():
    request, batch, verdict = window_inputs(0, 1045)
    provider = Provider(verdict)
    with pytest.raises(SemanticReuseError, match="proof_reuse_recipe_invalid"):
        run(request, batch, provider)
    assert provider.calls == []


def test_provider_failure_sends_no_vector_and_leaves_both_judges_unchanged():
    request, batch, verdict = window_inputs()
    verdict.update(recipe_id="unit.catalog.00", recipe_revision=1)
    provider = Provider(verdict, embedding_fails=True)
    received = []

    def loader(vector):
        received.append(vector)
        return batch

    result = attempt(
        OpenAIResponsesClient(api_key="unit-only", transport=provider),
        request,
        batch["claim_id"],
        loader,
        deadline=time.monotonic() + 30,
    )
    assert received == [None] and len(provider.embeddings) == 1
    assert result.answer is not None and len(provider.calls) == 2


def test_query_vector_uses_exact_binding_and_is_passed_to_the_window_loader():
    request, batch, verdict = window_inputs()
    verdict.update(recipe_id="unit.catalog.00", recipe_revision=1)
    provider = Provider(verdict)
    received = []
    usage = []

    def loader(vector):
        received.append(vector)
        return batch

    with usage_scope(usage.append):
        attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            loader,
            deadline=time.monotonic() + 30,
        )
    assert provider.embeddings == [
        {"model": "text-embedding-3-large", "input": request["statement"], "dimensions": 1024}
    ]
    assert len(received[0]) == 1024
    embedding = next(item for item in usage if item["model"] == "text-embedding-3-large")
    assert embedding["output_tokens"] == 0


def test_paid_query_vector_is_permitted_received_and_priced_like_other_provider_calls():
    request, batch, verdict = window_inputs()
    verdict.update(recipe_id="unit.catalog.00", recipe_revision=1)
    provider = Provider(verdict)
    ledger = Ledger([])
    meter = TokenMeter(ledger, OP, request["id"], batch["claim_id"], time.monotonic() + 30)
    with usage_scope(lambda _record: None), token_meter_scope(meter):
        result = run(request, batch, provider)
    assert result.answer is not None and len(provider.embeddings) == 1
    assert len(ledger.permits) == len(ledger.receipts) == 3
    assert "recipe_retrieval_embedding" in json.dumps(ledger.permits)


@pytest.mark.parametrize(
    ("base_url", "seconds"),
    [("https://proxy.invalid/v1", 30), ("https://api.openai.com/v1", 0.1)],
)
def test_other_endpoint_or_exhausted_deadline_skips_the_vector(base_url, seconds):
    provider = Provider({})
    client = OpenAIResponsesClient(api_key="unit-only", base_url=base_url, transport=provider)
    assert query_embedding(client, "問", deadline=time.monotonic() + seconds) is None
    assert provider.embeddings == []


def test_binding_digest_and_retrieval_text_match_the_api_contract():
    # The same literals are asserted by pals-api tests/unit/test_recipe_retrieval.py.
    assert BINDING_SHA256 == "9b08a21ee20751b2c5e7540fc6b965f6ce4549d074e228ff3822b04f5da8c31a"
    assert (
        retrieval_text(
            {
                "statement": "命題",
                "domain": "実解析",
                "conclusion": "結論",
                "assumptions": ["a", "b"],
            }
        )
        == "命題\n実解析\n結論\na\nb"
    )


def test_no_prompt_result_survives_between_claims():
    request, batch, verdict = window_inputs()
    verdict.update(recipe_id="unit.catalog.00", recipe_revision=1)
    for _ in range(2):
        provider = Provider(verdict)
        result = run(request, batch, provider)
        assert result.answer is not None and len(provider.calls) == 2
        request["id"] = str(uuid4())
        batch["request_id"] = request["id"]
        batch["claim_id"] = str(uuid4())


def test_twenty_entry_compound_task_prompt_bytes_have_explicit_golden():
    """Golden hashes identify the window wording; they measure no provider or latency."""
    request, batch, _ = window_inputs(5, 20)
    pair = prompt_pair(request, batch)
    assert {role: hashlib.sha256(value.encode()).hexdigest() for role, value in pair.items()} == {
        "assessment": "637868f42abe82339c4f48bfe09031bc4a3fe5605ef6f3cae59c407c911b69ac",
        "review": "b1ebf99657832812f20591789c36fdd65840c295d10312c570b87c1c287e1607",
    }
