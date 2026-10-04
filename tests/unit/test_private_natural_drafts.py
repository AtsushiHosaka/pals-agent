"""Natural sketch retrieval preserves the exact source contract, without formal claims."""

import hashlib
import json

import pytest
import rfc8785

from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.http_transport import HttpResponse
from pals_agent.openmath import canonicalize_openmath_xml, canonicalize_retrieval_openmath_xml
from pals_agent.private_natural_drafts import EMBEDDING_BINDING, NaturalDraftCandidateClient
from pals_agent.proof_instantiation import instantiate_universal
from pals_agent.proof_reuse import ProofReuseError, _candidate_payloads
from tests.unit.test_proof_instantiation import integer


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def power_source():
    # Fixture only: production always retrieves the authenticated database port.
    return SeedDraftCatalog().find_by_id("continuous_power").openmath_xml


def payload():
    source = {
        "id": "power",
        "canonical_statement": "Every natural power of x is continuous on R",
        "openmath_xml": canonicalize_retrieval_openmath_xml(power_source()),
        "proof_strategy": "Induction using continuous identity and product",
        "sketch_steps": ["Base is constant", "Multiply by identity for successor"],
    }
    digest = hashlib.sha256(rfc8785.dumps(source)).hexdigest()
    return {
        "schema_version": "pals.proof-request-draft-candidates.v1",
        "evidence_kind": "unverified_sketches",
        "catalog_revision_sha256": "a" * 64,
        "actual_row_count": 431,
        "embedding_binding": dict(EMBEDDING_BINDING),
        "candidates": [dict(source, payload_sha256=digest, distance=0.2)],
    }


def client(data, status=200):
    transport = Transport(HttpResponse(status, json.dumps(data).encode()))
    return NaturalDraftCandidateClient(
        "https://api.example.test", "test-secret", transport
    ), transport


def test_exact_api_payload_revision_and_alpha_binder_are_preserved():
    data = payload()
    adapter, transport = client(data)
    query = canonicalize_openmath_xml(power_source())
    result = adapter.retrieve(query, [0.5] * 384)
    row = _candidate_payloads(result)[0]
    assert row["revision"] == "sha256:" + data["candidates"][0]["payload_sha256"]
    assert result.compatibility["evidence_kind"] == "unverified_sketches"
    assert result.compatibility["actual_row_count"] == 431
    evidence = result.as_json()
    assert evidence["query_evidence_kind"] == "untrusted_retrieval_hint"
    assert "evidence" not in evidence["contexts"][0]
    assert evidence["contexts"][0]["cosine_distance"] == 0.2
    # v4 alpha-renames n: specialization must use the actual source binder identity.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(row["openmath_xml"])
    binder_name = root[0][1][0].attrib["name"]
    instance = instantiate_universal(
        row["openmath_xml"],
        [
            {"variable": binder_name, "term_openmath_xml": integer(2)},
        ],
    )
    assert instance.substitutions[0]["domain"] == "Nat"
    request = json.loads(transport.calls[0]["body"])
    assert request == {"embedding": [0.5] * 384, "embedding_binding": EMBEDDING_BINDING, "limit": 8}
    assert transport.calls[0]["headers"]["X-PALS-Worker-Secret"] == "test-secret"
    assert transport.calls[0]["timeout_seconds"] == 10


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=True),
        lambda d: d.update(evidence_kind="verified"),
        lambda d: d.update(actual_row_count=0),
        lambda d: d["embedding_binding"].update(canonicalizer_version="v3"),
        lambda d: d["candidates"][0].update(payload_sha256="b" * 64),
        lambda d: d["candidates"][0].update(proof_strategy="tampered proof"),
        lambda d: d["candidates"][0].update(distance=float("nan")),
    ],
)
def test_mismatched_or_unbounded_catalog_is_rejected(mutation):
    data = payload()
    mutation(data)
    adapter, _ = client(data)
    with pytest.raises(ProofReuseError, match="catalog_invalid"):
        adapter.retrieve(canonicalize_openmath_xml(power_source()), [0.5] * 384)


def test_transport_failure_is_not_empty_catalog_or_synthetic_seed():
    adapter, _ = client({}, status=503)
    with pytest.raises(ProofReuseError, match="catalog_unavailable"):
        adapter.retrieve(canonicalize_openmath_xml(power_source()), [0.5] * 384)


def test_invalid_vector_does_not_call_api():
    adapter, transport = client(payload())
    with pytest.raises(ProofReuseError, match="catalog_invalid"):
        adapter.retrieve(canonicalize_openmath_xml(power_source()), [0.5] * 383)
    assert transport.calls == []


def test_untrusted_search_hint_does_not_require_formal_theorem_admission():
    adapter, _ = client(payload())
    hint = canonicalize_openmath_xml(
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMV name="hint"/></OMOBJ>'
    )
    result = adapter.retrieve(hint, [0.5] * 384)
    assert result.query_openmath == hint
    assert result.contexts[0].candidate.draft.id == "power"
    assert result.as_json()["query_evidence_kind"] == "untrusted_retrieval_hint"
