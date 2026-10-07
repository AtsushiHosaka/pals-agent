"""PFR-017/020 real client paths against isolated permit/provider boundaries."""

import time

import pytest

from pals_agent.input_fence import InputSnapshotObsolete
from pals_agent.lean import LeanVerifier
from pals_agent.linked_input import linked_call_scope, linked_job_scope
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.token_meter import active_token_meter
from pals_agent.worker import SqsProofWorker
from tests.unit.test_proof_input import InputApi, amendment
from tests.unit.test_proof_request_worker import CLAIM_ID, REQUEST_ID
from tests.unit.test_token_meter import OP
from tests.unit.test_token_proof_request import CountedProvider

JOB = {"id": "linked-job", "proof_request_id": REQUEST_ID,
       "input_generation": 3, "billing_operation_id": OP}


@pytest.mark.parametrize("role", ["prove", "proof_review", "explain", "clarify"])
def test_each_linked_phase_obtains_permits_and_durable_receipts(role):
    api = InputApi()
    provider = CountedProvider([amendment()], [])
    client = OpenAIResponsesClient("test", transport=provider)
    with linked_job_scope(JOB), linked_call_scope(
        api, CLAIM_ID, time.monotonic() + 60, role=role
    ):
        assert active_token_meter() is not None
        client.generate(model="gpt-6-luna", prompt="untrusted math")
    assert active_token_meter() is None
    assert len(api.permits) == len(api.receipts) == 1
    assert api.permits[0]["binding_kind"] == "lean"
    assert api.permits[0]["proof_job_id"] == "linked-job"
    assert api.permits[0]["input_generation"] == 3
    assert api.permits[0]["model_role"] == role
    assert all(check["proof_job_id"] == "linked-job" for check in api.checks)


def test_late_hold_preserves_first_receipt_and_prevents_next_provider_call():
    api = InputApi()
    provider = CountedProvider([amendment(), amendment()], [])
    client = OpenAIResponsesClient("test", transport=provider)
    with linked_job_scope(JOB), linked_call_scope(api, CLAIM_ID, time.monotonic() + 60):
        client.generate(model="gpt-6-luna", prompt="first")
        api.current = False
        with pytest.raises(InputSnapshotObsolete):
            client.generate(model="gpt-6-luna", prompt="obsolete")
    assert len(provider.calls) == len(api.receipts) == 1


def test_count_policy_linked_job_checks_snapshot_without_token_meter():
    api = InputApi()
    job = {key: value for key, value in JOB.items() if key != "billing_operation_id"}
    with linked_job_scope(job), linked_call_scope(api, CLAIM_ID, time.monotonic() + 60):
        assert active_token_meter() is None
    assert len(api.checks) == 1


def test_hold_stops_before_any_lean_compilation(tmp_path):
    # No subprocess should be launched: a controllable verifier boundary checks
    # the same current generation as provider calls.
    from pals_agent.input_fence import input_fence_scope

    verifier = LeanVerifier(project_dir=tmp_path)
    current = True
    with input_fence_scope(lambda: current):
        current = False
        with pytest.raises(InputSnapshotObsolete):
            verifier.verify("example : True := by trivial")


def test_paid_recipe_review_cannot_dispatch_unmetered_external_actor():
    from types import SimpleNamespace

    def forbidden(**kwargs):
        pytest.fail("The dedicated reviewer has no permit port for paid calls")

    worker = SqsProofWorker(
        settings=SimpleNamespace(), api_client=InputApi(), pipeline=None, explainer=None,
        recipe_review_dispatcher=SimpleNamespace(request=forbidden),
    )
    with linked_job_scope(JOB):
        assert not worker._request_recipe_review(
            proof_job_id="linked-job", candidate_id="candidate", claim_id=CLAIM_ID,
            extend_visibility=lambda _: None,
        )
