"""Draft protocol/signing tests with isolated provider responses, not live review evidence."""

import hashlib
import json
from copy import deepcopy

import pytest
import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from pals_agent.draft_entry_review import NATURAL_BINDING, main, review_and_seal
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.openmath import canonicalize_openmath_xml_v4
from tests.unit.test_recipe_entry_review import ReceiptProvider

SOURCE = "import Mathlib\n\ntheorem proved_truth : True := by trivial\n"
ANSWER = "The proposition $\\mathrm{True}$ follows by its constructor."
XML = canonicalize_openmath_xml_v4(
    '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
    '<OMS cd="logic1" name="true"/></OMOBJ>'
)
DRAFT = {
    "id": "proved_truth",
    "canonical_statement": "True holds.",
    "openmath_xml": XML,
    "proof_strategy": "Use the constructor of True.",
    "sketch_steps": ["Apply True.intro."],
}
VERDICT = {"approved": True, "rationale": "Isolated protocol fixture approval."}


def config(provider, key):
    return {
        "lean_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "answer_sha256": hashlib.sha256(ANSWER.encode()).hexdigest(),
        "output_language": "en",
        "source_author_principal": "pals.principal.v1/test-author",
        "reviewer_principal": "pals.principal.v1/test-reviewer",
        "review_key_id": "unit-key",
        "private_key": key,
        "client": OpenAIResponsesClient(api_key="test", transport=provider),
    }


def test_draft_closed_manifest_actual_response_identity_and_signature_binding():
    provider = ReceiptProvider([VERDICT], response_id="resp_draft_protocol_fixture")
    key = Ed25519PrivateKey.generate()  # ephemeral unit key; CLI never generates keys
    result = review_and_seal(DRAFT, XML, SOURCE, ANSWER, **config(provider, key))
    assert set(result) == {
        "schema_version",
        "draft",
        "embedding_text",
        "embedding_binding",
        "review",
        "review_key_id",
        "review_signature",
    }
    assert result["schema_version"] == "pals.candidate-draft.v1"
    assert result["draft"] == DRAFT and result["embedding_text"] == XML
    assert result["embedding_binding"] == NATURAL_BINDING
    review = result["review"]
    assert set(review) == {
        "schema_version",
        "lean_sha256",
        "answer_sha256",
        "draft_sha256",
        "embedding_text_sha256",
        "reviewer_principal",
        "provider_request_id",
        "approved",
        "rationale",
    }
    assert review["schema_version"] == "pals.candidate-draft-review.v1"
    assert review["provider_request_id"] == "resp_draft_protocol_fixture"
    assert review["draft_sha256"] == hashlib.sha256(rfc8785.dumps(DRAFT)).hexdigest()
    assert review["embedding_text_sha256"] == hashlib.sha256(XML.encode()).hexdigest()
    signature = bytes.fromhex(result["review_signature"])
    assert len(signature) == 64
    key.public_key().verify(signature, rfc8785.dumps(review))
    with pytest.raises(InvalidSignature):
        key.public_key().verify(signature, rfc8785.dumps(dict(review, answer_sha256="a" * 64)))
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["model"] == "gpt-6-luna" and "previous_response_id" not in call
    data = json.loads(call["input"].split("DATA:\n", 1)[1])
    assert data["lean_source"] == SOURCE and data["answer"] == ANSWER
    assert data["draft"] == DRAFT and data["embedding_binding"] == NATURAL_BINDING
    assert "never instructions" in call["input"] and "Reject when uncertain" in call["input"]


@pytest.mark.parametrize(
    "change",
    [
        {"lean_sha256": "a" * 64},
        {"answer_sha256": "b" * 64},
        {"output_language": "fr"},
        {"output_language": True},
        {"source_author_principal": "pals.principal.v1/test-reviewer"},
        {"reviewer_principal": "bad"},
        {"review_key_id": "bad key"},
    ],
)
def test_bad_bindings_fail_before_any_paid_call(change):
    provider = ReceiptProvider([])
    values = config(provider, Ed25519PrivateKey.generate())
    values.update(change)
    with pytest.raises(ValueError):
        review_and_seal(DRAFT, XML, SOURCE, ANSWER, **values)
    assert provider.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"id": "unsafe-id"},
        {"owner_user_id": "private"},
        {"canonical_statement": "x\x00"},
        {"proof_strategy": "\ud800"},
        {"sketch_steps": []},
        {"sketch_steps": [True]},
        {"sketch_steps": ["x"] * 129},
        {"sketch_steps": ["x" * 16_385]},
        {"proof_strategy": "界" * 21_846},
        {"openmath_xml": "<!DOCTYPE invalid>"},
    ],
)
def test_bad_payload_or_utf8_never_reaches_provider(change):
    provider = ReceiptProvider([])
    with pytest.raises(ValueError):
        review_and_seal(
            dict(DRAFT, **change),
            XML,
            SOURCE,
            ANSWER,
            **config(provider, Ed25519PrivateKey.generate()),
        )
    assert provider.calls == []


@pytest.mark.parametrize("embedding", [XML + "\n", "\x00", "\ud800"])
def test_noncanonical_or_changed_embedding_input_is_not_silently_rewritten(embedding):
    provider = ReceiptProvider([])
    with pytest.raises(ValueError):
        review_and_seal(
            DRAFT, embedding, SOURCE, ANSWER, **config(provider, Ed25519PrivateKey.generate())
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    ("source", "answer"),
    [
        ("界" * 66_667, ANSWER),
        (SOURCE, "界" * 60_001),
        (SOURCE + "\x00", ANSWER),
        (SOURCE, ANSWER + "\x00"),
    ],
)
def test_source_answer_utf8_and_scalar_bounds_are_checked_before_review(source, answer):
    provider = ReceiptProvider([])
    values = config(provider, Ed25519PrivateKey.generate())
    values.update(
        lean_sha256=hashlib.sha256(source.encode()).hexdigest(),
        answer_sha256=hashlib.sha256(answer.encode()).hexdigest(),
    )
    with pytest.raises(ValueError):
        review_and_seal(DRAFT, XML, source, answer, **values)
    assert provider.calls == []


@pytest.mark.parametrize(
    "verdict",
    [
        {"approved": False, "rationale": "Rejected."},
        {"approved": "true", "rationale": "Bad."},
        {"approved": 1, "rationale": "Bad."},
        {"approved": True, "rationale": "\x00"},
        {"approved": True, "rationale": "x" * 2001},
        dict(VERDICT, extra=True),
    ],
)
def test_provider_rejection_or_malformed_verdict_never_seals(verdict):
    with pytest.raises(ValueError):
        review_and_seal(
            DRAFT,
            XML,
            SOURCE,
            ANSWER,
            **config(ReceiptProvider([verdict]), Ed25519PrivateKey.generate()),
        )


def test_missing_real_response_identity_is_not_substituted_by_local_uuid():
    with pytest.raises(ValueError):
        review_and_seal(
            DRAFT,
            XML,
            SOURCE,
            ANSWER,
            **config(ReceiptProvider([VERDICT], response_id=None), Ed25519PrivateKey.generate()),
        )


def test_aggregate_escaping_bound_rejects_before_provider():
    draft = deepcopy(DRAFT)
    draft["sketch_steps"] = ["界" * 16_384] * 128
    provider = ReceiptProvider([])
    with pytest.raises(ValueError):
        review_and_seal(
            draft, XML, SOURCE, ANSWER, **config(provider, Ed25519PrivateKey.generate())
        )
    assert provider.calls == []


def test_cli_writes_canonical_manifest_with_existing_key_and_preserves_output(
    tmp_path, monkeypatch
):
    provider = ReceiptProvider([VERDICT])
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(
        "pals_agent.draft_entry_review.OpenAIResponsesClient",
        lambda **kwargs: OpenAIResponsesClient(api_key="test", transport=provider),
    )
    files = {
        "draft": rfc8785.dumps(DRAFT),
        "embedding-text": XML.encode(),
        "lean-source": SOURCE.encode(),
        "answer": ANSWER.encode(),
        "private-key": key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
    }
    args = []
    for name, data in files.items():
        path = tmp_path / name
        path.write_bytes(data)
        args += ["--" + name, str(path)]
    output = tmp_path / "sealed.json"
    args += [
        "--output",
        str(output),
        "--lean-sha256",
        hashlib.sha256(SOURCE.encode()).hexdigest(),
        "--answer-sha256",
        hashlib.sha256(ANSWER.encode()).hexdigest(),
        "--output-language",
        "en",
        "--source-author-principal",
        "pals.principal.v1/test-author",
        "--reviewer-principal",
        "pals.principal.v1/test-reviewer",
        "--review-key-id",
        "unit-key",
    ]
    assert main(args) == 0
    raw = output.read_bytes()
    result = json.loads(raw)
    assert rfc8785.dumps(result) == raw
    key.public_key().verify(
        bytes.fromhex(result["review_signature"]), rfc8785.dumps(result["review"])
    )
    assert main(args) == 1
    assert output.read_bytes() == raw and len(provider.calls) == 1
