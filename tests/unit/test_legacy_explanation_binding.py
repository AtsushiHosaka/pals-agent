import json
from dataclasses import replace
from pathlib import Path

import pytest

from pals_agent.explanations import LeanGroundedOutputReviewer, ProofOutputReviewError


class FakeClient:
    def __init__(self):
        self.prompts = []

    def generate(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        raise AssertionError("provider must not run for an invalid reference")


def _saved_coprime_excerpt(separator: str, *, legacy: bool):
    corpus = Path(__file__).resolve().parents[2] / "testdata/explanation-grounding-v1"
    case = json.loads((corpus / "corpus.json").read_text())["cases"][1]
    lines = (corpus / case["source"]).read_text().splitlines()
    source = separator.join(lines)
    excerpt = ("\n" if legacy else separator).join(lines[7:19])
    payload = {
        "overview": "Fix coprime natural numbers, including zero.",
        "sections": [
            {
                "id": "divisibility",
                "title": "Both implications",
                "summary": "Euclid's lemma gives the quotient divisibility in the forward "
                "direction. Each factor divides the product in the converse.",
                "references": [{"start_line": 8, "end_line": 19, "excerpt": excerpt}],
            }
        ],
        "conclusion": "Both divisibilities hold if and only if $ab\\mid n$.",
        "model": "saved-output",
        "provider": "synthetic",
        "elapsed_ms": 1,
    }
    return case, source, payload, separator.join(lines[7:19])


@pytest.mark.parametrize(
    "separator", ["\r\n", "\r", "\x85", "\u2028", "\u2029"], ids=["CRLF", "CR", "NEL", "LS", "PS"]
)
@pytest.mark.parametrize("legacy", [False, True], ids=["original", "old-LF"])
def test_saved_excerpt_reader_builds_clarification_with_canonical_source(separator, legacy) -> None:
    from pals_agent.explanations import _clarification_prompt, proof_explanation_from_api

    case, source, payload, original_excerpt = _saved_coprime_excerpt(separator, legacy=legacy)
    before = json.dumps(payload, ensure_ascii=False)
    explanation = proof_explanation_from_api(payload, lean_code=source)
    assert explanation.sections[0].references[0].excerpt == original_excerpt
    assert json.dumps(payload, ensure_ascii=False) == before
    prompt = _clarification_prompt(
        theorem_statement=case["question"],
        lean_code=source,
        explanation=explanation,
        selected=explanation.sections[0],
        question="Why does the quotient remain natural?",
        language="en",
    )
    context = json.loads(
        prompt.split("Existing explanation:\n", 1)[1].split(
            "\n\nReturn exactly one JSON object",
            1,
        )[0]
    )
    assert context["sections"][0]["references"][0]["excerpt"] == original_excerpt
    assert context["sections"][0]["summary"] == payload["sections"][0]["summary"]


@pytest.mark.parametrize(
    "separator", ["\r\n", "\r", "\x85", "\u2028", "\u2029"], ids=["CRLF", "CR", "NEL", "LS", "PS"]
)
def test_legacy_reader_does_not_relax_new_generation_or_qa_excerpts(separator) -> None:
    from pals_agent.explanations import _parse_explanation, proof_explanation_from_api

    case, source, payload, original_excerpt = _saved_coprime_excerpt(separator, legacy=True)
    with pytest.raises(ValueError, match="excerpt does not exactly match"):
        _parse_explanation(payload, source, language="en", require_claim_headers=True)
    loaded = proof_explanation_from_api(payload, lean_code=source)
    assert loaded.sections[0].references[0].excerpt == original_excerpt
    bad_reference = replace(
        loaded.sections[0].references[0], excerpt=payload["sections"][0]["references"][0]["excerpt"]
    )
    bad_section = replace(loaded.sections[0], references=(bad_reference,))
    client = FakeClient()
    reviewer = LeanGroundedOutputReviewer(client=client, model="explain-model", provider="unit")
    with pytest.raises(ProofOutputReviewError, match="source correspondence") as error:
        reviewer.review_explanation(
            theorem_statement=case["question"],
            lean_code=source,
            explanation=replace(loaded, sections=(bad_section,)),
            language="en",
        )
    assert error.value.category == "rejected"
    assert client.prompts == []
    # Historical compatibility accepts only the old normalization, not altered text.
    payload["sections"][0]["references"][0]["excerpt"] += "\nnot in the source"
    with pytest.raises(ValueError, match="excerpt does not exactly match"):
        proof_explanation_from_api(payload, lean_code=source)


@pytest.mark.parametrize(
    "separator",
    ["\n", "\r\n", "\r", "\x85", "\u2028", "\u2029"],
    ids=["LF", "CRLF", "CR", "NEL", "LS", "PS"],
)
def test_parent_identity_uses_saved_content_not_canonical_model_context(separator) -> None:
    from pals_agent.explanations import proof_explanation_from_api
    from pals_agent.worker import (
        _canonical_json_sha256,
        _public_explanation_content,
        _stored_parent_explanation_content,
    )

    _, source, payload, original = _saved_coprime_excerpt(separator, legacy=True)
    before = json.dumps(payload, ensure_ascii=False)
    context = proof_explanation_from_api(payload, lean_code=source)
    canonical = _public_explanation_content(context)
    stored = _stored_parent_explanation_content(payload, context)
    assert stored == payload
    assert json.dumps(payload, ensure_ascii=False) == before
    assert context.sections[0].references[0].excerpt == original
    assert canonical["sections"][0]["references"][0]["excerpt"] == original
    assert _canonical_json_sha256(stored) == _canonical_json_sha256(payload)
    if separator != "\n":
        assert _canonical_json_sha256(stored) != _canonical_json_sha256(canonical)


def _claim_resource():
    return {
        "id": "clarification",
        "proof_job_id": "proof",
        "section_id": "selected",
        "selected_text": "selected text",
        "after_clarification_id": None,
        "question": "Why?",
        "state": "generating",
        "content": None,
        "diagnostics": [],
        "created_at": "2026-11-05T00:00:00Z",
        "updated_at": "2026-11-05T00:00:00Z",
    }


@pytest.mark.parametrize("language", [None, "en", "ja", "zh-Hans", "zh-Hant"])
def test_current_nullable_language_member_is_validated_in_claim(language):
    from pals_agent.worker import _validate_claim_resource

    resource = _claim_resource()
    resource["output_language"] = language
    _validate_claim_resource(
        resource, resource_kind="clarification", resource_id="clarification", status="acquired"
    )
    resource.pop("output_language")
    _validate_claim_resource(
        resource, resource_kind="clarification", resource_id="clarification", status="acquired"
    )


@pytest.mark.parametrize("language", ["fr", "zh", "", False, 0, [], {}])
def test_claim_language_does_not_accept_unknown_values_or_types(language):
    from pals_agent.worker import _validate_claim_resource

    resource = _claim_resource()
    resource["output_language"] = language
    with pytest.raises(ValueError):
        _validate_claim_resource(
            resource, resource_kind="clarification", resource_id="clarification", status="acquired"
        )


def test_claim_language_does_not_allow_other_unknown_members():
    from pals_agent.worker import _validate_claim_resource

    resource = _claim_resource()
    resource["output_language"] = "en"
    resource["unknown"] = True
    with pytest.raises(ValueError, match="identity/fields"):
        _validate_claim_resource(
            resource, resource_kind="clarification", resource_id="clarification", status="acquired"
        )
