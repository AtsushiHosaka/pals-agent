from __future__ import annotations

from pals_agent.models import ProofDraft
from pals_agent.openmath import (
    canonicalize_retrieval_openmath_xml,
    retrieval_openmath_structural_features,
    validate_canonical_retrieval_openmath_xml,
)
from pals_agent.private_draft_candidates import DraftCandidate
from pals_agent.proof_flow_evidence import project_draft_evidence

_CLOSED_EQUALITY = (
    '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
    '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="x"/></OMBVAR><OMA>'
    '<OMS cd="relation1" name="eq"/><OMV name="x"/><OMV name="x"/>'
    "</OMA></OMBIND></OMOBJ>"
)


def test_pfi_ag_004_closed_quantified_feature_oracle_has_exact_weight_71() -> None:
    canonical = canonicalize_retrieval_openmath_xml(_CLOSED_EQUALITY)

    features = retrieval_openmath_structural_features(canonical)

    assert sum(features.values()) == 71
    assert features["bound-count:1"] == 4
    assert features[
        "binder:('http://www.openmath.org/cd', 'quant1', 'forall')"
    ] == 5


def test_pfi_ag_004_evidence_preserves_candidate_order_and_has_no_selection_rule() -> None:
    canonical = canonicalize_retrieval_openmath_xml(_CLOSED_EQUALITY)
    first = DraftCandidate(
        draft=ProofDraft(
            id="a",
            matched_prompt="For all x, x equals x.",
            openmath_xml=canonical,
            proof_strategy="Use reflexivity.",
            sketch_steps=("Apply reflexivity.",),
        ),
        cosine_distance=0.0,
    )
    second = DraftCandidate(
        draft=ProofDraft(
            id="b",
            matched_prompt="For all x, x equals x.",
            openmath_xml=canonical,
            proof_strategy="Use reflexivity.",
            sketch_steps=("Apply reflexivity.",),
        ),
        cosine_distance=0.5,
    )

    evidence = project_draft_evidence(
        query_openmath_xml=canonical,
        candidates=(first, second),
    )

    assert [item.candidate.draft.id for item in evidence] == ["a", "b"]
    actual = [
        (item.vector_score, item.structural_score, item.exact_equivalence)
        for item in evidence
    ]
    assert actual == [
        (1.0, 1.0, True),
        (0.5, 1.0, True),
    ]


def test_pfi_ag_004_reparses_cpython_canonical_transport_bytes_without_normalizing_them() -> None:
    canonical = canonicalize_retrieval_openmath_xml(_CLOSED_EQUALITY)

    assert validate_canonical_retrieval_openmath_xml(canonical) == canonical
