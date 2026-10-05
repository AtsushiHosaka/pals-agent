"""Real signing and production reviewer wiring with isolated provider HTTP responses.

These unit tests prove the protocol; live provider/DB evidence is a separate check.
"""

import hashlib
import json

import pytest
import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_entry_review import main, review_and_seal
from tests.unit.test_proof_reuse import ProviderTransport
from tests.unit.test_proof_reuse_lean_flow import RECIPE, REVIEW, SOURCE

ENTRY = {
    **{
        field: RECIPE[field]
        for field in (
            "recipe_id",
            "recipe_revision",
            "statement",
            "domain",
            "assumptions",
            "quantifiers",
            "conclusion",
            "proof_method_tag",
            "output_language",
            "answer",
            "answer_sha256",
            "lean_sha256",
            "compiler_receipt_sha256",
            "toolchain_sha256",
        )
    },
    "schema_version": "pals.recipe-search-entry.v1",
    "search_text": "Continuity of the square function on the real numbers",
    "target_sha256": hashlib.sha256(RECIPE["target_source"].encode()).hexdigest(),
}


class ReceiptProvider(ProviderTransport):
    def __init__(self, responses, *, response_id="resp_registration_review"):
        super().__init__(responses)
        self.response_id = response_id

    def request(self, **kwargs):
        response = super().request(**kwargs)
        body = json.loads(response.body)
        if self.response_id is not None:
            body["id"] = self.response_id
        return HttpResponse(response.status_code, json.dumps(body).encode())


def seal(entry=ENTRY, source=SOURCE, verdict=REVIEW, *, response_id="resp_registration_review"):
    provider = ReceiptProvider([verdict], response_id=response_id)
    key = (
        Ed25519PrivateKey.generate()
    )  # ephemeral unit signing key; production never generates keys
    manifest = review_and_seal(
        entry,
        source,
        client=OpenAIResponsesClient(api_key="test", transport=provider),
        reviewer_principal="pals.principal.v1/test-reviewer",
        review_key_id="unit-test-key",
        private_key=key,
    )
    return manifest, provider, key


def test_entry_is_sealed_only_after_stateless_independent_actual_source_and_answer_review():
    manifest, provider, key = seal()
    assert manifest["entry"] == ENTRY
    review = manifest["review"]
    assert review["entry_sha256"] == hashlib.sha256(rfc8785.dumps(ENTRY)).hexdigest()
    assert (
        review["provider_request_id"] == "resp_registration_review" and review["approved"] is True
    )
    key.public_key().verify(bytes.fromhex(manifest["review_signature"]), rfc8785.dumps(review))
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["model"] == "gpt-6-luna" and "previous_response_id" not in call
    data = json.loads(call["input"].split("DATA:\n", 1)[1])
    assert data["lean_source"] == SOURCE and data["entry"]["answer"] == RECIPE["answer"]
    assert "untrusted content" in call["input"] and "Reject when uncertain" in call["input"]
    assert set(call["text"]["format"]["schema"]["properties"]) == {"approved", "rationale"}


@pytest.mark.parametrize(
    "changes",
    [
        {"answer": "tampered"},
        {"lean_sha256": "f" * 64},
        {"recipe_revision": True},
        {"approved": True},
        {"assumptions": ["\x00"]},
        {"answer_sha256": "bad"},
    ],
)
def test_bad_entry_is_rejected_before_any_paid_review(changes):
    provider = ReceiptProvider([])
    with pytest.raises(ValueError):
        review_and_seal(
            dict(ENTRY, **changes),
            SOURCE,
            client=OpenAIResponsesClient(api_key="test", transport=provider),
            reviewer_principal="pals.principal.v1/test-reviewer",
            review_key_id="unit-key",
            private_key=Ed25519PrivateKey.generate(),
        )
    assert provider.calls == []


@pytest.mark.parametrize(
    "verdict",
    [dict(REVIEW, approved=False), dict(REVIEW, approved="yes"), dict(REVIEW, unexpected=True)],
)
def test_review_rejection_or_malformed_verdict_never_produces_signature(verdict):
    with pytest.raises(ValueError):
        seal(verdict=verdict)


def test_missing_actual_provider_response_identity_is_not_replaced_by_local_uuid():
    with pytest.raises(ValueError):
        seal(response_id=None)


def test_cli_preserves_existing_output_without_reading_keys_or_calling_provider(tmp_path):
    output = tmp_path / "sealed.json"
    output.write_text("existing")
    assert (
        main(
            [
                "--entry",
                str(tmp_path / "missing.json"),
                "--lean-source",
                str(tmp_path / "missing.lean"),
                "--output",
                str(output),
                "--reviewer-principal",
                "pals.principal.v1/test-reviewer",
                "--review-key-id",
                "unit-key",
                "--private-key",
                str(tmp_path / "missing.pem"),
            ]
        )
        == 1
    )
    assert output.read_text() == "existing"
