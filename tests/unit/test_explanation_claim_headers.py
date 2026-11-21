"""Multi-line local `have` claim headers must be cited by one section (pals#232).

A section that cites only the last tactic of a multi-line `have` leaves the line that states
the claim without an explanation in the learner's Lean panel. New generations are checked and
retried; saved explanations are read as before.
"""

import json
import uuid

import pytest

from pals_agent.explanations import (
    ExplanationGenerationError,
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    LeanProofExplainer,
    ProofExplanation,
    ProofOutputReviewError,
    _explanation_prompt,
    _local_claim_headers,
    _parse_explanation,
    _require_local_claim_headers,
    _validation_failure_reason,
)

LEAN = """import Mathlib

theorem t (a b : ℕ) (h : a = b) : b = a := by
  have hab :
      a = b := by
    exact h
  have hba : b = a :=
    hab.symm
  exact hba"""


def _payload(*ranges: tuple[int, int]) -> str:
    lines = LEAN.split("\n")
    references = [
        {"start_line": a, "end_line": b, "excerpt": "\n".join(lines[a - 1 : b])} for a, b in ranges
    ]
    return json.dumps(
        {
            "overview": "自然数 a と b が等しいと仮定します。",
            "sections": [
                {
                    "id": "step",
                    "title": "等式の向きを入れ替える",
                    "summary": "仮定から a と b が等しいことを取り出し、左右を入れ替えます。",
                    "references": references,
                }
            ],
            "conclusion": "したがって b と a は等しくなります。",
        },
        ensure_ascii=False,
    )


class _Client:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        _ = (model, timeout_seconds)
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _explainer(*responses: str) -> tuple[LeanProofExplainer, _Client]:
    client = _Client(*responses)
    return LeanProofExplainer(client=client, model="m", provider="p"), client


def _explain(explainer: LeanProofExplainer) -> ProofExplanation:
    return explainer.explain(theorem_statement="a = b ならば b = a", lean_code=LEAN, verified=True)


def test_only_multi_line_have_with_an_assignment_is_a_claim_header() -> None:
    # `have hab :` and its type end on line 5; `have hba` states its claim on one line.
    assert _local_claim_headers(LEAN) == [(4, 5)]
    plain = "theorem t : True := by\n  have h : True := trivial\n  exact h"
    assert _local_claim_headers(plain) == []


def test_headers_ignore_comments_strings_and_following_haves() -> None:
    source = (
        "theorem t : True := by\n"
        "  -- have fake :\n"
        "  --   True := by\n"
        '  have s : "have x :\n'
        '    y" = "" := by\n'
        "    simp\n"
        "  have first :\n"
        "  have second :\n"
        "      True := by\n"
        "    trivial\n"
        "  trivial"
    )
    # A tactic-style `have first :` without an assignment must not borrow the next have's `:=`.
    assert _local_claim_headers(source) == [(4, 5), (8, 9)]


def test_header_in_one_section_is_required_for_new_generations_only() -> None:
    missing = json.loads(_payload((6, 6), (9, 9)))
    covered = json.loads(_payload((4, 6), (9, 9)))
    with pytest.raises(ValueError, match="local claim header 4-5"):
        _parse_explanation(missing, LEAN, language="ja", require_claim_headers=True)
    _parse_explanation(covered, LEAN, language="ja", require_claim_headers=True)
    # Saved explanations stay readable.
    _parse_explanation(missing, LEAN, language="ja")


def test_a_header_split_across_two_sections_is_not_covered() -> None:
    first = ExplanationSection(
        id="a", title="a", summary="s", references=(LeanLineReference(4, 4, LEAN.split("\n")[3]),)
    )
    second = ExplanationSection(
        id="b",
        title="b",
        summary="s",
        references=(LeanLineReference(5, 6, "\n".join(LEAN.split("\n")[4:6])),),
    )
    with pytest.raises(ValueError, match="local claim header 4-5"):
        _require_local_claim_headers([first, second], LEAN)


def test_missing_header_is_retried_with_the_range_in_the_error() -> None:
    explainer, client = _explainer(_payload((6, 6), (9, 9)), _payload((4, 6), (9, 9)))
    result = _explain(explainer)
    assert len(client.prompts) == 2
    assert "Complete local claim header 4-5 is missing" in client.prompts[1]
    assert result.sections[0].references[0].start_line == 4


def test_a_header_that_stays_missing_fails_with_a_closed_label() -> None:
    explainer, client = _explainer(_payload((6, 6)), _payload((6, 6)))
    with pytest.raises(ExplanationGenerationError) as caught:
        _explain(explainer)
    assert caught.value.attempt_failures == ("reference_header", "reference_header")
    assert len(client.prompts) == 2


def test_validation_label_for_a_missing_header() -> None:
    error = ValueError("Complete local claim header 4-5 is missing from references")
    assert _validation_failure_reason(error) == "reference_header"


def test_prompt_lists_required_headers_only_when_the_source_has_them() -> None:
    with_header = _explanation_prompt(theorem_statement="s", lean_code=LEAN, language="ja")
    assert "Required multi-line local claim header ranges" in with_header
    assert "[[4, 5]]" in with_header
    plain = "theorem t : True := by\n  trivial"
    without = _explanation_prompt(theorem_statement="s", lean_code=plain, language="ja")
    assert "claim header" not in without
    assert without.endswith("Do not trim or normalize spaces.")


def _saved_explanation(*ranges: tuple[int, int]) -> ProofExplanation:
    parsed = json.loads(_payload(*ranges))
    overview, sections, conclusion = _parse_explanation(parsed, LEAN, language="ja")
    return ProofExplanation(
        overview=overview,
        sections=sections,
        conclusion=conclusion,
        model="m",
        provider="p",
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )


def test_reviewer_rejects_a_missing_header_before_any_model_call() -> None:
    client = _Client()
    reviewer = LeanGroundedOutputReviewer(
        client=client,
        model="m",
        provider="p",
        session_id_factory=lambda: uuid.UUID("11111111-1111-4111-8111-111111111111"),
    )
    with pytest.raises(ProofOutputReviewError) as caught:
        reviewer.review_explanation(
            theorem_statement="s",
            lean_code=LEAN,
            explanation=_saved_explanation((6, 6), (9, 9)),
            language="ja",
        )
    assert caught.value.category == "rejected"
    assert "4-5" in caught.value.rationale
    assert client.prompts == []
