"""Math conventions are confirmed by the learner, never guessed by the model (MCV-001–008)."""

import json

import pytest

from pals_agent.math_conventions import DEFAULTS, IDS, parse_claim
from pals_agent.proof_request_worker import ProofRequestProcessor
from pals_agent.proof_reuse import PREFLIGHT_SCHEMA
from tests.unit.test_proof_request_worker import CLAIM_ID, REQUEST_ID, LeanApiBoundary
from tests.unit.test_proof_reuse import READY, REQUEST, decision, runtime

# The same order is pinned in pals-api (specs/math-conventions/design.md).
SPEC_IDS = (
    "zero_ring_domain",
    "natural_zero",
    "ring_without_unit",
    "ring_commutative",
    "zero_pow_zero",
    "division_by_zero",
    "compact_hausdorff",
    "subset_proper",
    "positive_zero",
    "log_base_ten",
    "monotone_nonstrict",
)
DOMAIN = "Prove that every finite integral domain is a field."


def relevant(*ids, **change):
    check = dict(READY["premise_check"], conventions=list(ids))
    return dict(READY, premise_check=check, **change)


def with_conventions(policy="ask", **choices):
    return dict(REQUEST, statement=DOMAIN, math_conventions={"policy": policy, "choices": choices})


def test_ids_match_the_api_catalog_and_the_schema():
    assert IDS == SPEC_IDS
    assert {k for k, v in DEFAULTS.items() if v == "include"} == {
        "natural_zero",
        "zero_pow_zero",
        "monotone_nonstrict",
    }
    items = PREFLIGHT_SCHEMA["properties"]["premise_check"]["properties"]["conventions"]
    assert items["items"]["enum"] == list(SPEC_IDS)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"policy": "ask"},
        {"policy": "sometimes", "choices": {}},
        {"policy": "ask", "choices": {"unknown": "include"}},
        {"policy": "ask", "choices": {"natural_zero": "ask"}},
        {"policy": "ask", "choices": {}, "extra": True},
    ],
)
def test_malformed_claim_conventions_are_refused(value):
    assert parse_claim(value) is None
    engine, transport = runtime([READY])
    result = engine.answer(dict(REQUEST, math_conventions=value))
    assert (result.outcome, result.error_code) == ("failed", "proof_reuse_input_invalid")
    assert transport.calls == []


def test_unknown_relevant_reading_is_asked_before_anything_else():
    counterexample = dict(READY["premise_check"], counterexample="the zero ring",
                          conventions=["zero_ring_domain"])
    engine, transport = runtime([dict(READY, premise_check=counterexample)])
    result = engine.answer(with_conventions())
    assert result.outcome == "needs_input"
    assert result.question["convention_id"] == "zero_ring_domain"
    assert result.private_evidence["convention_question"] == "zero_ring_domain"
    assert "premise_check_fallback" not in result.private_evidence
    assert len(transport.calls) == 1
    data = json.loads(transport.calls[0]["input"].rsplit("\n", 1)[1])
    readings = {item["id"]: item["known_reading"] for item in data["math_conventions"]}
    assert readings["zero_ring_domain"] is None and set(readings) == set(SPEC_IDS)


def test_the_model_may_leave_the_convention_question_to_the_system():
    leave = relevant("natural_zero", action="needs_input", question=None)
    engine, _ = runtime([leave])
    result = engine.answer(with_conventions())
    assert result.question["convention_id"] == "natural_zero"
    engine, _ = runtime([leave])
    known = engine.answer(with_conventions(natural_zero="exclude"))
    assert (known.outcome, known.error_code) == ("failed", "proof_reuse_invalid_response")
    engine, _ = runtime([leave])
    released = engine.answer(dict(REQUEST, statement=DOMAIN))
    assert (released.outcome, released.error_code) == ("failed", "proof_reuse_invalid_response")


def test_known_reading_is_given_to_the_model_and_reported_as_applied():
    engine, transport = runtime([relevant("zero_ring_domain"), decision()])
    result = engine.answer(with_conventions(zero_ring_domain="exclude"))
    assert result.outcome == "answered"
    assert result.private_evidence["applied_conventions"] == [
        {"id": "zero_ring_domain", "choice": "exclude"}
    ]
    prompt = transport.calls[0]["input"]
    assert "Never ask about a listed convention yourself" in prompt
    assert "A reading changes only the notion it names" in prompt
    data = json.loads(prompt.rsplit("\n", 1)[1])
    assert {i["id"]: i["known_reading"] for i in data["math_conventions"]}[
        "zero_ring_domain"
    ] == "exclude"


def test_every_convention_has_both_readings_in_plain_words():
    from pals_agent.math_conventions import reading
    for item in SPEC_IDS:
        include, exclude = reading(item, "include"), reading(item, "exclude")
        assert include and exclude and include != exclude
        assert not include.startswith(("include", "exclude")) and not exclude.startswith("exclude")


def test_a_model_question_about_a_known_reading_is_not_asked():
    question = {"text": "How should 0^0 be treated?", "options": ["0^0 = 1", "undefined"]}
    asks = relevant("zero_pow_zero", action="needs_input", question=question, statement="")
    engine, transport = runtime([asks, decision()])
    request = dict(REQUEST, statement="Prove that x^0 = 1 for every real x.",
                   math_conventions={"policy": "default", "choices": {}})
    result = engine.answer(request)
    assert result.outcome == "answered"
    assert result.private_evidence["convention_question_suppressed"] is True
    assert result.private_evidence["applied_conventions"] == [
        {"id": "zero_pow_zero", "choice": "include"}
    ]
    assert "Conventions: 0^0 = 1. Every other definition keeps its standard meaning." in (
        transport.calls[1]["input"]
    )


def test_a_counterexample_question_is_still_asked_with_known_readings():
    check = dict(READY["premise_check"], conventions=["zero_pow_zero"], counterexample="x = 0")
    question = {"text": "This seems to fail at x = 0. Which claim?", "options": []}
    engine, _ = runtime([dict(READY, premise_check=check, action="needs_input", question=question)])
    result = engine.answer(dict(REQUEST, math_conventions={"policy": "default", "choices": {}}))
    assert result.outcome == "needs_input" and "convention_id" not in result.question


def test_guests_use_defaults_and_are_never_asked():
    engine, _ = runtime([relevant("natural_zero", "zero_ring_domain"), decision()])
    result = engine.answer(with_conventions(policy="default"))
    assert result.outcome == "answered"
    assert result.private_evidence["applied_conventions"] == [
        {"id": "natural_zero", "choice": "include"},
        {"id": "zero_ring_domain", "choice": "exclude"},
    ]


def test_without_released_conventions_nothing_is_asked_or_applied():
    engine, transport = runtime([relevant("zero_ring_domain"), decision()])
    result = engine.answer(dict(REQUEST, statement=DOMAIN))
    assert result.outcome == "answered"
    assert "applied_conventions" not in result.private_evidence
    assert "math_conventions" not in transport.calls[0]["input"].rsplit("\n", 1)[1]


class ConventionApi(LeanApiBoundary):
    def __init__(self, conventions):
        super().__init__([])
        self.conventions = conventions

    def acquire_proof_request_claim(self, **kwargs):
        return dict(super().acquire_proof_request_claim(**kwargs),
                    math_conventions=self.conventions)


def test_worker_passes_readings_and_settles_the_applied_ones():
    assessment = {key: value for key, value in decision().items()
                  if key not in {"answer", "next_input_suggestion"}}
    engine, _ = runtime([relevant("zero_ring_domain"), assessment])
    api = ConventionApi({"policy": "ask", "choices": {"zero_ring_domain": "include"}})
    assert ProofRequestProcessor(api, engine).process(REQUEST_ID, CLAIM_ID, lambda seconds: None)
    settlement = api.settlements[0]
    assert settlement["outcome"] == "formal"
    assert settlement["conventions"] == [{"id": "zero_ring_domain", "choice": "include"}]
    statement = settlement["formal_plan"]["statement"]
    assert statement.startswith(READY["statement"])
    assert statement.endswith(
        "Conventions: the zero ring (where 1 = 0) counts as an integral domain. "
        "Every other definition keeps its standard meaning."
    )
    assert statement.count("Conventions:") == 1


def test_worker_sends_the_convention_question_without_applied_readings():
    engine, _ = runtime([relevant("zero_ring_domain")])
    api = ConventionApi({"policy": "ask", "choices": {}})
    assert ProofRequestProcessor(api, engine).process(REQUEST_ID, CLAIM_ID, lambda seconds: None)
    settlement = api.settlements[0]
    assert settlement["outcome"] == "needs_input" and "conventions" not in settlement
    assert settlement["question"]["convention_id"] == "zero_ring_domain"


def test_worker_rejects_malformed_claim_conventions():
    engine, transport = runtime([READY])
    api = ConventionApi({"policy": "ask", "choices": {"zero_ring_domain": "maybe"}})
    assert ProofRequestProcessor(api, engine).process(
        REQUEST_ID, CLAIM_ID, lambda seconds: None
    ) is False
    assert api.settlements == [] and transport.calls == []
