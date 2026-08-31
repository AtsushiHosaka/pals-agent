from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from importlib import resources
from typing import Any

import pytest

from pals_agent.draft_catalog import (
    SeedDraftCatalog,
    draft_embedding_text,
    draft_seed_manifest,
    load_seed_drafts,
    validate_draft_xml,
)
from pals_agent.draft_embeddings import (
    EmbeddingError,
    OpenAIEmbeddingModel,
    normalize_embedding_endpoint,
)
from pals_agent.openmath import (
    MathXMLValidationError,
    canonicalize_openmath_xml,
)


def test_seed_catalog_is_seed_source_not_statement_retriever() -> None:
    catalog = SeedDraftCatalog()

    draft = catalog.find_by_id("continuous_square")

    assert draft is not None
    assert catalog.find_by_statement("x^2が連続であることを示せ") is None
    assert catalog.find_by_statement("x² が連続であることを示せ") is None


def test_seed_catalog_contains_general_power_draft() -> None:
    catalog = SeedDraftCatalog()

    draft = catalog.find_by_id("continuous_power")

    assert draft is not None
    assert draft.id == "continuous_power"
    assert 'name="n"' in draft.openmath_xml
    assert "Generalize the square-function continuity draft" in draft.proof_strategy
    assert draft.sketch_steps


def test_seed_catalog_contains_distinct_epsilon_delta_proof_families() -> None:
    catalog = SeedDraftCatalog()
    draft_ids = (
        "continuous_affine",
        "continuous_absolute_value",
        "continuous_reciprocal_nonzero",
    )
    drafts = []

    for draft_id in draft_ids:
        draft = catalog.find_by_id(draft_id)
        assert draft is not None
        drafts.append(draft)
        assert "ε" in " ".join((draft.proof_strategy, *draft.sketch_steps))
        assert all(":" in step for step in draft.sketch_steps)
        assert catalog.find_by_statement(draft.matched_prompt) is None

    canonical_statements = {
        canonicalize_openmath_xml(draft.openmath_xml) for draft in drafts
    }
    assert len(canonical_statements) == len(draft_ids)


def test_continuity_seed_statements_do_not_encode_a_proof_method() -> None:
    catalog = SeedDraftCatalog()

    for draft_id in (
        "continuous_affine",
        "continuous_absolute_value",
        "continuous_reciprocal_nonzero",
    ):
        draft = catalog.find_by_id(draft_id)
        assert draft is not None
        assert "イプシロンデルタ" not in draft.matched_prompt
        assert "epsilon-delta" not in draft.matched_prompt.lower()
        assert "ε" in " ".join((draft.proof_strategy, *draft.sketch_steps))


def test_epsilon_delta_seed_openmath_preserves_real_domain_constraints() -> None:
    catalog = SeedDraftCatalog()
    expected_symbol_counts = {
        "continuous_affine": {("set1", "in"): 2},
    }

    for draft_id, expected_counts in expected_symbol_counts.items():
        draft = catalog.find_by_id(draft_id)
        assert draft is not None
        symbols = [
            (element.get("cd"), element.get("name"))
            for element in ET.fromstring(draft.openmath_xml).iter()
            if element.tag.endswith("}OMS")
        ]
        for symbol, expected_count in expected_counts.items():
            assert symbols.count(symbol) == expected_count

    for draft_id, phrase in (("continuous_affine", "a and b are real"),):
        draft = catalog.find_by_id(draft_id)
        assert draft is not None
        assert phrase in draft.matched_prompt


def test_seed_payload_uses_only_the_minimal_draft_contract() -> None:
    payload = json.loads(
        resources.files("pals_agent.seed")
        .joinpath("dsp_drafts.json")
        .read_text(encoding="utf-8")
    )

    assert len(payload) == 31
    assert all(
        set(item)
        == {"id", "matched_prompt", "openmath_xml", "proof_strategy", "sketch_steps"}
        for item in payload
    )


def test_seed_payload_has_distinct_openmath_propositions() -> None:
    drafts = load_seed_drafts()

    canonical_propositions = {
        canonicalize_openmath_xml(draft.openmath_xml) for draft in drafts
    }

    assert len(drafts) == 31
    assert len(canonical_propositions) == 31


def test_seed_manifest_covers_strategy_and_is_order_independent() -> None:
    drafts = load_seed_drafts()
    changed = (replace(drafts[0], proof_strategy="changed strategy"), *drafts[1:])

    assert draft_seed_manifest(drafts) == draft_seed_manifest(tuple(reversed(drafts)))
    assert draft_seed_manifest(drafts) != draft_seed_manifest(changed)


def test_seed_canonical_statements_do_not_encode_a_proof_method() -> None:
    for draft in load_seed_drafts():
        assert "イプシロンデルタ" not in draft.matched_prompt
        assert "epsilon-delta" not in draft.matched_prompt.lower()


def test_seed_canonical_statements_are_english() -> None:
    japanese_script = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

    for draft in load_seed_drafts():
        assert japanese_script.search(draft.matched_prompt) is None


def test_continuity_seed_statements_name_their_domain() -> None:
    for draft in load_seed_drafts():
        if draft.id.startswith("continuous_"):
            assert "continuous on" in draft.matched_prompt.lower()


def test_rank_nullity_seed_checks_assumptions_and_conclusion() -> None:
    draft = SeedDraftCatalog().find_by_id("rank_nullity")
    assert draft is not None
    root = ET.fromstring(draft.openmath_xml)
    implication = list(list(root)[0])[2]
    antecedent = list(implication)[1]
    linear_map_only = list(antecedent)[1]
    implication.remove(antecedent)
    implication.insert(1, linear_map_only)
    missing_dimension = replace(
        draft,
        openmath_xml=ET.tostring(root, encoding="unicode"),
    )

    with pytest.raises(MathXMLValidationError, match="premises do not match"):
        validate_draft_xml(missing_dimension)

    root = ET.fromstring(draft.openmath_xml)
    rank_symbol = next(
        element
        for element in root.iter()
        if element.tag.endswith("}OMS") and element.get("name") == "rank"
    )
    rank_symbol.set("name", "nullity")
    wrong_equality = replace(
        draft,
        openmath_xml=ET.tostring(root, encoding="unicode"),
    )

    with pytest.raises(MathXMLValidationError, match="rank-nullity equality"):
        validate_draft_xml(wrong_equality)


def test_seed_validation_rejects_openmath_for_a_different_natural_statement() -> None:
    drafts = {draft.id: draft for draft in load_seed_drafts()}
    square = drafts["continuous_square"]
    absolute_value = drafts["continuous_absolute_value"]
    mismatched = replace(
        square,
        openmath_xml=absolute_value.openmath_xml,
    )

    with pytest.raises(MathXMLValidationError, match="arithmetic structure|arith1:power"):
        validate_draft_xml(mismatched)

def test_seed_draft_embedding_text_is_only_alpha_canonical_openmath() -> None:
    draft = SeedDraftCatalog().find_by_id("continuous_square")
    assert draft is not None

    embedding_text = draft_embedding_text(draft)

    assert "http://www.openmath.org/OpenMath" in embedding_text
    assert 'name="v1"' in embedding_text
    assert 'name="x"' not in embedding_text
    assert draft.matched_prompt not in embedding_text
    assert "epsilon-delta" not in embedding_text
    assert draft.proof_strategy not in embedding_text


def test_openai_embedding_requests_semantic_vector_with_configured_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Any] = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode()

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        requests.append(request)
        assert timeout == 12.0
        return FakeResponse()

    monkeypatch.setattr("pals_agent.draft_embeddings.urlopen", fake_urlopen)

    model = OpenAIEmbeddingModel(
        api_key="sk-test",
        revision="sha256:test-revision",
        model="text-embedding-3-small",
        dimension=3,
        base_url="https://api.openai.test/v1",
        timeout_seconds=12.0,
    )

    embedding = model.embed("rank-nullityを示せ")

    request = requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.openai.test/v1/embeddings"
    assert request.headers["Authorization"] == "Bearer sk-test"
    assert payload == {
        "model": "text-embedding-3-small",
        "input": "rank-nullityを示せ",
        "dimensions": 3,
    }
    assert embedding == [0.1, 0.2, 0.3]


def test_openai_embedding_rejects_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"data": [{"embedding": [0.1, 0.2]}]}).encode()

    monkeypatch.setattr(
        "pals_agent.draft_embeddings.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    model = OpenAIEmbeddingModel(
        api_key="sk-test",
        revision="sha256:test-revision",
        dimension=3,
    )

    with pytest.raises(EmbeddingError, match="dimension mismatch"):
        model.embed("x^2が連続であることを示せ")


def test_embedding_model_rejects_missing_immutable_revision() -> None:
    with pytest.raises(ValueError, match="embedding revision"):
        OpenAIEmbeddingModel(api_key="sk-test", revision="")


def test_embedding_endpoint_identity_excludes_credentials_and_query() -> None:
    assert normalize_embedding_endpoint(
        "HTTPS://user:secret@Embeddings.Example:8443/v1/?api-version=2026-01"
    ) == "https://embeddings.example:8443/v1"

