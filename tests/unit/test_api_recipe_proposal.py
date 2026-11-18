"""Remote compiler hints preserve claim binding and never replace final review/compile."""

import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from pals_agent import factory
from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.api_recipe_proposal import SCHEMA, RemoteGeneralRecipeStage
from pals_agent.http_transport import HttpResponse
from pals_agent.recipe_instantiation import elaborate
from tests.unit.test_general_recipe_stage import CLAIM_ID, POWER, REQUEST, call

pytest_plugins = ["tests.unit.test_general_recipe_stage"]

PROPOSITION = "Continuous (fun x : ℝ => x ^ 3)"
CONTEXT = {
    "request_id": REQUEST["id"],
    "claim_id": CLAIM_ID,
    "expected_revision": REQUEST["revision"],
    "request_context_sha256": "a" * 64,
}


def response(payload, decision="candidate", reason=None):
    instance = elaborate(POWER["lean_code"], payload["requested_proposition"])
    return {
        "schema_version": SCHEMA,
        "decision": decision,
        "reason": reason,
        "request_id": CONTEXT["request_id"],
        "claim_id": payload["claim_id"],
        "request_revision": payload["expected_revision"],
        "request_context_sha256": payload["request_context_sha256"],
        "recipe_id": payload["recipe_id"],
        "recipe_revision": payload["recipe_revision"],
        "entry_sha256": payload["entry_sha256"],
        "candidate": None
        if decision == "fallback"
        else {
            "instance_proposition": instance.proposition,
            "instance_proposition_sha256": instance.proposition_sha256,
            "instance_source_sha256": instance.source_sha256,
            "bindings": [],
        },
    }


class Transport:
    def __init__(self, change=None):
        self.calls = []
        self.change = change

    def request(self, **kwargs):
        self.calls.append(kwargs)
        result = response(json.loads(kwargs["body"]))
        if self.change:
            self.change(result)
        return HttpResponse(status_code=200, body=json.dumps(result).encode())


def client(transport):
    return PalsApiClient("https://api.invalid", "worker-test-only", transport=transport)


def payload():
    return {
        **CONTEXT,
        **{k: POWER[k] for k in ("recipe_id", "recipe_revision", "entry_sha256")},
        "requested_proposition": PROPOSITION,
        "bindings": [],
        "timeout_seconds": 10.0,
        "budget_ms": 9000,
    }


def test_authenticated_typed_client_uses_claim_bound_route_and_bounded_timeout():
    transport = Transport()
    result = client(transport).propose_recipe_instance(**payload())
    sent = transport.calls[0]
    assert sent["url"].endswith(
        f"/v1/internal/proof-requests/{REQUEST['id']}/recipe-instance-proposals"
    )
    assert sent["headers"]["X-PALS-Worker-Secret"] == "worker-test-only"
    assert sent["timeout_seconds"] == 10.0
    assert result["decision"] == "candidate"
    assert "approved" not in result and "recipe_instance_compile" not in result


@pytest.mark.parametrize(
    "key,value",
    [
        ("claim_id", "00000000-0000-4000-8000-000000000000"),
        ("request_revision", True),
        ("request_context_sha256", "b" * 64),
        ("entry_sha256", "b" * 64),
        ("approved", True),
    ],
)
def test_client_rejects_wrong_echo_or_extra_authority(key, value):
    transport = Transport(lambda value_: value_.update({key: value}))
    with pytest.raises(PalsApiError):
        client(transport).propose_recipe_instance(**payload())


def test_remote_stage_hands_only_candidate_to_unchanged_instantiation(on, handoff):
    transport = Transport()
    result, _ = call(RemoteGeneralRecipeStage(client(transport).propose_recipe_instance))
    assert result == "HANDED_OFF"
    proposal, evidence, _ = handoff[0]
    assert proposal["proposed"]["requested_proposition"] == PROPOSITION
    hint = evidence["general_recipe_lane"]
    assert hint["decision"] == "candidate" and hint["not_verified_answer"] is True
    assert "approved" not in hint and "verification_succeeded" not in hint


def test_remote_stage_does_not_start_with_insufficient_budget():
    def forbidden(**kwargs):
        raise AssertionError("low budget must not send HTTP")

    result = RemoteGeneralRecipeStage(forbidden).run(
        PROPOSITION, [POWER], "ja", budget_s=1.5, proposal_context=CONTEXT
    )
    assert result.outcome == "miss"


def test_remote_stage_rejects_api_source_hash_mismatch():
    transport = Transport(lambda r: r["candidate"].update(instance_source_sha256="b" * 64))
    result = RemoteGeneralRecipeStage(client(transport).propose_recipe_instance).run(
        PROPOSITION, [POWER], "ja", budget_s=10, proposal_context=CONTEXT
    )
    assert result.outcome == "miss"


def test_fallback_and_four_candidate_bound():
    calls = []

    def decline(**kwargs):
        calls.append(kwargs)
        return response(kwargs, "fallback", "not_instance")

    result = RemoteGeneralRecipeStage(decline).run(
        PROPOSITION, [POWER] * 8, "ja", budget_s=10, proposal_context=CONTEXT
    )
    assert result.outcome == "miss" and len(calls) == 4


@pytest.mark.parametrize("reason", ["disabled", "unavailable", "claim_budget"])
def test_unavailable_endpoint_is_normal_fallback(reason):
    calls = []

    def decline(**kwargs):
        calls.append(kwargs)
        return response(kwargs, "fallback", reason)

    result = RemoteGeneralRecipeStage(decline).run(
        PROPOSITION, [POWER] * 4, "ja", budget_s=10, proposal_context=CONTEXT
    )
    assert result.outcome == "miss" and len(calls) == 1


def test_factory_passes_actual_api_client_without_resolving_local_lean(monkeypatch):
    @dataclass
    class DummyClient:
        max_output_tokens: int = 1

    api = SimpleNamespace(propose_recipe_instance=lambda **kwargs: None)
    monkeypatch.setenv("PALS_GENERAL_RECIPE_LANE", "on")
    monkeypatch.setenv("PALS_RECIPE_INSTANTIATION", "on")
    monkeypatch.setattr(factory, "_release_openai_client", lambda settings: DummyClient())
    processor = factory.build_proof_request_processor(SimpleNamespace(), api)
    remote = processor.runtime.proof_runtime.general_lane
    assert isinstance(remote, RemoteGeneralRecipeStage)
    assert remote.propose is api.propose_recipe_instance


def test_factory_missing_flag_or_port_keeps_remote_disabled(monkeypatch):
    api = SimpleNamespace(propose_recipe_instance=lambda **kwargs: None)
    monkeypatch.delenv("PALS_GENERAL_RECIPE_LANE", raising=False)
    assert factory.general_recipe_lane_stage(api) is None
    monkeypatch.setenv("PALS_GENERAL_RECIPE_LANE", "on")
    monkeypatch.delenv("PALS_RECIPE_INSTANTIATION", raising=False)
    assert factory.general_recipe_lane_stage(api) is None
    monkeypatch.setenv("PALS_RECIPE_INSTANTIATION", "on")
    assert factory.general_recipe_lane_stage(SimpleNamespace()) is None


def test_server_budget_reserves_transport_and_stops_before_low_remaining(monkeypatch):
    from pals_agent import api_recipe_proposal

    now = [0.0]
    monkeypatch.setattr(api_recipe_proposal.time, "monotonic", lambda: now[0])
    calls = []

    def slow_miss(**kwargs):
        calls.append(kwargs)
        now[0] += 3.0
        return response(kwargs, "fallback", "not_instance")

    result = RemoteGeneralRecipeStage(slow_miss).run(
        PROPOSITION, [POWER] * 4, "ja", budget_s=5, proposal_context=CONTEXT
    )
    assert result.outcome == "miss" and len(calls) == 1
    assert calls[0]["timeout_seconds"] <= 5
    assert calls[0]["budget_ms"] == 4000


@pytest.mark.parametrize("budget", [True, 0, -1, 90_001, 10_001])
def test_client_rejects_unbounded_or_over_http_budget_without_sending(budget):
    transport = Transport()
    request = payload()
    request["budget_ms"] = budget
    with pytest.raises(ValueError):
        client(transport).propose_recipe_instance(**request)
    assert transport.calls == []
