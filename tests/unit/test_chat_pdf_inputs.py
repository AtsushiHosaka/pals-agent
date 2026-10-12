"""Document/page binding checks; isolated provider fixtures do not prove live interpretation."""

import base64
import copy
import hashlib
import json

import pytest

from pals_agent.chat_images import (
    chat_attachment_ids,
    chat_image_urls,
    chat_input_sha256,
    current_chat_images,
    parse_chat_images,
)
from pals_agent.linked_chat import linked_chat_scope
from tests.unit.test_chat_runtime import IMAGE, REQUEST, engine, route


def pdf_input():
    # The API is responsible for rendering valid documents. These distinctive byte
    # fixtures isolate immutable transport/hash behavior, not JPEG decoding.
    pages = [b"\xff\xd8\xffpage-one", b"\xff\xd8\xffpage-two"]
    encoded = [base64.b64encode(page).decode() for page in pages]
    urls = ["data:image/jpeg;base64," + page for page in encoded]
    hashes = [hashlib.sha256(page).hexdigest() for page in pages]
    return {
        **IMAGE,
        "filename": "diagram.pdf",
        "media_type": "application/pdf",
        "page_count": 2,
        "image_data_url": urls[0],
        "image_sha256": hashes[0],
        "image_data_urls": urls,
        "image_sha256s": hashes,
        "pages_sha256": hashlib.sha256(
            json.dumps(encoded, separators=(",", ":")).encode()
        ).hexdigest(),
        "ocr_text": "Page 1: a mapping. Page 2: the kernel.",
    }


def test_all_pdf_pages_reach_classifier_generator_and_independent_review():
    document = pdf_input()
    parsed = parse_chat_images({"attachments": [document]}, [document["id"]])
    runtime, provider = engine([
        route(), {"text": "The diagram represents a linear map and its kernel."},
        {"approved": True, "rationale": "Both pages were considered."},
    ])
    request = {**REQUEST, "chat_images": parsed}
    result = runtime.answer(request)
    assert result.outcome == "answered"
    for call in provider.calls:
        assert [part["image_url"] for part in call["input"][0]["content"][1:]] == (
            document["image_data_urls"]
        )
    assert result.private_evidence["chat_route"]["input_sha256"] == (
        result.private_evidence["chat_explanation_qa"]["input_sha256"]
    )


@pytest.mark.parametrize("mutation", ["missing_page", "page_order", "page_hash", "count"])
def test_incomplete_or_mutated_pdf_is_rejected(mutation):
    document = pdf_input()
    if mutation == "missing_page":
        document["image_data_urls"].pop()
        document["image_sha256s"].pop()
    elif mutation == "page_order":
        document["image_data_urls"].reverse()
    elif mutation == "page_hash":
        document["image_sha256s"][1] = "a" * 64
    else:
        document["page_count"] = 21
    with pytest.raises(ValueError):
        parse_chat_images({"attachments": [document]}, [document["id"]])


def test_pdf_hash_binds_second_page_and_linked_review_restores_all_pages():
    from tests.unit.test_linked_chat import binding

    context, payload = copy.deepcopy(binding())
    document = pdf_input()
    payload["attachments"] = [document]
    request = {**payload["request"], "chat_images": [document]}
    context["chat_route"]["input_sha256"] = chat_input_sha256(request)
    payload["chat_route"] = context["chat_route"]
    with linked_chat_scope(context, payload):
        assert current_chat_images() == chat_image_urls([document])
    assert current_chat_images() == ()
    changed = copy.deepcopy(request)
    changed["chat_images"][0]["pages_sha256"] = "a" * 64
    assert chat_input_sha256(changed) != chat_input_sha256(request)


def test_aggregate_attachment_manifest_retains_its_context_bound():
    ids = [f"44444444-4444-4444-8444-{number:012d}" for number in range(331)]
    assert chat_attachment_ids({"attachment_ids": ids[:330]}) == ids[:330]
    with pytest.raises(ValueError):
        chat_attachment_ids({"attachment_ids": ids})


@pytest.mark.parametrize("source", ["clarification", "history"])
def test_expanded_worker_snapshot_preserves_all_images_and_linked_review(source):
    from tests.unit.test_linked_chat import binding

    count = 5 if source == "clarification" else 8
    documents = [dict(IMAGE, id=f"44444444-4444-4444-8444-{number:012d}")
                 for number in range(count)]
    identifiers = [document["id"] for document in documents]
    metadata = {key: value for key, value in documents[4].items()
                if key not in {"image_data_url", "ocr_text"}}
    context, payload = binding()
    payload["attachments"] = documents
    payload["request"]["attachment_ids"] = identifiers
    payload["request"]["context_turns"] = ([{
        "question_id": "focus", "question": "Which part should I explain?",
        "answer": "This part", "attachments": [metadata],
    }] if source == "clarification" else [])
    payload["request"]["chat_history"] = ([{
        "role": "user", "text": "Explain the prior diagrams.",
        "attachment_ids": identifiers[4:], "context_turns": [],
    }] if source == "history" else [])
    assert chat_attachment_ids(payload["request"]) == identifiers
    parsed = parse_chat_images({"attachments": documents}, identifiers)
    request = {**payload["request"], "output_language": "en", "chat_images": parsed}
    runtime, provider = engine([
        route(), {"text": "The diagrams describe mappings."},
        {"approved": True, "rationale": "All requested diagrams were considered."},
    ])
    assert runtime.answer(request).outcome == "answered"
    assert all(len(call["input"][0]["content"]) == count + 1 for call in provider.calls)
    context["chat_route"]["input_sha256"] = chat_input_sha256(request)
    payload["chat_route"] = context["chat_route"]
    with linked_chat_scope(context, payload):
        assert len(current_chat_images()) == count
    assert current_chat_images() == ()


def test_document_context_adapters_accept_large_bounded_payloads_only_on_context_routes():
    from pals_agent.api_client import PalsApiClient, PalsApiError
    from pals_agent.http_transport import HttpResponse
    from pals_agent.recipe_semantic_reviewer import RecipeSemanticReviewApiClient

    class LargeDocumentResponse:
        def request(self, **kwargs):
            assert kwargs["headers"].get("X-PALS-Worker-Secret") or (
                kwargs["headers"].get("X-PALS-Recipe-Semantic-Reviewer-Secret")
            )
            return HttpResponse(200, json.dumps({"attachments": "x" * 1_200_000}).encode())

    transport = LargeDocumentResponse()
    client = PalsApiClient("https://api.example.test", "fixture", attachment_transport=transport)
    identifier = IMAGE["id"]
    assert client.get_proof_request_attachments(request_id=identifier, claim_id=identifier)
    assert client.get_proof_job_chat_input(identifier)
    reviewer = RecipeSemanticReviewApiClient(
        "https://api.example.test", "reviewer-fixture", attachment_transport=transport
    )
    assert reviewer.get_chat_input(identifier, identifier)
    control = PalsApiClient("https://api.example.test", "fixture", transport=transport)
    with pytest.raises(PalsApiError, match="byte limit"):
        control.get_proof_job(identifier)


def test_visual_lean_route_retains_recipe_first_search_and_shared_pdf_context():
    from dataclasses import replace

    from tests.unit.test_proof_reuse import READY, CatalogBoundary
    from tests.unit.test_proof_reuse_lean_flow import CLAIM_ID, INTENT, REQUEST_ID

    document = pdf_input()
    statement = "Prove continuity of the real function f(x)=x^2 at every real point."
    runtime, provider = engine([
        route("lean", extracted_statement=statement),
        {**READY, "statement": statement},
        INTENT,
    ])
    runtime = replace(
        runtime, proof_runtime=replace(runtime.proof_runtime, catalog=CatalogBoundary())
    )
    searches = []

    def search(query, language):
        searches.append((query, language))
        return []

    request = {
        **REQUEST, "id": REQUEST_ID, "revision": 3,
        "statement": statement, "chat_images": [document],
    }
    result = runtime.answer(request, recipe_search=search, claim_id=CLAIM_ID)
    assert result.outcome == "formal" and result.answer is None
    assert result.formal_plan == {"kind": "dsp", "statement": statement}
    assert searches == [(INTENT["query"], "en")]
    assert len(provider.calls) == 3
    for call in provider.calls:
        assert [part["image_url"] for part in call["input"][0]["content"][1:]] == (
            document["image_data_urls"]
        )
    assert current_chat_images() == ()
