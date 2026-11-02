"""Compound-task boundary tests, not provider-accuracy or fresh Lean evidence."""

import hashlib
import importlib.util
import json
import time
from pathlib import Path

import pytest

from pals_agent import recipe_semantic_contract as contract
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_semantic import SemanticReuseError, attempt
from pals_agent.usage import usage_scope
from tests.unit.test_recipe_semantic import Provider, inputs

CALCULATE = {"kind": "compute", "answer_relation": "computes_value"}
PROVE = {"kind": "prove", "answer_relation": "proves_assertion"}


@pytest.fixture(autouse=True)
def judges_only(monkeypatch):
    monkeypatch.setattr("pals_agent.recipe_semantic.query_embedding", lambda *a, **k: None)


def cubic_inputs():
    request, batch, verdict = inputs()
    request["statement"] = (
        "f(x)=x³−3x を実数全体で定義します。任意の x∈ℝ における f の微分係数を求め、"
        "その式が成立することを証明してください。"
    )
    base = Path(__file__).parents[2] / "testdata/requested-math-seeds-v1"
    spec = importlib.util.spec_from_file_location("compound_math_fixture", base / "publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((base / "publication/requested.cubic_derivative.json").read_bytes())
    case = next(
        c
        for c in json.loads((base / "corpus.json").read_bytes())["cases"]
        if c["id"] == "requested.cubic_derivative"
    )
    row = batch["recipes"][0]
    row.update(
        recipe_id=case["id"],
        statement=case["statement"],
        domain=case["family_id"],
        assumptions=case["assumptions"],
        quantifiers=case["quantifiers"],
        conclusion=manifest["target_source"],
        target_source=manifest["target_source"],
        lean_code=module.materialize(manifest).decode(),
        answer=case["answer"],
    )
    row["lean_sha256"] = hashlib.sha256(row["lean_code"].encode()).hexdigest()
    row["answer_sha256"] = hashlib.sha256(row["answer"].encode()).hexdigest()
    # The isolated HTTP fixture claims no catalog signature or actual compiler receipt.
    row["entry_sha256"] = contract.digest({"synthetic_entry_fixture": row["recipe_id"]})
    row["compiler_receipt_sha256"] = contract.digest(
        {"synthetic_receipt_fixture": row["recipe_id"]}
    )
    batch["request_context_sha256"] = contract.digest(
        {k: request[k] for k in ("statement", "context_turns", "output_language")}
    )
    batch["batch_sha256"] = contract.digest(
        {
            "schema_version": contract.CONTENT_SCHEMA,
            **{k: batch[k] for k in contract.CONTENT_FIELDS},
        }
    )
    verdict.update(
        recipe_id=row["recipe_id"],
        relevant_conventions=[],
        tasks=[CALCULATE, PROVE],
        source_target_sha256=hashlib.sha256(row["target_source"].encode()).hexdigest(),
        request_scope={
            "objects_and_types": ["f : Real -> Real; f(x) = x^3 - 3*x"],
            "domain": "Real",
            "assumptions": [],
            "quantifiers_and_dependencies": ["for every real x"],
            "conclusion": "calculate f'(x) and prove the formula at every real x",
            "required_method": None,
        },
    )
    return request, batch, verdict


class CompoundProvider(Provider):
    """Isolate provider I/O; exercise production prompt, parser and orchestration."""

    def __init__(self, verdict, *, review_tasks=None, qa=True, scope=True):
        super().__init__(verdict)
        self.review_tasks, self.qa, self.scope = review_tasks, qa, scope

    def request(self, **kwargs):
        response = super().request(**kwargs)
        if kwargs["url"].endswith("/input_tokens"):
            return response
        sent = json.loads(kwargs["body"])
        policy = sent["input"].split("\nCATALOG_DATA:\n", 1)[0]
        assert "record BOTH compute AND prove" in policy
        assert "even when the same derivation discharges both obligations" in policy
        assert "when the request only asks for a justified calculation" in policy
        assert "cubic" not in policy and "x³" not in policy
        if "ROLE: Act as an adversarial" not in sent["input"]:
            return response
        payload = json.loads(response.body)
        value = json.loads(payload["output"][0]["content"][0]["text"])
        if self.review_tasks is not None:
            value["tasks"] = self.review_tasks
        value["answer_qa"], value["checks"]["conclusion"] = self.qa, self.scope
        payload["output"][0]["content"][0]["text"] = json.dumps(value)
        return type(response)(response.status_code, json.dumps(payload).encode())


def run_cubic(provider):
    request, batch, _ = cubic_inputs()
    records = []
    with usage_scope(records.append):
        result = attempt(
            OpenAIResponsesClient(api_key="isolated-boundary", transport=provider),
            request,
            batch["claim_id"],
            lambda _vector: batch,
            deadline=time.monotonic() + 30,
        )
    return result, records, batch


@pytest.mark.parametrize("tasks", [[CALCULATE, PROVE], [PROVE, CALCULATE]])
def test_cubic_both_obligations_require_independent_agreement(tasks):
    provider = CompoundProvider(cubic_inputs()[2], review_tasks=tasks)
    result, records, batch = run_cubic(provider)
    assert result.answer is not None and result.answer["text"] == batch["recipes"][0]["answer"]
    receipt = result.evidence["recipe_semantic_correspondence"]
    assert all(len(receipt[r]["result"]["tasks"]) == 2 for r in ("assessment", "review"))
    assert len(provider.calls) == len(records) == 2
    assert receipt["assessment"]["session_id"] != receipt["review"]["session_id"]
    assert {r["provider_request_id"] for r in records} == {"resp_assessment_a", "resp_review_b"}


@pytest.mark.parametrize("tasks", [[CALCULATE], [PROVE]])
def test_missing_compute_or_proof_is_not_filled_in_after_review(tasks):
    provider = CompoundProvider(cubic_inputs()[2], review_tasks=tasks)
    result, records, _ = run_cubic(provider)
    assert result.answer is None and len(records) == len(provider.calls) == 2
    assert "recipe_semantic_correspondence" not in result.evidence
    evidence = result.evidence["recipe_semantic_attempt"]
    assert evidence["review"]["result"]["tasks"] == tasks
    assert len(evidence["assessment"]["result"]["tasks"]) == 2


@pytest.mark.parametrize("qa,scope", [(False, True), (True, False)])
def test_task_agreement_cannot_override_missing_answer_or_proof_scope(qa, scope):
    provider = CompoundProvider(cubic_inputs()[2], qa=qa, scope=scope)
    with pytest.raises(SemanticReuseError):
        run_cubic(provider)
    assert len(provider.calls) == 2


def test_contradictory_task_kind_relation_still_fails_strict_parser():
    provider = CompoundProvider(
        cubic_inputs()[2],
        review_tasks=[CALCULATE, {"kind": "prove", "answer_relation": "computes_value"}],
    )
    with pytest.raises(SemanticReuseError):
        run_cubic(provider)
