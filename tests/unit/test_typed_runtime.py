from pathlib import Path
from types import SimpleNamespace

import pytest

from pals_agent.private_draft_candidates import DraftCandidateCompatibilityError
from pals_agent.private_typed_candidates import PrivateTypedCandidateClient, profile_contract
from pals_agent.typed_evaluation import evaluate
from pals_agent.typed_release import profile_bindings

ROOT = Path(__file__).resolve().parents[3]


def test_runtime_profile_binding_matches_release_binding():
    bindings = profile_bindings(ROOT)
    assert len(bindings) >= 13
    for profile, binding in bindings.items():
        assert profile_contract(profile)[1] == binding


def test_unknown_profile_fails_before_any_remote_request():
    class ForbiddenTransport:
        def request(self, **kwargs):
            pytest.fail("unsupported profile must not call generic or typed remote APIs")

    client = PrivateTypedCandidateClient("http://localhost", "secret", ForbiddenTransport())
    with pytest.raises(DraftCandidateCompatibilityError, match="unsupported"):
        client.find_candidates(
            profile_id="typed-unreviewed-v1", query_openmath="x", embedding=[1.0] * 384
        )


def test_evaluation_reads_real_proof_boundary_instead_of_accepting_success_boolean():
    from pals_agent.typed_local_catalog import load_typed_local_catalog_manifest

    manifest = load_typed_local_catalog_manifest(
        ROOT / "docs/typed-math-matrix-v1-authoring-manifest.proposal.json", repository_root=ROOT
    )
    xml = manifest.cards[0].canonical_openmath_xml
    draft_id = manifest.cards[0].card_id
    corpus = dict(
        schema_version="pals.typed-catalog-evaluation-corpus.v1",
        profile_id="typed-math-matrix-v1",
        layout_sha256="a" * 64,
        queries=[
            dict(
                family_id="matrix",
                statement="positive",
                canonical_openmath_xml=xml,
                expected_draft_ids=[draft_id],
                proof_job_id="job",
            ),
            dict(
                family_id="matrix",
                statement="negative",
                canonical_openmath_xml=xml,
                expected_draft_ids=[],
                proof_job_id=None,
            ),
        ],
    )

    class Runtime:
        def retrieve_for_profile(self, profile, statement):
            return SimpleNamespace(
                query_openmath=xml,
                compatibility={"seed_manifest_sha256": "sha256:" + "a" * 64},
                candidate_ids=(draft_id,),
                contexts=(
                    SimpleNamespace(candidate=SimpleNamespace(draft=SimpleNamespace(id=draft_id))),
                )
                if statement == "positive"
                else (),
            )

    class Proof:
        state = "verified"
        statement = "different statement"

        def get_proof_job(self, jid):
            return dict(state=self.state, theorem_statement=self.statement)

    proof = Proof()
    report = evaluate(corpus, Runtime(), proof, "test-evaluator")
    assert report["families"][0]["verified_completion_rate"] == 0
    proof.statement = "positive"
    assert (
        evaluate(corpus, Runtime(), proof, "test-evaluator")["families"][0][
            "verified_completion_rate"
        ]
        == 1
    )
    proof.state = "compiling"
    assert (
        evaluate(corpus, Runtime(), proof, "test-evaluator")["families"][0][
            "verified_completion_rate"
        ]
        == 0
    )
    corpus["queries"][0]["verified"] = True
    with pytest.raises(ValueError):
        evaluate(corpus, Runtime(), proof, "test-evaluator")
