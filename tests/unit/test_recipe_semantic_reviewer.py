import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.explanations import ProofSemanticReview
from pals_agent.recipe_semantic_reviewer import (
    RecipeReviewActor,
    RecipeSemanticReviewApiClient,
    ReviewBusyError,
    _closed_object,
)


class Api:
    reviewer_secret = "reviewer-only"

    def __init__(self):
        self.candidate = str(uuid4())
        self.content = {
            "id": "proof-1",
            "state": "semantic_review",
            "verification_candidate_id": self.candidate,
            "attempt_source": "recipe",
            "source_binding_sha256": "a" * 64,
            "mutation_claim_id": str(uuid4()),
            "result_artifact_uri": "s3://proof-artifacts/proof-jobs/proof-1/result.lean",
            "theorem_statement": "True",
            "formal_statement": None,
            "lean_code": "example : True := by trivial",
            "target_declaration": {"kind": "example", "name": None, "proposition": "True"},
        }
        self.writes = []
        self.failures = []

    def get_input(self, job, candidate):
        assert (job, candidate) == ("proof-1", self.candidate)
        return dict(self.content)

    def settle_unavailable(self, job, failure):
        self.failures.append(failure)
        self.content["state"] = "failed"
        return dict(self.content)

    def settle(self, job, evidence):
        self.writes.append(evidence)
        self.content["state"] = "verified"
        return dict(self.content)


def test_actor_fetches_exact_context_and_does_not_review_terminal_replay():
    api = Api()
    calls = []

    class Reviewer:
        def review_proof(self, **kwargs):
            calls.append(kwargs)
            return ProofSemanticReview(
                "approved", "True by its constructor.", "unit-provider", "unit-model", str(uuid4())
            )

    actor = RecipeReviewActor(api, Reviewer)
    assert actor.review("proof-1", api.candidate)["state"] == "verified"
    assert actor.review("proof-1", api.candidate)["state"] == "verified"
    assert len(calls) == len(api.writes) == 1
    assert calls[0]["lean_code"] == api.content["lean_code"]
    assert api.writes[0]["source_binding_sha256"] == "a" * 64
    assert "reviewer_principal" not in api.writes[0]
    assert "generator_session_id" not in api.writes[0]


def test_actor_concurrent_duplicate_is_busy_and_failed_call_releases_slot():
    api = Api()
    entered, release = threading.Event(), threading.Event()

    class Reviewer:
        def review_proof(self, **kwargs):
            entered.set()
            assert release.wait(2)
            raise RuntimeError("model unavailable")

    actor = RecipeReviewActor(api, Reviewer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(actor.review, "proof-1", api.candidate)
        assert entered.wait(2)
        with pytest.raises(ReviewBusyError):
            actor.review("proof-1", api.candidate)
        release.set()
        assert pending.result(timeout=2)["state"] == "failed"
    assert len(api.failures) == 1
    assert api.failures[0]["failure_kind"] == "internal"
    assert actor._active == set() and api.writes == []


def test_mismatched_authoritative_target_never_calls_model():
    api = Api()
    api.content["target_declaration"]["proposition"] = "False"

    def forbidden():
        raise AssertionError("must not create a model")

    with pytest.raises(ValueError, match="target differs"):
        RecipeReviewActor(api, forbidden).review("proof-1", api.candidate)


def test_worker_client_cannot_submit_dedicated_review():
    with pytest.raises(PalsApiError, match="dedicated reviewer"):
        PalsApiClient("http://api", "worker").settle_recipe_semantic_review(
            proof_job_id="p", evidence={}
        )


def test_reviewer_client_sends_no_worker_credential():
    api = Api()
    from pals_agent.http_transport import HttpResponse

    class Transport:
        def request(self, **kwargs):
            assert kwargs["headers"] == {
                "Accept": "application/json",
                "X-PALS-Recipe-Semantic-Reviewer-Secret": "reviewer",
            }
            assert kwargs["url"].endswith("/semantic-review-input?candidate_id=" + api.candidate)
            return HttpResponse(status_code=200, body=json.dumps(api.content).encode())

    result = RecipeSemanticReviewApiClient(
        "http://api", "reviewer", transport=Transport()
    ).get_input("proof-1", api.candidate)
    assert result == api.content


def test_duplicate_request_keys_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        json.loads('{"candidate_id":"a","candidate_id":"b"}', object_pairs_hook=_closed_object)


@pytest.fixture
def http_actor_server():
    """Real local HTTP boundary; the actor double performs no model/API calls."""
    from types import SimpleNamespace

    from pals_agent.recipe_semantic_reviewer import create_server

    class Actor:
        api = SimpleNamespace(reviewer_secret="reviewer-only")

        def __init__(self):
            self.calls = []

        def review(self, job, candidate):
            self.calls.append((job, candidate))
            return {"state": "verified"}

    actor = Actor()
    server = create_server(
        actor, "requester-only", host="127.0.0.1", port=0,
        max_http_requests=2, request_timeout_seconds=0.3,
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield server, actor
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def _raw_request(server, extra_headers=(), *, body=None, omit=()):
    import socket

    body = body or b'{"proof_job_id":"proof-1","candidate_id":"candidate-1"}'
    headers = {
        "X-PALS-Recipe-Review-Requester-Secret": "requester-only",
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
    }
    encoded = "POST /v1/reviews HTTP/1.0\r\n" + "".join(
        f"{name}: {value}\r\n" for name, value in headers.items() if name not in omit
    ) + "".join(f"{name}: {value}\r\n" for name, value in extra_headers) + "\r\n"
    with socket.create_connection(server.server_address, timeout=2) as connection:
        connection.sendall(encoded.encode() + body)
        result = b""
        while chunk := connection.recv(4096):
            result += chunk
    return int(result.split(b" ", 2)[1])


@pytest.mark.parametrize(("headers", "body", "omit", "status"), [
    ([("X-PALS-Recipe-Review-Requester-Secret", "requester-only")], None, (), 401),
    ([("Content-Length", "51")], None, (), 400),
    ([("Transfer-Encoding", "chunked")], None, (), 400),
    ([("Content-Type", "text/plain")], None, ("Content-Type",), 400),
    ([("Content-Type", "application/json")], None, (), 400),
    ([], None, ("Content-Length",), 400),
    ([], b'{"proof_job_id":"p","proof_job_id":"p","candidate_id":"c"}', (), 400),
    ([], b'[]', (), 400),
])
def test_http_rejects_ambiguous_or_open_requests_before_actor(
    http_actor_server, headers, body, omit, status,
):
    server, actor = http_actor_server
    assert _raw_request(server, headers, body=body, omit=omit) == status
    assert actor.calls == []


def test_http_header_readers_are_bounded_and_timeout_releases_capacity(http_actor_server):
    import socket

    server, actor = http_actor_server
    connections = []
    try:
        for _ in range(2):
            connection = socket.create_connection(server.server_address, timeout=2)
            connections.append(connection)
            connection.sendall(b"POST /v1/reviews HTTP/1.0\r\nX-Incomplete:")
        with socket.create_connection(server.server_address, timeout=2) as overflow:
            assert b"503 Service Unavailable" in overflow.recv(4096)
        assert actor.calls == []
        # Incomplete headers themselves time out, before do_POST is called.
        for connection in connections:
            assert connection.recv(4096) == b""
        assert _raw_request(server) == 200
        assert actor.calls == [("proof-1", "candidate-1")]
    finally:
        for connection in connections:
            connection.close()


def test_dedicated_operational_failure_lost_response_does_not_review_terminal_replay():
    class LostResponseApi(Api):
        def settle_unavailable(self, job, failure):
            super().settle_unavailable(job, failure)
            raise PalsApiError("response lost")

    calls = []

    class Reviewer:
        def review_proof(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("provider unavailable")

    api = LostResponseApi()
    actor = RecipeReviewActor(api, Reviewer)
    with pytest.raises(PalsApiError, match="response lost"):
        actor.review("proof-1", api.candidate)
    assert actor.review("proof-1", api.candidate)["state"] == "failed"
    assert len(calls) == len(api.failures) == 1
    assert api.writes == []
    assert api.failures[0]["mutation_claim_id"] == api.content["mutation_claim_id"]


def test_lost_mathematical_settlement_never_fabricates_operational_failure():
    class LostResponseApi(Api):
        def settle(self, job, evidence):
            super().settle(job, evidence)
            raise PalsApiError("response lost")

    class Reviewer:
        def review_proof(self, **kwargs):
            return ProofSemanticReview("approved", "True by constructor", "p", "m", str(uuid4()))

    api = LostResponseApi()
    actor = RecipeReviewActor(api, Reviewer)
    with pytest.raises(PalsApiError, match="response lost"):
        actor.review("proof-1", api.candidate)
    assert actor.review("proof-1", api.candidate)["state"] == "verified"
    assert api.failures == [] and len(api.writes) == 1
