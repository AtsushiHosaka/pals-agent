"""Trust-boundary and prompt parity tests; synthetic HTTP never proves model accuracy."""

import copy
import hashlib
import json
import time
from uuid import uuid4

import pytest

from pals_agent import recipe_semantic_contract as contract
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_local_retrieval import rank
from pals_agent.recipe_semantic import SemanticReuseError, attempt
from pals_agent.usage import usage_scope
from tests.unit.test_recipe_semantic import Provider, inputs


def batch_inputs(count=20):
    request, batch, verdict = inputs()
    template = batch["recipes"][0]
    batch["recipes"] = []
    for i in range(count):
        row = copy.deepcopy(template)
        row["recipe_id"] = f"unit.catalog.{i:02}"
        row["entry_sha256"] = hashlib.sha256(f"unit.catalog.{i:02}".encode()).hexdigest()
        batch["recipes"].append(row)
    batch["total_count"] = count
    batch["batch_sha256"] = contract.digest(
        {
            "schema_version": contract.CONTENT_SCHEMA,
            **{k: batch[k] for k in ("output_language", "toolchain_sha256", "recipes")},
        }
    )
    return request, batch, verdict


def prompt_pair(request, batch, pins):
    return contract.prompts(
        request,
        batch,
        {"natural_zero": "include", "zero_pow_zero": "include"},
        assessment_session="00000000-0000-4000-8000-000000000001",
        review_session="00000000-0000-4000-8000-000000000002",
        retrieved_entry_sha256s=pins,
    )


def model_catalog(prompt):
    return json.loads(prompt.split("CATALOG_DATA:\n", 1)[1].split("\nROLE: ", 1)[0])


def test_only_model_projection_omits_five_hashes_full_authority_and_exact_sources_retained():
    request, batch, _ = batch_inputs()
    before = copy.deepcopy(batch)
    pins = rank(batch["recipes"], request["statement"])
    pair = prompt_pair(request, batch, pins)
    catalogs = [model_catalog(p) for p in pair.values()]
    assert catalogs[0] == catalogs[1] and batch == before
    data = catalogs[0]
    assert data["catalog_batch_sha256"] == batch["batch_sha256"]
    assert data["catalog_candidate_count"] == 20 and data["shown_candidate_count"] == 5
    assert data["candidate_scope"] == "retrieved_subset_not_complete_catalog"
    assert "unseen entries" in pair["assessment"] and request["statement"] in pair["assessment"]
    selected = contract.subset_rows(batch, pins)
    for model, source in zip(data["candidates"], selected, strict=True):
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
    request, batch, _ = batch_inputs(count)
    pair = prompt_pair(request, batch, rank(batch["recipes"], request["statement"]))
    assert model_catalog(pair["assessment"])["candidate_scope"] == "full_catalog_shown"
    assert "contains ALL catalog entries" in pair["assessment"]
    assert "not every catalog entry" not in pair["assessment"]


@pytest.mark.parametrize("change", ["unknown", "duplicate", "empty", "too_many", "digest"])
def test_malformed_subset_or_changed_full_digest_is_not_model_input(change):
    request, batch, _ = batch_inputs()
    pins = list(rank(batch["recipes"], request["statement"]))
    if change == "unknown":
        pins[0] = "f" * 64
    elif change == "duplicate":
        pins[0] = pins[1]
    elif change == "empty":
        pins = []
    elif change == "too_many":
        pins = [r["entry_sha256"] for r in batch["recipes"][:6]]
    elif change == "digest":
        batch["batch_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prompt_pair(request, batch, pins)


def test_real_valid_source_outside_window_is_rejected_after_both_spent_calls():
    request, batch, verdict = batch_inputs(6)
    pins = rank(batch["recipes"], request["statement"])
    outside = next(r for r in batch["recipes"] if r["entry_sha256"] not in pins)
    verdict.update(
        recipe_id=outside["recipe_id"],
        recipe_revision=outside["recipe_revision"],
        source_target_sha256=hashlib.sha256(outside["target_source"].encode()).hexdigest(),
    )
    provider = Provider(verdict)
    usage = []
    with (
        usage_scope(usage.append),
        pytest.raises(SemanticReuseError, match="proof_reuse_invalid_response"),
    ):
        attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert len(provider.calls) == len(usage) == 2


def test_unshown_source_tampering_still_fails_before_any_provider_call():
    request, batch, verdict = batch_inputs(6)
    pins = rank(batch["recipes"], request["statement"])
    outside = next(r for r in batch["recipes"] if r["entry_sha256"] not in pins)
    outside["lean_code"] += "\n-- modified source"
    provider = Provider(verdict)
    with pytest.raises(SemanticReuseError, match="proof_reuse_recipe_invalid"):
        attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert provider.calls == []


def test_empty_and_explicit_overflow_preserve_ordinary_fallback_no_providers():
    request, batch, verdict = batch_inputs(0)
    provider = Provider(verdict)
    assert (
        attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
        is None
    )
    batch.update(
        complete=False,
        truncated=True,
        reason="count_limit",
        total_count=None,
        recipes=[],
        batch_sha256=None,
    )
    assert (
        attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
        is None
    )
    assert provider.calls == []


def test_oversized_complete_batch_is_integrity_failure_not_silent_truncation():
    request, batch, verdict = batch_inputs(33)
    provider = Provider(verdict)
    with pytest.raises(SemanticReuseError, match="proof_reuse_recipe_invalid"):
        attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
    assert provider.calls == []


def test_no_rank_or_prompt_result_survives_between_claims(monkeypatch):
    request, batch, verdict = batch_inputs(6)
    events = []
    original = rank

    def counted(rows, question):
        events.append((question, tuple(r["entry_sha256"] for r in rows)))
        return original(rows, question)

    monkeypatch.setattr("pals_agent.recipe_semantic.rank", counted)
    for _ in range(2):
        pins = rank(batch["recipes"], request["statement"])
        selected = next(r for r in batch["recipes"] if r["entry_sha256"] == pins[0])
        verdict.update(recipe_id=selected["recipe_id"], recipe_revision=selected["recipe_revision"])
        provider = Provider(verdict)
        result = attempt(
            OpenAIResponsesClient(api_key="unit-only", transport=provider),
            request,
            batch["claim_id"],
            lambda: batch,
            deadline=time.monotonic() + 30,
        )
        assert result.answer is not None and len(provider.calls) == 2
        request["id"] = str(uuid4())
        batch["request_id"] = request["id"]
        batch["claim_id"] = str(uuid4())
    assert len(events) == 2


def test_twenty_entry_prompt_bytes_match_measured_private_v12_and_v15_golden():
    """Golden hashes came from frozen private7f678 v12 policy at V15's exact window.

    The fixture is portable, content-free synthetic catalog metadata. This binds
    production prompt assembly to the measured implementation, not model accuracy.
    """
    request, batch, _ = batch_inputs(20)
    pair = prompt_pair(request, batch, rank(batch["recipes"], request["statement"]))
    assert {role: hashlib.sha256(value.encode()).hexdigest() for role, value in pair.items()} == {
        "assessment": "860a34c38f4b91f7bdbb35f0c8505659c370cc88cf1fbfbc65082ee937f25850",
        "review": "0e5c4502522f301017f990cf5a1238e2870fde5ada5282dbd2dab5a69307d7be",
    }
