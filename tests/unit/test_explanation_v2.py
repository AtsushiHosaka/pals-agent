"""Explanation v2 (Draft-aware, answer-first) and the unreviewed-explanation fallback."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from pals_agent import explanation_fallback, explanation_v2
from pals_agent.api_client import PalsApiError
from pals_agent.explanation_fallback import (
    coarse_references,
    deliver_unreviewed_explanation,
    minimal_explanation_content,
)
from pals_agent.explanation_v2 import (
    ExplanationReviewerV2,
    ExplanationWriterV2,
    derive_references,
    draft_text_from_proof_job,
    explanation_prompt_v2,
    parse_defects_text,
    parse_review_verdict,
    select_v2,
)
from pals_agent.explanations import (
    ExplanationDeadlineExceeded,
    ExplanationGenerationError,
    ProofOutputReviewError,
    _explanation_prompt,
    _parse_explanation,
)
from tests.unit.test_worker_claim_spec import (
    LEAN_CODE,
    ClaimApi,
    FakeClock,
    RecordingExplainer,
    RecordingOutputReviewer,
    _envelope,
    _worker,
)

LEAN = "import Mathlib\n\ntheorem t (n : Nat) : n + 0 = n := by\n  simp"
STATEMENT_PROVE = "Prove that n + 0 = n for every natural number n."
STATEMENT_COMPUTE = "Compute the sum of 1 to 10."
DRAFT = "Plan: n + 0 reduces to n by the definition of addition."


def good_payload(*, overview: str | None = None) -> dict[str, Any]:
    return {
        "overview": overview
        or "For every natural number $n$, $n+0=n$. Addition by zero is trivial.",
        "sections": [
            {
                "id": "zero-step",
                "title": "label",
                "summary": "Adding zero leaves $n$ unchanged, by the definition of addition.",
                "references": [{"start_line": 3, "end_line": 4}],
            }
        ],
        "conclusion": "So $n$ plus zero is $n$.",
    }


class ScriptedClient:
    def __init__(self, *responses: str, schema: bool = True) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        if schema:
            self.generate = self._generate_schema  # type: ignore[method-assign]
        else:
            self.generate = self._generate_plain  # type: ignore[method-assign]

    def _next(self) -> str:
        if not self.responses:
            raise AssertionError("unexpected model call")
        return self.responses.pop(0)

    def _generate_schema(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append({"model": model, "prompt": prompt, "schema": response_schema})
        return self._next()

    def _generate_plain(
        self, *, model: str, prompt: str, timeout_seconds: float | None = None
    ) -> str:
        self.calls.append({"model": model, "prompt": prompt, "schema": None})
        return self._next()


def writer(client: ScriptedClient) -> ExplanationWriterV2:
    return ExplanationWriterV2(client=client, model="m", provider="p")


def write(client: ScriptedClient, statement: str = STATEMENT_PROVE, language: str = "en") -> Any:
    return writer(client).explain(
        theorem_statement=statement, lean_code=LEAN, draft_text=DRAFT, language=language
    )


# ---- flag off: current behaviour is byte-identical ---------------------------------------


def test_flag_off_selects_nothing_and_touches_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALS_EXPLANATION_V2_ENABLED", raising=False)
    selected, reason = select_v2(
        explainer=object(),
        reviewer=object(),
        draft_text=DRAFT,
        theorem_statement="s",
        lean_code=LEAN,
        language="en",
        deadline=1.0,
        timeout_seconds=1.0,
    )
    assert selected is None and reason == "flag_off"


def test_v1_prompt_is_byte_identical_to_origin_main() -> None:
    # explanations.py is untouched by this change (git diff origin/main is empty for it); the
    # digest pins the v1 prompt so any later edit to it is a visible, deliberate change.
    prompt = _explanation_prompt(theorem_statement=STATEMENT_PROVE, lean_code=LEAN, language="en")
    assert hashlib.sha256(prompt.encode()).hexdigest() == V1_PROMPT_SHA256


V1_PROMPT_SHA256 = "47acb3d5e1900e88a4a9b9ca618afe2e2693c0907549c1849ac1de0bf05c9354"


def test_worker_flag_off_uses_v1_writer_and_reviewer_even_with_a_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALS_EXPLANATION_V2_ENABLED", raising=False)
    monkeypatch.delenv("PALS_EXPLANATION_FALLBACK_ENABLED", raising=False)
    api = ClaimApi(
        claim_response=_envelope("acquired", 600_000), proof_job_response=job(draft=True)
    )
    explainer, reviewer = RecordingExplainer(), RecordingOutputReviewer()
    assert run_retry(_worker(api, explainer, FakeClock(), output_reviewer=reviewer))
    assert len(explainer.explain_calls) == 1 and len(reviewer.explanation_calls) == 1
    assert "draft_text" not in explainer.explain_calls[0]
    assert api.explanation_updates[-1]["state"] == "completed"


# ---- Draft plumbing ----------------------------------------------------------------------


def job(*, draft: bool, state: str = "verified") -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": "proof-1",
        "state": state,
        "theorem_statement": "True を証明せよ",
        "lean_code": LEAN_CODE,
        "output_language": "ja",
        "context": {},
    }
    if draft:
        value["status_context"] = {"attempt_evidence": {"generated": {"draft": {"text": DRAFT}}}}
    return value


def run_retry(worker: Any) -> bool:
    return bool(
        worker.process_explanation_retry(
            "proof-1",
            retry_id="22222222-2222-4222-8222-222222222222",
            claim_id="11111111-1111-4111-8111-111111111111",
            extend_visibility=lambda _: None,
        )
    )


def test_draft_text_extraction_and_absence() -> None:
    assert draft_text_from_proof_job(job(draft=True)) == DRAFT
    assert draft_text_from_proof_job(job(draft=False)) is None
    assert draft_text_from_proof_job(None) is None
    assert (
        draft_text_from_proof_job(
            {"status_context": {"attempt_evidence": {"generated": {"draft": None}}}}
        )
        is None
    )


def test_select_v2_records_why_it_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALS_EXPLANATION_V2_ENABLED", "true")
    common = dict(
        theorem_statement="s", lean_code=LEAN, language="en", deadline=1.0, timeout_seconds=1.0
    )
    assert select_v2(explainer=object(), reviewer=object(), draft_text=None, **common) == (
        None,
        "draft_unavailable",
    )
    assert select_v2(explainer=object(), reviewer=object(), draft_text=DRAFT, **common) == (
        None,
        "client_unavailable",
    )
    explainer = SimpleNamespace(client=ScriptedClient(), model="m", provider="p")
    reviewer = SimpleNamespace(client=ScriptedClient(), model="r", provider="p")
    selected, reason = select_v2(explainer=explainer, reviewer=reviewer, draft_text=DRAFT, **common)
    assert selected is not None and reason is None


def test_worker_flag_on_without_draft_uses_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALS_EXPLANATION_V2_ENABLED", "true")
    api = ClaimApi(
        claim_response=_envelope("acquired", 600_000), proof_job_response=job(draft=False)
    )
    explainer = RecordingExplainer()
    assert run_retry(_worker(api, explainer, FakeClock()))
    assert len(explainer.explain_calls) == 1


# ---- excerpts are derived in code ---------------------------------------------------------


def test_excerpt_is_computed_from_the_line_table() -> None:
    completed = derive_references(LEAN, good_payload())
    reference = completed["sections"][0]["references"][0]
    assert reference == {
        "start_line": 3,
        "end_line": 4,
        "excerpt": "theorem t (n : Nat) : n + 0 = n := by\n  simp",
    }


@pytest.mark.parametrize(
    "reference",
    [
        {"start_line": 0, "end_line": 1},
        {"start_line": 3, "end_line": 2},
        {"start_line": 1, "end_line": 99},
        {"start_line": 2, "end_line": 2},
        {"start_line": "3", "end_line": 4},
    ],
)
def test_invalid_reference_ranges_are_rejected(reference: dict[str, Any]) -> None:
    payload = good_payload()
    payload["sections"][0]["references"] = [reference]
    with pytest.raises((ValueError, TypeError)):
        derive_references(LEAN, payload)


def test_writer_accepts_line_numbers_only_and_sends_lean_once_with_draft() -> None:
    client = ScriptedClient(json.dumps(good_payload()))
    result = write(client)
    assert result.sections[0].references[0].excerpt.endswith("  simp")
    prompt = client.calls[0]["prompt"]
    assert DRAFT in prompt and prompt.count("theorem t (n : Nat)") == 1
    assert "```lean" not in prompt and '"text":' not in prompt
    assert client.calls[0]["schema"] is not None and len(client.calls) == 1


def test_writer_keeps_plain_generate_for_clients_without_schema_mode() -> None:
    client = ScriptedClient(json.dumps(good_payload()), schema=False)
    write(client)
    assert client.calls[0]["schema"] is None


def test_exact_copy_failures_cannot_occur_but_bad_lines_retry_then_fail() -> None:
    bad = good_payload()
    bad["sections"][0]["references"] = [{"start_line": 1, "end_line": 99}]
    client = ScriptedClient(json.dumps(bad), json.dumps(bad), json.dumps(bad))
    with pytest.raises(ExplanationGenerationError) as error:
        write(client)
    assert error.value.attempt_failures == ("reference_range",) * 3


# ---- deterministic gates on v2 output -----------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "language", "statement"),
    [
        (lambda p: p.update(conclusion="The `simp` step finishes it."), "en", STATEMENT_PROVE),
        (
            lambda p: p.update(overview="Use Nat.add_zero for $n+0=n$ directly."),
            "en",
            STATEMENT_PROVE,
        ),
        (lambda p: p.update(overview="これは日本語で、$n+0=n$ です。"), "en", STATEMENT_PROVE),
        (
            lambda p: p.update(overview="Everything is true. We prove $n+0=n$ now."),
            "ja",
            STATEMENT_PROVE,
        ),
        (
            lambda p: p.update(overview="The sum is fifty-five by pairing terms."),
            "en",
            STATEMENT_COMPUTE,
        ),
        (
            lambda p: p.update(conclusion="Holds for $n$ since \\varepsilon is small."),
            "en",
            STATEMENT_PROVE,
        ),
        (lambda p: p.update(conclusion="Broken $n+0 delimiter."), "en", STATEMENT_PROVE),
    ],
)
def test_gates_reject_bad_v2_output(mutate: Any, language: str, statement: str) -> None:
    payload = good_payload()
    mutate(payload)
    client = ScriptedClient(*[json.dumps(payload)] * 3)
    with pytest.raises(ExplanationGenerationError):
        write(client, statement=statement, language=language)


def test_computation_requires_the_answer_in_the_overview() -> None:
    ok = good_payload(overview="The sum is $\\sum_{k=1}^{10}k=55$; pair first and last terms.")
    assert write(ScriptedClient(json.dumps(ok)), statement=STATEMENT_COMPUTE).overview.startswith(
        "The sum is"
    )


def test_japanese_output_passes_language_gate() -> None:
    ja = good_payload(overview="任意の自然数 $n$ について $n+0=n$ です。零を足しても変わりません。")
    ja["sections"][0]["summary"] = "零を足すと $n$ のままです。加法の定義から従います。"
    ja["conclusion"] = "したがって $n+0=n$ が成り立ちます。"
    assert write(ScriptedClient(json.dumps(ja)), language="ja").overview.startswith("任意")


def test_revision_prompt_carries_the_specific_defects() -> None:
    defects = json.dumps(
        {
            "defects": [{"kind": "unjustified_leap", "where": "zero-step", "problem": "no reason"}],
            "summary": "s",
        }
    )
    client = ScriptedClient(json.dumps(good_payload()))
    writer(client).explain(
        theorem_statement=STATEMENT_PROVE,
        lean_code=LEAN,
        draft_text=DRAFT,
        language="en",
        review_feedback={"rationale": defects, "previous_candidate": "x"},
    )
    assert (
        "unjustified_leap" in client.calls[0]["prompt"] and "no reason" in client.calls[0]["prompt"]
    )


def test_prompt_is_a_positive_specification_with_one_exemplar_per_type() -> None:
    for language, marker in (
        ("en", "Every even number"),
        ("ja", "偶数の平方"),
        ("zh-Hant", "偶数的平方"),
    ):
        prompt = explanation_prompt_v2(
            theorem_statement="s", lean_code=LEAN, draft_text=DRAFT, language=language
        )
        assert prompt.count(marker) == 1
        for tag in ("[proof]", "[computation]", "[counterexample]"):
            assert prompt.count(tag) == 1
        assert (
            "Begin with the proof itself" not in prompt and "Do not first summarize" not in prompt
        )
    assert "Traditional Chinese" in prompt


# ---- defect-list review -------------------------------------------------------------------

DEFECT = {"kind": "missing_answer", "where": "overview", "problem": "states no value"}


def test_review_verdict_parsing() -> None:
    ok = parse_review_verdict({"approved": True, "defects": [], "summary": "fine"})
    assert ok.approved and ok.defects == ()
    rejected = parse_review_verdict({"approved": False, "defects": [DEFECT], "summary": "no"})
    assert rejected.defects[0]["kind"] == "missing_answer"
    for bad in (
        {"approved": True, "defects": [DEFECT], "summary": "x"},
        {"approved": False, "defects": [], "summary": "x"},
        {"approved": False, "defects": [{**DEFECT, "kind": "vibes"}], "summary": "x"},
        {"approved": False, "defects": [DEFECT]},
        {"approved": "yes", "defects": [], "summary": "x"},
        {"approved": False, "defects": [{"kind": "other"}], "summary": "x"},
    ):
        with pytest.raises(ValueError):
            parse_review_verdict(bad)


def reviewer(client: ScriptedClient) -> ExplanationReviewerV2:
    return ExplanationReviewerV2(client=client, model="r", provider="p", draft_text=DRAFT)


def review(client: ScriptedClient) -> Any:
    explanation = write(ScriptedClient(json.dumps(good_payload())))
    return reviewer(client).review_explanation(
        theorem_statement=STATEMENT_PROVE, lean_code=LEAN, explanation=explanation, language="en"
    )


def test_reviewer_approves_and_returns_review_record() -> None:
    record = review(ScriptedClient(json.dumps({"approved": True, "defects": [], "summary": "ok"})))
    assert record.kind == "explanation" and record.rationale == "ok" and record.session_id


def test_reviewer_rejection_carries_defects_for_the_revision() -> None:
    client = ScriptedClient(json.dumps({"approved": False, "defects": [DEFECT], "summary": "no"}))
    with pytest.raises(ProofOutputReviewError) as error:
        review(client)
    assert error.value.category == "rejected"
    assert parse_defects_text(error.value.rationale) == [DEFECT]
    assert DRAFT in client.calls[0]["prompt"]


def test_reviewer_schema_failure_is_not_a_rejection() -> None:
    client = ScriptedClient("not json", "still not json")
    with pytest.raises(ProofOutputReviewError) as error:
        review(client)
    assert error.value.category == "schema"


# ---- worker integration: v2 flag ----------------------------------------------------------


def v2_worker(
    monkeypatch: pytest.MonkeyPatch,
    writer_client: ScriptedClient,
    reviewer_client: ScriptedClient,
    api: ClaimApi,
    **kw: Any,
) -> Any:
    monkeypatch.setenv("PALS_EXPLANATION_V2_ENABLED", "true")
    explainer = SimpleNamespace(client=writer_client, model="m", provider="p", max_attempts=3)
    qa = SimpleNamespace(client=reviewer_client, model="r", provider="p")
    return _worker(api, explainer, FakeClock(), output_reviewer=qa)  # type: ignore[arg-type]


def ja_payload() -> str:
    return json.dumps(
        {
            "overview": "$True$ が成り立ちます。自明な命題です。",
            "sections": [
                {
                    "id": "s",
                    "title": "t",
                    "summary": "目標は自明なので、そのまま閉じられます。",
                    "references": [{"start_line": 2, "end_line": 2}],
                }
            ],
            "conclusion": "したがって主張は成り立ちます。",
        },
        ensure_ascii=False,
    )


APPROVE = json.dumps({"approved": True, "defects": [], "summary": "ok"})
REJECT = json.dumps({"approved": False, "defects": [DEFECT], "summary": "no"})


def test_worker_v2_revises_once_from_defects_then_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = ClaimApi(
        claim_response=_envelope("acquired", 600_000), proof_job_response=job(draft=True)
    )
    writer_client = ScriptedClient(ja_payload(), ja_payload().replace("自明な命題", "自明な主張"))
    reviewer_client = ScriptedClient(REJECT, APPROVE)
    assert run_retry(v2_worker(monkeypatch, writer_client, reviewer_client, api))
    assert len(writer_client.calls) == 2 and "states no value" in writer_client.calls[1]["prompt"]
    completed = api.explanation_updates[-1]
    assert completed["state"] == "completed"
    assert completed["content"]["sections"][0]["references"][0]["excerpt"] == "  trivial"


# ---- fallback (B) -------------------------------------------------------------------------


class FallbackApi(ClaimApi):
    def __init__(self, *args: Any, accept: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.accept = accept
        self.unreviewed: list[dict[str, Any]] = []

    def upsert_unreviewed_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        self.unreviewed.append(kwargs)
        if not self.accept:
            raise PalsApiError("rejected", status_code=422, error_code="validation_error")
        return _envelope("terminal", None)


def fallback_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    explainer: Any,
    reviewer: Any,
    flag: bool = True,
    accept: bool = True,
) -> FallbackApi:
    if flag:
        monkeypatch.setenv("PALS_EXPLANATION_FALLBACK_ENABLED", "true")
    else:
        monkeypatch.delenv("PALS_EXPLANATION_FALLBACK_ENABLED", raising=False)
    monkeypatch.delenv("PALS_EXPLANATION_V2_ENABLED", raising=False)
    api = FallbackApi(
        claim_response=_envelope("acquired", 600_000),
        proof_job_response=job(draft=False),
        accept=accept,
    )
    assert run_retry(_worker(api, explainer, FakeClock(), output_reviewer=reviewer))
    return api


def failed_writes(api: ClaimApi) -> list[dict[str, Any]]:
    return [u for u in api.explanation_updates if u["state"] == "failed"]


def test_fallback_on_schema_failure_delivers_deterministic_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = fallback_run(
        monkeypatch,
        explainer=RecordingExplainer(error=ExplanationGenerationError("bad")),
        reviewer=RecordingOutputReviewer(),
    )
    sent = api.unreviewed[0]
    assert sent["unreviewed_reason"] == "generation_failed" and not failed_writes(api)
    assert sent["content"]["model"] == "deterministic-fallback"
    assert sent["content"]["sections"][0]["references"][0]["excerpt"] == LEAN_CODE


def test_fallback_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    api = fallback_run(
        monkeypatch,
        explainer=RecordingExplainer(error=ExplanationDeadlineExceeded("late")),
        reviewer=RecordingOutputReviewer(),
    )
    assert api.unreviewed[0]["unreviewed_reason"] == "timeout"


def test_fallback_after_qa_rejects_twice_sends_the_best_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Rejecting(RecordingOutputReviewer):
        def review_explanation(self, **kwargs: Any) -> Any:
            self.explanation_calls.append(kwargs)
            raise ProofOutputReviewError("no", category="rejected", rationale="bad")

    class Varying(RecordingExplainer):
        def explain(self, **kwargs: Any) -> Any:
            result = super().explain(**kwargs)
            from dataclasses import replace

            return replace(result, overview=f"概要 {len(self.explain_calls)}")

    api = fallback_run(monkeypatch, explainer=Varying(), reviewer=Rejecting())
    sent = api.unreviewed[0]
    assert sent["unreviewed_reason"] == "qa_rejected_or_unavailable"
    assert sent["content"]["overview"] == "概要 2" and sent["private_review_failures"]


def test_fallback_not_accepted_by_api_records_the_failure_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = fallback_run(
        monkeypatch,
        explainer=RecordingExplainer(error=ExplanationGenerationError("bad")),
        reviewer=RecordingOutputReviewer(),
        accept=False,
    )
    assert len(api.unreviewed) == 1 and len(failed_writes(api)) == 1


def test_fallback_flag_off_records_failure_without_trying_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = fallback_run(
        monkeypatch,
        explainer=RecordingExplainer(error=ExplanationGenerationError("bad")),
        reviewer=RecordingOutputReviewer(),
        flag=False,
    )
    assert api.unreviewed == [] and len(failed_writes(api)) == 1


def test_fallback_never_sends_review_evidence() -> None:
    sent: dict[str, Any] = {}

    class Api:
        def upsert_unreviewed_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
            sent.update(kwargs)
            return {}

    deliver_unreviewed_explanation(
        Api(),
        proof_job_id="p",
        claim_id="c",
        theorem_statement="s",
        lean_code=LEAN,
        language="en",
        reason="timeout",
        candidate_content=None,
        private_review_failures=None,
    )
    assert "review_evidence" not in sent and sent["unreviewed_reason"] == "timeout"


@pytest.mark.parametrize("language", ["en", "ja", "zh-Hans", "zh-Hant"])
def test_minimal_explanation_satisfies_the_stored_contract(language: str) -> None:
    content = minimal_explanation_content(
        theorem_statement="x " * 500, lean_code=LEAN, language=language
    )
    overview, sections, conclusion = _parse_explanation(content, LEAN, language=language)
    assert len(overview) <= 600 and len(sections[0].summary) <= 800 and conclusion
    assert sections[0].references[0].excerpt == LEAN


def test_coarse_references_chunk_and_cap() -> None:
    long = "\n".join(f"line {i}" if i % 45 else "" for i in range(1, 2000))
    references = coarse_references(long)
    assert 1 <= len(references) <= 20
    for reference in references:
        lines = long.splitlines()[reference["start_line"] - 1 : reference["end_line"]]
        assert reference["excerpt"] == "\n".join(lines)
    with pytest.raises(ValueError):
        coarse_references("\n\n")


def test_flag_helpers_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALS_EXPLANATION_V2_ENABLED", raising=False)
    monkeypatch.delenv("PALS_EXPLANATION_FALLBACK_ENABLED", raising=False)
    assert not explanation_v2.explanation_v2_enabled()
    assert not explanation_fallback.explanation_fallback_enabled()
