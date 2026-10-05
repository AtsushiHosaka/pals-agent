"""Exercise production assessment through an isolated provider HTTP boundary."""

import json

import pytest

from pals_agent.http_transport import HttpResponse
from pals_agent.lean import LeanVerifier
from pals_agent.models import ProofDraft
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.private_draft_candidates import DraftCandidate
from pals_agent.proof_flow_evidence import DraftEvidence
from pals_agent.proof_flow_runtime import DraftRetrievalResult
from pals_agent.proof_reuse import ProofReuseError, ProofReuseRuntime
from tests.unit.test_proof_instantiation import POWER, integer, universal

REQUEST = {
    "statement": "x²が実数全体で連続であることを示してください。",
    "output_language": "ja",
    "context_turns": [],
}
READY = {
    "action": "ready",
    "statement": REQUEST["statement"],
    "profile_id": "generic-v1",
    "requires_catalog_source": False,
    "question": None,
    "reason": "Domain and goal are supplied.",
    "premise_check": {"counterexample": "", "truth_depends_on": [], "assumed_defaults": []},
}


def decision(**overrides):
    return dict(
        {
            "action": "answer",
            "mode": "instantiate",
            "source_ids": ["power"],
            "substitutions": [{"variable": "n", "term_openmath_xml": integer(2)}],
            "premises": [{"statement": "2 ∈ ℕ", "justification": "2 is a natural number."}],
            "conclusion": "x²は実数全体で連続である。",
            "answer": (
                "定数関数 $1$ は連続であり、連続関数の積は連続である。"
                "帰納法で自然数 $n$ の全てについて $x^n$ は連続である。"
                "$n=2$ を適用して $x^2$ は連続である。"
            ),
            "supporting_proof": "Base n=0 constant; successor multiplies continuous x^n by x.",
            "dependency_cycle": False,
            "question": None,
            "reason": "Universal elimination.",
        },
        **overrides,
    )


class ProviderTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, **kwargs):
        body = json.loads(kwargs["body"])
        self.calls.append(body)
        response = self.responses.pop(0)
        if isinstance(response, int):
            return HttpResponse(response, b'{"error":{"code":"insufficient_quota"}}')
        text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        return HttpResponse(
            200,
            json.dumps(
                {
                    "object": "response",
                    "status": "completed",
                    "model": body["model"],
                    "error": None,
                    "incomplete_details": None,
                    "usage": {"input_tokens": 100, "output_tokens": 60},
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ],
                }
            ).encode(),
        )


class CatalogBoundary:
    profiles = ("generic-v1",)

    def __init__(self, source=None, error=None):
        self.calls = []
        self.source = source or universal(POWER)
        self.error = error

    def retrieve(self, statement, profile_id, *, deadline):
        self.calls.append((statement, profile_id))
        if self.error:
            raise self.error
        draft = ProofDraft(
            "power",
            "∀n∈ℕ, xⁿ is continuous on ℝ",
            self.source,
            "Induction on n using product continuity",
            ("Base, successor",),
        )
        item = DraftEvidence(DraftCandidate(draft, 0.2), 0.8, 0.8, False)
        return DraftRetrievalResult("match", universal(POWER), (item,), {"generation_id": "g1"})


def runtime(responses, catalog=None):
    transport = ProviderTransport(
        [*responses, {"approved": True, "rationale": "Complete proof and TeX math."}]
    )
    return ProofReuseRuntime(
        OpenAIResponsesClient(api_key="test", transport=transport), catalog or CatalogBoundary()
    ), transport


def test_real_assessment_path_reuses_general_theorem_without_any_lean(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No Lean may run for natural proof answers")

    monkeypatch.setattr(LeanVerifier, "verify", forbidden)
    engine, transport = runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    assert result.answer["evidence_kind"] == "llm_assessed"
    assert result.answer["sources"][0]["revision"].startswith("sha256:")
    assert result.private_evidence["instantiation"]["substitutions"][0]["domain"] == "Nat"
    assert [c["model"] for c in transport.calls] == ["gpt-6-luna"] * 3
    assert all(c["text"]["format"]["strict"] for c in transport.calls)
    assert "do not constrain this user's new request" in transport.calls[1]["input"]
    assert "prefer mode instantiate" in transport.calls[1]["input"]
    answer_prompt = transport.calls[1]["input"]
    assert "EVERY mathematical expression" in answer_prompt
    assert "Delimit each inline mathematical span with $...$" in answer_prompt
    assert "$x^m\\in I$" in answer_prompt
    assert "$x\\in\\sqrt{IJ}$" in answer_prompt
    assert "NEVER bare x^m∈I" in answer_prompt
    assert "escape each TeX backslash as \\\\" in answer_prompt
    assert transport.calls[2]["input"].startswith("Independently review")
    assert result.private_evidence["answer_qa"]["approved"] is True


def test_unmetered_answer_format_rejection_is_final_and_never_published():
    raw_answer = "ここで x^m∈I, x∈√(IJ) となります。"
    engine, transport = runtime(
        [
            READY,
            decision(answer=raw_answer),
            {"approved": False, "rationale": "Visible formulas are not TeX."},
        ]
    )

    result = engine.answer(REQUEST)

    assert result.outcome == "failed"
    assert result.answer is None
    assert result.error_code == "proof_reuse_answer_review_failed"
    assert result.private_evidence["answer_qa"]["approved"] is False
    assert len(transport.calls) == 3
    assert "Reject undelimited math or raw Unicode" in transport.calls[-1]["input"]


def test_unmetered_independent_review_failure_cannot_publish_answer():
    engine, transport = runtime([READY, decision(), 500])

    result = engine.answer(REQUEST)

    assert result.outcome == "failed"
    assert result.answer is None
    assert result.error_code == "proof_reuse_provider_unavailable"
    assert len(transport.calls) == 3


def test_missing_domain_asks_before_retrieval_and_preserves_question_context():
    missing = dict(
        READY,
        action="needs_input",
        question={"text": "nは自然数ですか？", "options": ["自然数", "実数"]},
    )
    engine, transport = runtime([missing])
    result = engine.answer(dict(REQUEST, statement="x^nは連続？"))
    assert result.outcome == "needs_input" and result.question["id"]
    assert engine.catalog.calls == [] and len(transport.calls) == 1
    engine, transport = runtime([READY, decision()])
    request = dict(
        REQUEST,
        context_turns=[
            {
                "question_id": result.question["id"],
                "question": "nは自然数ですか？",
                "answer": "自然数",
            }
        ],
    )
    assert engine.answer(request).outcome == "answered"
    assert all("自然数" in call["input"] for call in transport.calls)


def test_uncertainty_uses_terra_once_and_never_sol():
    engine, transport = runtime([READY, decision(action="uncertain"), decision()])
    assert engine.answer(REQUEST).outcome == "answered"
    assert [c["model"] for c in transport.calls] == [
        "gpt-6-luna", "gpt-6-luna", "gpt-5.6-terra", "gpt-6-luna"
    ]


@pytest.mark.parametrize("status", [429, 500, 401])
def test_provider_failure_never_triggers_escalation_or_retries(status):
    engine, transport = runtime([READY, status])
    result = engine.answer(REQUEST)
    assert result.outcome == "failed" and result.error_code == "proof_reuse_provider_unavailable"
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"source_ids": ["invented"]},
        {"dependency_cycle": True},
        {"supporting_proof": ""},
        {"substitutions": [{"variable": "n", "term_openmath_xml": integer(-1)}]},
        {"unknown": True},
    ],
)
def test_bad_source_cycle_incomplete_sketch_and_invalid_substitution_do_not_answer(change):
    engine, transport = runtime([READY, decision(**change)])
    assert engine.answer(REQUEST).outcome == "failed"
    assert len(transport.calls) == 2


def test_catalog_failure_is_not_treated_as_empty_catalog():
    engine, transport = runtime(
        [READY],
        CatalogBoundary(
            error=ProofReuseError("proof_reuse_catalog_unavailable"),
        ),
    )
    assert engine.answer(REQUEST).error_code == "proof_reuse_catalog_unavailable"
    assert len(transport.calls) == 1


def test_derive_without_catalog_does_not_invent_sources():
    class EmptyCatalog(CatalogBoundary):
        def retrieve(self, *args, **kwargs):
            return DraftRetrievalResult("no_match", "", (), {})

    engine, _ = runtime(
        [READY, decision(mode="derive", source_ids=[], substitutions=[])], EmptyCatalog()
    )
    assert engine.answer(REQUEST).answer["sources"] == []


def test_clarifications_are_bounded_and_do_not_loop_forever():
    missing = dict(READY, action="needs_input", question={"text": "Which domain?", "options": []})
    engine, _ = runtime([missing])
    turns = [{"question_id": str(i), "question": "Domain?", "answer": "Real"} for i in range(5)]
    assert engine.answer(dict(REQUEST, context_turns=turns)).outcome == "failed"


def test_source_revision_changes_with_catalog_content():
    engine, _ = runtime([READY, decision()])
    first = engine.answer(REQUEST).answer["sources"][0]["revision"]
    changed = CatalogBoundary(source=universal(POWER).replace('name="x"', 'name="y"'))
    engine, _ = runtime([READY, decision()], changed)
    second = engine.answer(REQUEST).answer["sources"][0]["revision"]
    assert first != second


@pytest.mark.parametrize(
    "change",
    [
        {"action": []},
        {"question": {"text": "Domain?", "options": [], "extra": "bad"}},
        {"source_ids": [{}]},
        {"premises": [{"statement": "P", "justification": []}]},
    ],
)
def test_malformed_closed_response_fails_without_worker_exception_or_terra(change):
    engine, provider = runtime([READY, decision(**change)])
    assert engine.answer(REQUEST).outcome == "failed"
    assert len(provider.calls) == 2


def test_injected_catalog_instructions_remain_untrusted_data_in_prompt():
    engine, provider = runtime([READY, decision()])
    engine.answer(REQUEST)
    prompt = provider.calls[1]["input"]
    assert "untrusted DATA" in prompt and "never invent a catalog citation" in prompt
    assert "NOT established theorems" in prompt and "No Lean compiler has run" in prompt


def test_preflight_schema_lists_only_configured_profiles_and_allows_no_catalog():
    class UnconfiguredCatalog(CatalogBoundary):
        profiles = ()

        def retrieve(self, statement, profile_id, *, deadline):
            assert profile_id is None
            return DraftRetrievalResult("no_match", "", (), {"reason": "no_catalog_profile"})

    engine, provider = runtime(
        [dict(READY, profile_id=None), decision(mode="derive", source_ids=[], substitutions=[])],
        UnconfiguredCatalog(),
    )
    assert engine.answer(REQUEST).outcome == "answered"
    profile_schema = provider.calls[0]["text"]["format"]["schema"]["properties"]["profile_id"]
    assert profile_schema["enum"] == [None]


def test_unconfigured_profile_response_is_preserved_for_diagnosis_and_never_retrieved():
    engine, provider = runtime([dict(READY, profile_id="not_configured")])
    result = engine.answer(REQUEST)
    assert result.outcome == "failed" and result.error_code == "proof_reuse_invalid_response"
    assert result.private_evidence["preflight"]["profile_id"] == "not_configured"
    assert engine.catalog.calls == [] and len(provider.calls) == 1


def test_only_local_query_invalid_allows_bounded_source_free_answer():
    engine, provider = runtime(
        [READY, decision(mode="derive", source_ids=[], substitutions=[])],
        CatalogBoundary(
            error=ProofReuseError("proof_reuse_query_invalid", details={"failure_code": "tree"})
        ),
    )
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    assert result.answer["sources"] == []
    assert result.private_evidence["retrieval_status"] == "query_invalid"
    assert len(provider.calls) == 3


@pytest.mark.parametrize(
    "response",
    [
        decision(),
        decision(mode="direct", source_ids=[], substitutions=[]),
        decision(
            mode="derive",
            source_ids=[],
            substitutions=[{"variable": "n", "term_openmath_xml": integer(2)}],
        ),
    ],
)
def test_query_invalid_cannot_claim_source_or_substitution(response):
    engine, _ = runtime(
        [READY, response], CatalogBoundary(error=ProofReuseError("proof_reuse_query_invalid"))
    )
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.answer is None


def test_explicit_source_requirement_cannot_be_satisfied_by_query_fallback():
    engine, provider = runtime(
        [dict(READY, requires_catalog_source=True)],
        CatalogBoundary(error=ProofReuseError("proof_reuse_query_invalid")),
    )
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.error_code == "proof_reuse_unsupported"
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "code",
    ["proof_reuse_catalog_invalid", "proof_reuse_catalog_unavailable", "proof_reuse_deadline"],
)
def test_nonlocal_failure_never_uses_query_fallback(code):
    engine, provider = runtime([READY], CatalogBoundary(error=ProofReuseError(code)))
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.error_code == code
    assert len(provider.calls) == 1


def test_search_for_general_theorem_is_not_a_missing_user_premise():
    request = dict(
        REQUEST,
        statement=(
            "Draft検索で得られた適用可能な一般定理を使い、自然数のパラメータ n を 2 に"
            "具体化して、実数全体で関数 x↦x² が連続であることを示してください。"
            "一般定理の根拠も確認し、証明が循環しないようにしてください。"
        ),
    )
    engine, provider = runtime([dict(READY, requires_catalog_source=True), decision()])
    result = engine.answer(request)
    assert result.outcome == "answered"
    assert engine.catalog.calls
    assert "Do not ask the user to supply sources" in provider.calls[0]["input"]
    assert "not missing premises" in provider.calls[0]["input"]
    assert request["statement"] in provider.calls[0]["input"]


@pytest.mark.parametrize("display", [r"\[x^2-x^2=0\]", "$$\nx^2-x^2=0\n$$"])
def test_display_math_is_preserved_through_independent_review(display):
    answer = "任意の $x$ に対して\n" + display
    engine, transport = runtime([READY, decision(answer=answer)])
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    assert result.answer["text"] == answer
    qa_prompt = transport.calls[-1]["input"]
    qa_data = json.loads(qa_prompt.split("DATA:\n", 1)[1])
    assert qa_data["answer"] == answer
    assert "All four are valid" in qa_prompt
    assert result.private_evidence["answer_qa"]["approved"] is True


def test_concrete_lambda_catalog_uses_direct_reconstruction_with_exact_original_revision():
    import hashlib

    import rfc8785

    from tests.unit.test_proof_instantiation import document

    source = document(POWER.replace('<OMV name="n"/>', '<OMI>2</OMI>'))
    # CatalogBoundary deliberately labels this source as a general theorem. The
    # structural restriction must follow its actual XML rather than that label.
    engine, transport = runtime(
        [READY, decision(mode="direct", substitutions=[])], CatalogBoundary(source)
    )
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    generated = transport.calls[1]
    schema = generated["text"]["format"]["schema"]
    assert "instantiate" not in schema["properties"]["mode"]["enum"]
    assert schema["properties"]["substitutions"]["maxItems"] == 0
    data = json.loads(generated["input"].split("DATA:\n", 1)[1])
    candidate = data["candidates"][0]
    assert candidate["instantiable_parameters"] == []
    original = {key: candidate[key] for key in
                ("draft_id", "statement", "openmath_xml", "proof_strategy", "sketch_steps")}
    assert result.answer["sources"][0]["revision"] == (
        "sha256:" + hashlib.sha256(rfc8785.dumps(original)).hexdigest()
    )
    assert result.private_evidence["answer_qa"]["approved"] is True
    assert "instantiation" not in result.private_evidence
    assert len(transport.calls) == 3


def test_provider_ignoring_concrete_source_schema_still_cannot_instantiate_lambda():
    from tests.unit.test_proof_instantiation import document

    source = document(POWER.replace('<OMV name="n"/>', '<OMI>2</OMI>'))
    engine, transport = runtime(
        [READY, decision(substitutions=[{"variable": "x", "term_openmath_xml": integer(2)}])],
        CatalogBoundary(source),
    )
    result = engine.answer(REQUEST)
    assert result.outcome == "failed"
    assert result.error_code == "proof_reuse_invalid_instantiation"
    assert result.answer is None
    assert len(transport.calls) == 2


def test_general_numeric_theorem_keeps_real_instantiation_available():
    engine, transport = runtime([READY, decision()])
    result = engine.answer(REQUEST)
    assert result.outcome == "answered"
    schema = transport.calls[1]["text"]["format"]["schema"]
    assert "instantiate" in schema["properties"]["mode"]["enum"]
    assert schema["properties"]["substitutions"]["items"]["properties"]["variable"]["enum"] == ["n"]
    assert result.private_evidence["instantiation"]["substitutions"][0]["domain"] == "Nat"
