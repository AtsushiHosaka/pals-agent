import json
from dataclasses import replace

import pytest

from pals_agent.http_transport import HttpResponse
from pals_agent.recipe_review_dispatch import RecipeReviewDispatcher
from pals_agent.settings import AgentSettings

JOB = "11111111-1111-4111-8111-111111111111"
CANDIDATE = "22222222-2222-4222-8222-222222222222"


def test_dispatch_has_only_requester_identity_and_immutable_ids():
    class Transport:
        def request(self, **request):
            assert request["url"] == "http://pals-recipe-reviewer:18119/v1/reviews"
            assert request["headers"] == {
                "Content-Type": "application/json",
                "X-PALS-Recipe-Review-Requester-Secret": "requester-secret",
            }
            assert json.loads(request["body"]) == {"proof_job_id": JOB, "candidate_id": CANDIDATE}
            return HttpResponse(200, json.dumps({"id": JOB, "state": "verified"}).encode())

    dispatcher = RecipeReviewDispatcher(
        "http://pals-recipe-reviewer:18119", "requester-secret", Transport()
    )
    assert "requester-secret" not in repr(dispatcher)
    dispatcher.request(proof_job_id=JOB, candidate_id=CANDIDATE, timeout_seconds=225)


@pytest.mark.parametrize("url", [
    "http://public.example", "https://example.com/path", "https://user:secret@example.com",
    "https://example.com?token=value", "https://example.com#fragment",
])
def test_dispatch_rejects_unsafe_origins(url):
    with pytest.raises(ValueError):
        RecipeReviewDispatcher(url, "requester-secret")


@pytest.mark.parametrize("status,body", [
    (503, b'{}'), (302, b'{}'), (200, b'{"id":"another-job"}'), (200, b'[]'),
])
def test_dispatch_unavailable_or_unbound_result_remains_retryable(status, body):
    class Transport:
        def request(self, **request):
            return HttpResponse(status, body)
    dispatcher = RecipeReviewDispatcher("http://localhost:18119", "requester", Transport())
    with pytest.raises(RuntimeError):
        dispatcher.request(proof_job_id=JOB, candidate_id=CANDIDATE, timeout_seconds=225)


def test_requester_configuration_cannot_reuse_the_worker_identity(monkeypatch):
    monkeypatch.setenv("PALS_WORKER_SHARED_SECRET", "worker-secret")
    settings = AgentSettings.from_env()
    with pytest.raises(ValueError, match="together"):
        replace(settings, recipe_reviewer_url="http://pals-recipe-reviewer:18119")
    with pytest.raises(ValueError, match="separate"):
        replace(settings, recipe_reviewer_url="http://pals-recipe-reviewer:18119",
                recipe_review_requester_secret="worker-secret")
