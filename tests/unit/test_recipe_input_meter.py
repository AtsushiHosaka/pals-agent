"""Dedicated Recipe actor/provider boundary, isolated from actual DB admission."""

import json

from pals_agent.explanations import LeanProofSemanticReviewer
from pals_agent.http_transport import HttpResponse
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_semantic_reviewer import RecipeReviewActor, RecipeSemanticReviewApiClient
from tests.unit.test_proof_request_worker import REQUEST_ID
from tests.unit.test_recipe_semantic_reviewer import Api
from tests.unit.test_token_meter import OP, Ledger
from tests.unit.test_token_proof_request import CountedProvider


class MeteredApi(Api, Ledger):
    def __init__(self):
        Api.__init__(self)
        Ledger.__init__(self, [])
        self.content.update(proof_request_id=REQUEST_ID, input_generation=2,
                            billing_operation_id=OP)


def test_dedicated_actor_meters_exact_candidate_and_source_without_worker_credentials():
    api = MeteredApi()
    provider = CountedProvider([{"approved": True, "rationale": "True by construction."}], [])
    client = OpenAIResponsesClient("test", transport=provider)
    actor = RecipeReviewActor(api, lambda: LeanProofSemanticReviewer(
        client, "gpt-6-luna", "openai"
    ))
    assert actor.review("proof-1", api.candidate)["state"] == "verified"
    assert len(api.permits) == len(api.receipts) == len(provider.calls) == 1
    permit = api.permits[0]
    assert permit["model_role"] == "proof_qa" and permit["binding_kind"] == "lean"
    assert permit["verification_candidate_id"] == api.candidate
    assert permit["source_binding_sha256"] == "a" * 64
    assert permit["claim_id"] == api.content["mutation_claim_id"]
    assert permit["input_generation"] == 2 and permit["proof_job_id"] == "proof-1"


def test_dedicated_meter_api_routes_use_only_reviewer_secret():
    calls = []

    class Transport:
        def request(self, **kwargs):
            calls.append(kwargs)
            return HttpResponse(200, json.dumps(
                {"permitted": True} if kwargs["url"].endswith("permits")
                else {"recorded": True}
            ).encode())

    client = RecipeSemanticReviewApiClient("http://api", "reviewer", transport=Transport())
    client.permit_token_call({"proof_job_id": "proof-1"}, timeout_seconds=2)
    client.record_token_receipt({"call_id": "call-1"}, timeout_seconds=2)
    assert [call["url"].rsplit("/", 1)[1] for call in calls] == [
        "recipe-token-permits", "recipe-token-receipts"
    ]
    for call in calls:
        assert call["headers"]["X-PALS-Recipe-Semantic-Reviewer-Secret"] == "reviewer"
        assert "X-PALS-Worker-Secret" not in call["headers"]


def test_dedicated_actor_fails_closed_if_paid_metadata_has_no_generation():
    api = MeteredApi()
    del api.content["input_generation"]

    def forbidden():
        raise AssertionError("Must not construct a provider before validating its binding")

    assert RecipeReviewActor(api, forbidden).review("proof-1", api.candidate)["state"] == "failed"
    assert not api.permits and api.failures
