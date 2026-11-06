"""The x-squared epsilon-delta requirement is judged by the independent QA, not by regex.

Production incident, 2026-11-06: three mathematically valid explanations were rejected by a
notation-sensitive text gate (`validation:x_squared_epsilon_delta`) and the learner got
`lean_explanation_failed`.  The structural layer (JSON shape, Lean references, length, Lean
vocabulary, repeated final equation) must now accept any notation, and the epsilon-delta
requirement is carried into the independent review rubric.  These tests use stub models only;
whether a real reviewer judges a given proof correctly is not established here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from fractions import Fraction
from typing import Any

import pytest

from pals_agent.explanations import (
    EPSILON_DELTA_CHECK_IDS,
    ExplanationGenerationError,
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    ProofExplanation,
    ProofOutputReviewError,
    _is_x_squared_continuity,
    _parse_explanation,
    _requires_epsilon_delta,
    _validation_failure_reason,
)
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.worker import (
    _generate_reviewed_candidate,
    _public_explanation_content,
    _verified_candidate_matches_statement,
)

SOURCE = "theorem continuous_square : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"
STATEMENT = "x² が連続であることを説明してください。"
REQUIREMENT_MARKER = "EPSILON-DELTA REQUIREMENT"

GOOD_OVERVIEW = "$\\varepsilon>0$ を任意に取り、実数 $a$ を固定します。"
GOOD_SUMMARY = (
    "$\\delta=\\min(1,\\varepsilon/(2|a|+1))>0$ とおきます。$|x-a|<\\delta$ のとき "
    "$|x^2-a^2|=|x-a||x+a|$ で、$|x|<|a|+1$ より $|x+a|<2|a|+1$ なので "
    "$|x^2-a^2|<\\delta(2|a|+1)\\le\\varepsilon$ です。"
)
GOOD_CONCLUSION = "$a$ は任意なので、$x^2$ は実数全体で連続です。"


def _payload(
    overview: str = GOOD_OVERVIEW,
    summary: str = GOOD_SUMMARY,
    conclusion: str = GOOD_CONCLUSION,
) -> dict[str, Any]:
    return {
        "overview": overview,
        "sections": [
            {
                "id": "bound-difference",
                "title": "差の評価",
                "summary": summary,
                "references": [{"start_line": 2, "end_line": 2, "excerpt": "  continuity"}],
            }
        ],
        "conclusion": conclusion,
    }


# Mathematically valid explanations the former regex gate rejected, or could reject, because
# of surface form only.  Each differs from the good proof in notation or phrasing, not content.
VALID_VARIANTS: dict[str, dict[str, Any]] = {
    "good": _payload(),
    "chain_ends_with_equality": _payload(
        summary=GOOD_SUMMARY.replace(
            "$|x^2-a^2|<\\delta(2|a|+1)\\le\\varepsilon$",
            "$|x^2-a^2|<\\delta(2|a|+1)\\le\\frac{\\varepsilon}{2|a|+1}(2|a|+1)=\\varepsilon$",
        )
    ),
    "dfrac": _payload(
        summary=GOOD_SUMMARY.replace("\\varepsilon/(2|a|+1)", "\\dfrac{\\varepsilon}{2|a|+1}")
    ),
    "vert": _payload(summary=GOOD_SUMMARY.replace("|x-a|", "\\vert x-a\\vert")),
    "mathrm_min": _payload(summary=GOOD_SUMMARY.replace("\\min", "\\mathrm{min}")),
    "operatorname_min": _payload(summary=GOOD_SUMMARY.replace("\\min", "\\operatorname{min}")),
    "leqslant": _payload(
        summary=GOOD_SUMMARY.replace("\\le\\varepsilon", "\\leqslant\\varepsilon")
    ),
    "backslash_space": _payload(
        summary=GOOD_SUMMARY.replace("\\le\\varepsilon", "\\ \\le\\ \\varepsilon")
    ),
    "factored_inside_abs": _payload(summary=GOOD_SUMMARY.replace("|x-a||x+a|", "|(x-a)(x+a)|")),
    "delta_positive_in_words": _payload(
        summary=GOOD_SUMMARY.replace(
            "$\\delta=\\min(1,\\varepsilon/(2|a|+1))>0$ とおきます。",
            "$\\delta=\\min(1,\\varepsilon/(2|a|+1))$ とおきます。$\\delta$ は正です。",
        )
    ),
    "point_then_epsilon_opening": _payload(
        overview="実数 $a$ と $\\varepsilon>0$ を任意に取ります。"
    ),
    "epsilon_gt_zero_opening": _payload(
        overview="$\\varepsilon\\gt0$ と実数 $a$ を任意に取ります。"
    ),
    "display_math_opening": _payload(overview="$$ε>0$$ と実数 $a$ を任意に取ります。"),
    "point_renamed": _payload(
        overview="$\\varepsilon>0$ を任意に取り、実数 $b$ を固定します。",
        summary=re.sub(r"(?<![A-Za-z\\])a(?![A-Za-z])", "b", GOOD_SUMMARY).replace("x", "y"),
    ),
    "unicode_symbols": _payload(
        overview="$ε>0$ は任意の正の数、$a$ は実数とします。",
        summary="$δ=\\min(1, ε/(2|a|+1))$ と置く。$|x-a|<δ$ なら $|x^2-a^2|≤δ(2|a|+1)≤ε$ です。",
    ),
    "opening_with_setup_sentence": _payload(
        overview="実数 $a$ を任意に取り、さらに任意の $\\varepsilon>0$ を与えます。"
    ),
}

# Wrong or non-epsilon-delta explanations. The structural layer cannot (and must not try to)
# tell them from valid ones by notation; they reach the independent QA, which rejects them.
WRONG_VARIANTS: dict[str, dict[str, Any]] = {
    "epsilon_plus_one_bound": _payload(
        summary=GOOD_SUMMARY.replace("\\le\\varepsilon$", "\\le\\varepsilon+1$")
    ),
    "delta_ignores_point": _payload(
        summary=GOOD_SUMMARY.replace("\\varepsilon/(2|a|+1)", "\\varepsilon")
    ),
    "delta_without_min": _payload(
        summary=GOOD_SUMMARY.replace("\\min(1,\\varepsilon/(2|a|+1))", "\\varepsilon/(2|a|+1)")
    ),
    "other_function": _payload(
        summary=GOOD_SUMMARY.replace("x^2-a^2", "x^3-a^3").replace("|x+a|", "|x^2+xa+a^2|")
    ),
    "not_epsilon_delta": _payload(
        overview="実数 $a$ を任意に取ります。",
        summary="積の連続性により、$x\\mapsto x\\cdot x$ は点 $a$ で連続です。",
        conclusion="よって $x^2$ は連続です。",
    ),
    "missing_bound": _payload(
        summary=(
            "$\\delta=\\min(1,\\varepsilon/(2|a|+1))>0$ とおけば、"
            "$|x-a|<\\delta$ のとき成り立ちます。"
        )
    ),
}


def _wrong_marker(payload: dict[str, Any]) -> str:
    return str(payload["sections"][0]["summary"])


class StubClient:
    """Deterministic stand-in for an LLM session; records every prompt it sees."""

    def __init__(self, answer: Callable[[str], str]) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        _ = (model, timeout_seconds)
        self.prompts.append(prompt)
        return self.answer(prompt)


CHECKLIST_MARKER = "Checklist (give every id exactly once)"


def _checks_answer(fails: dict[str, tuple[str, str, str]] | None = None, **extra: Any) -> str:
    """A checklist answer: every id ok, except `fails[id] = (status, quote, note)`."""
    fails = fails or {}
    checks = []
    for check_id in EPSILON_DELTA_CHECK_IDS:
        status, quote, note = fails.get(check_id, ("ok", "", ""))
        checks.append({"id": check_id, "status": status, "quote": quote, "note": note})
    return json.dumps({"rationale": "checked", "checks": checks, **extra}, ensure_ascii=False)


def _approve(prompt: str) -> str:
    """Answer in whichever format the prompt asks for: checklist for x², legacy otherwise."""
    if CHECKLIST_MARKER in prompt:
        return _checks_answer()
    return '{"approved": true, "rationale": "valid proof"}'


def _explainer(*payloads: dict[str, Any]) -> tuple[LeanProofExplainer, StubClient]:
    queue = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    client = StubClient(lambda _prompt: queue.pop(0))
    return LeanProofExplainer(client=client, model="m", provider="p"), client


def _reviewer(answer: Callable[[str], str]) -> tuple[LeanGroundedOutputReviewer, StubClient]:
    client = StubClient(answer)
    return LeanGroundedOutputReviewer(client=client, model="m", provider="p"), client


def _explain(
    explainer: LeanProofExplainer, statement: str = STATEMENT, lean_code: str = SOURCE
) -> ProofExplanation:
    return explainer.explain(theorem_statement=statement, lean_code=lean_code, verified=True)


def _explain_with_feedback(
    explainer: LeanProofExplainer, feedback: dict[str, Any] | None
) -> ProofExplanation:
    return explainer.explain(
        theorem_statement=STATEMENT, lean_code=SOURCE, verified=True, review_feedback=feedback
    )


# (i) Surface form never rejects at the structural layer; the candidate reaches QA intact.


@pytest.mark.parametrize("name", sorted(VALID_VARIANTS))
def test_valid_notation_variants_pass_structure_and_are_sent_to_qa(name: str) -> None:
    payload = VALID_VARIANTS[name]
    explainer, generator = _explainer(payload)
    candidate = _explain(explainer)
    assert len(generator.prompts) == 1  # no structural retry, hence no validation: failure

    reviewer, qa = _reviewer(_approve)
    review = reviewer.review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
    )
    assert review.kind == "explanation"
    assert candidate.sections[0].summary in qa.prompts[0]
    assert REQUIREMENT_MARKER in qa.prompts[0]


@pytest.mark.parametrize("name", sorted(WRONG_VARIANTS))
def test_wrong_explanations_are_not_decided_by_regex_but_reach_qa(name: str) -> None:
    explainer, generator = _explainer(WRONG_VARIANTS[name])
    _explain(explainer)
    assert len(generator.prompts) == 1


def test_parse_explanation_has_no_epsilon_delta_switch() -> None:
    with pytest.raises(TypeError):
        _parse_explanation(_payload(), SOURCE, require_epsilon_delta=True)  # type: ignore[call-arg]


def test_retired_x_squared_failure_labels_are_gone() -> None:
    for message in (
        "x-squared continuity explanation must start with the mathematical proof",
        "x-squared continuity explanation must include epsilon-delta reasoning",
    ):
        assert _validation_failure_reason(ValueError(message)) == "other"


# (ii) QA semantics reject bad explanations; the rejection drives the existing correction loop.


# Which checklist element fails for each wrong fixture (the stub quotes a "wrong" passage).
WRONG_CHECK = {
    "epsilon_plus_one_bound": ("final_inequality", "wrong"),
    "delta_ignores_point": ("delta_depends_on_point_and_epsilon", "wrong"),
    "delta_without_min": ("delta_bounded_by_one", "missing"),
    "other_function": ("factorization", "wrong"),
    "not_epsilon_delta": ("epsilon_arbitrary", "missing"),
    "missing_bound": ("sum_bound", "missing"),
}


def _semantic_stub(prompt: str) -> str:
    """Stands in for a mathematician: fails exactly the known-wrong fixtures."""
    for name, payload in WRONG_VARIANTS.items():
        marker = _wrong_marker(payload)
        if marker in prompt:
            check_id, status = WRONG_CHECK[name]
            quote = marker if status == "wrong" else ""
            return _checks_answer({check_id: (status, quote, "wrong delta or bound")})
    return _approve(prompt)


@pytest.mark.parametrize("name", sorted(WRONG_VARIANTS))
def test_qa_rejection_of_wrong_explanation_is_a_rejected_review(name: str) -> None:
    explainer, _ = _explainer(WRONG_VARIANTS[name])
    candidate = _explain(explainer)
    reviewer, qa = _reviewer(_semantic_stub)
    with pytest.raises(ProofOutputReviewError) as raised:
        reviewer.review_explanation(
            theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
        )
    assert raised.value.category == "rejected"
    assert REQUIREMENT_MARKER in qa.prompts[0]


@pytest.mark.parametrize("name", sorted(VALID_VARIANTS))
def test_semantic_stub_approves_every_valid_variant(name: str) -> None:
    explainer, _ = _explainer(VALID_VARIANTS[name])
    candidate = _explain(explainer)
    reviewer, _qa = _reviewer(_semantic_stub)
    reviewer.review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
    )


def test_rejected_wrong_proof_is_corrected_once_with_qa_feedback() -> None:
    explainer, generator = _explainer(
        WRONG_VARIANTS["epsilon_plus_one_bound"], VALID_VARIANTS["chain_ends_with_equality"]
    )
    reviewer, qa = _reviewer(_semantic_stub)
    failures: list[dict[str, Any]] = []

    candidate, review = _generate_reviewed_candidate(
        generate=lambda feedback: _explain_with_feedback(explainer, feedback),
        review=lambda value: reviewer.review_explanation(
            theorem_statement=STATEMENT, lean_code=SOURCE, explanation=value, language="ja"
        ),
        content_of=_public_explanation_content,
        failures=failures,
    )
    assert [failure["category"] for failure in failures] == ["rejected"]
    assert "wrong delta or bound" in generator.prompts[1]
    assert "=\\varepsilon$" in candidate.sections[0].summary
    assert review.kind == "explanation"
    assert len(qa.prompts) == 2


def test_two_wrong_proofs_end_as_review_failure_not_validation_failure() -> None:
    explainer, _ = _explainer(
        WRONG_VARIANTS["epsilon_plus_one_bound"], WRONG_VARIANTS["delta_without_min"]
    )
    reviewer, _qa = _reviewer(_semantic_stub)
    failures: list[dict[str, Any]] = []
    with pytest.raises(ProofOutputReviewError):
        _generate_reviewed_candidate(
            generate=lambda feedback: _explain_with_feedback(explainer, feedback),
            review=lambda value: reviewer.review_explanation(
                theorem_statement=STATEMENT, lean_code=SOURCE, explanation=value, language="ja"
            ),
            content_of=_public_explanation_content,
            failures=failures,
        )
    assert [failure["category"] for failure in failures] == ["rejected", "rejected"]


# The requirement is still stated to the generator and to the reviewer, in notation-free terms.


def test_generation_prompt_still_requires_epsilon_delta() -> None:
    explainer, generator = _explainer(_payload())
    _explain(explainer)
    assert "epsilon-delta explanation" in generator.prompts[0]
    assert "explicit positive delta" in generator.prompts[0]


def test_review_prompt_asks_for_the_checklist_and_ignores_the_approved_flag() -> None:
    explainer, _ = _explainer(_payload())
    candidate = _explain(explainer)
    reviewer, qa = _reviewer(_approve)
    reviewer.review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
    )
    prompt = qa.prompts[0]
    assert REQUIREMENT_MARKER in prompt and CHECKLIST_MARKER in prompt
    assert "`approved` field is ignored" in " ".join(prompt.split())


# (iii) Other theorems are unchanged.


ADD_ZERO_LEAN = "theorem add_zero_nat (n : Nat) : n + 0 = n := by\n  simp"


def test_other_theorems_do_not_get_the_epsilon_delta_requirement() -> None:
    explainer, generator = _explainer(
        {
            "overview": "$n$ を任意の自然数とします。",
            "sections": [
                {
                    "id": "zero",
                    "title": "零の加法",
                    "summary": "$0$ を足しても値は変わりません。",
                    "references": [
                        {"start_line": 1, "end_line": 1, "excerpt": ADD_ZERO_LEAN.splitlines()[0]}
                    ],
                }
            ],
            "conclusion": "よって $n+0=n$ です。",
        }
    )
    statement = "n + 0 = n を示せ"
    candidate = _explain(explainer, statement, ADD_ZERO_LEAN)
    assert "epsilon-delta explanation" not in generator.prompts[0]
    reviewer, qa = _reviewer(_approve)
    reviewer.review_explanation(
        theorem_statement=statement,
        lean_code=ADD_ZERO_LEAN,
        explanation=candidate,
        language="ja",
    )
    assert REQUIREMENT_MARKER not in qa.prompts[0]


# The requirement follows the verified Lean statement, not the learner's wording.


@pytest.mark.parametrize(
    "statement",
    [
        "Why is x^2 continuous?",
        "x^{2} は連続ですか",
        "xの2乗が連続な理由",
        "x の二乗は連続？",
        "ｘ²が連続である理由",
        "Show that x**2 is continuous",
        "x*x is continuous, why?",
        "平方関数が連続になる理由を教えて",
    ],
)
def test_epsilon_delta_requirement_follows_the_lean_statement_not_the_wording(
    statement: str,
) -> None:
    explainer, generator = _explainer(_payload())
    candidate = _explain(explainer, statement)
    assert "epsilon-delta explanation" in generator.prompts[0]
    reviewer, qa = _reviewer(_approve)
    reviewer.review_explanation(
        theorem_statement=statement, lean_code=SOURCE, explanation=candidate, language="ja"
    )
    assert REQUIREMENT_MARKER in qa.prompts[0]


@pytest.mark.parametrize(
    ("statement", "lean_code"),
    [
        (
            "x² の導関数は連続か",
            "theorem d : Continuous (deriv fun x : ℝ => x ^ 2) := by\n  fun_prop",
        ),
        (
            "x^2 は一様連続でない",
            "theorem u : ¬ UniformContinuous (fun x : ℝ => x ^ 2) := by\n  sorry",
        ),
        ("x² が連続", "theorem c : Continuous (fun x : ℝ => x ^ 3) := by\n  continuity"),
        ("x² が連続", "theorem c : Continuous (fun x : ℝ => x) := by\n  continuity"),
        ("x² が連続", "theorem c : ContinuousAt (fun x : ℝ => x ^ 2) 0 := by\n  fun_prop"),
    ],
)
def test_other_statements_mentioning_x_squared_do_not_get_the_requirement(
    statement: str, lean_code: str
) -> None:
    assert not _requires_epsilon_delta(statement, lean_code)
    payload = _payload()
    payload["sections"][0]["references"] = [
        {"start_line": 1, "end_line": 1, "excerpt": lean_code.splitlines()[0]}
    ]
    explainer, generator = _explainer(payload)
    candidate = _explain(explainer, statement, lean_code)
    assert "epsilon-delta explanation" not in generator.prompts[0]
    reviewer, qa = _reviewer(_approve)
    reviewer.review_explanation(
        theorem_statement=statement, lean_code=lean_code, explanation=candidate, language="ja"
    )
    assert REQUIREMENT_MARKER not in qa.prompts[0]


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("x² が連続であることを説明してください。", True),
        ("x^2 は連続？", True),
        ("x² の導関数は連続か", False),
        ("x^2 は一様連続でない", False),
        ("x^2 の微分可能性と連続性", False),
        ("n + 0 = n を示せ", False),
    ],
)
def test_wording_is_only_a_fallback_when_no_single_lean_target_is_readable(
    statement: str, expected: bool
) -> None:
    unreadable = "def helper : Nat := 1"
    assert extract_single_target_declaration(unreadable) is None
    assert _requires_epsilon_delta(statement, unreadable) is expected
    assert _is_x_squared_continuity(statement) is expected


def test_worker_alignment_gate_no_longer_demands_x_squared_for_other_properties() -> None:
    derivative = "theorem d : Continuous (deriv fun x : ℝ => x ^ 2) := by\n  fun_prop"
    assert _verified_candidate_matches_statement("x² の導関数は連続か", derivative)
    # The continuity of x² itself is still checked deterministically.
    assert not _verified_candidate_matches_statement(
        "x² が連続であることを示せ", "theorem t : Continuous (fun x : ℝ => x) := by\n  fun_prop"
    )


# Contract of the real x² review prompt: the checklist is the single, one-to-one list of
# required elements; notation is tolerated in one place; nothing cancels anything else.

TOLERATED_NOTATION = [
    "\\dfrac",
    "\\vert",
    "\\operatorname{min}",
    "\\leqslant",
    "|(x-a)(x+a)|",
    "in words",
    "display math",
    "any variable names",
]
STANDARD_FACTS = [
    "the minimum of positive numbers is positive",
    "each argument of a minimum bounds it from above",
    "the triangle inequality",
]
# Typical defects, and the single element each one must fail.
DEFECT_TO_ELEMENT = {
    "A delta with no such bound": "delta_bounded_by_one",
    "delta that ignores a": "delta_depends_on_point_and_epsilon",
    "ends in epsilon+1, 2 epsilon or delta": "final_inequality",
    "epsilon/(|a|+1) in place of epsilon/(2|a|+1)": "final_inequality",
    "delta plus 1, twice delta": "delta_bounded_by_one",
    "not a sum, not another function": "factorization",
    "Stating delta>0 with no reason at all is missing": "delta_positive_justified",
    "a bare assertion is missing": "sum_bound",
    "previews the proof plan or the conclusion": "presentation",
}


def _x_squared_review_prompt() -> str:
    explainer, _ = _explainer(_payload())
    candidate = _explain(explainer)
    reviewer, qa = _reviewer(_approve)
    reviewer.review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
    )
    return " ".join(qa.prompts[0].split())


def _definitions(prompt: str) -> dict[str, str]:
    block = prompt[prompt.index(CHECKLIST_MARKER) : prompt.index("Status. ")]
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"- ([a-z_]+): (.*?)(?= - [a-z_]+: |$)", block)
    }


def test_checklist_ids_are_defined_exactly_once_and_in_the_response_format() -> None:
    prompt = _x_squared_review_prompt()
    definitions = _definitions(prompt)
    assert tuple(definitions) == EPSILON_DELTA_CHECK_IDS
    assert len(EPSILON_DELTA_CHECK_IDS) == len(set(EPSILON_DELTA_CHECK_IDS)) == 10
    for check_id in EPSILON_DELTA_CHECK_IDS:
        assert prompt.count(f"- {check_id}: ") == 1
        assert f'{{"id": "{check_id}", "status": "ok"' in prompt


@pytest.mark.parametrize(("defect", "element"), sorted(DEFECT_TO_ELEMENT.items()))
def test_each_known_defect_is_assigned_to_exactly_one_element(defect: str, element: str) -> None:
    owners = [i for i, text in _definitions(_x_squared_review_prompt()).items() if defect in text]
    assert owners == [element]


def test_prompt_states_the_status_rule_standard_facts_and_tolerated_notation() -> None:
    prompt = _x_squared_review_prompt()
    status_rule = prompt[prompt.index("Status. ") :]
    status_rule = status_rule[: status_rule.index("Return exactly one JSON object")]
    for fragment in [*TOLERATED_NOTATION, *STANDARD_FACTS]:
        assert fragment in status_rule, fragment
    assert "Never mark an element missing or wrong because of notation or phrasing" in prompt
    assert "Style, level of detail, how explicit a step is" in prompt
    assert '"wrong" whose quote is not in the proof does not count' in prompt
    # Tolerated notation is listed only in the status rule, never as a defect of an element.
    for definition in _definitions(prompt).values():
        for notation in TOLERATED_NOTATION:
            assert notation not in definition, notation
    # The opening's wording is tolerated, a plan or conclusion preview in it is not.
    assert "The opening's notation, wording and word order are not presentation defects" in prompt
    assert "previews the proof plan or the conclusion" in _definitions(prompt)["presentation"]
    assert "Reject summary-first or conclusion-preview exposition" in prompt  # general rubric
    assert "a chain may end in an equality such as `= ε`" in prompt


def _delta_is_sufficient(delta: Callable[[Fraction, Fraction], Fraction]) -> bool:
    points = [Fraction(n, 2) for n in range(-8, 9)]
    epsilons = [Fraction(1, 100), Fraction(1, 2), Fraction(1), Fraction(10), Fraction(1000)]
    for a in points:
        for eps in epsilons:
            d = delta(a, eps)
            if d <= 0:
                return False
            for fraction in (
                Fraction(-99, 100),
                Fraction(-1, 2),
                Fraction(1, 2),
                Fraction(99, 100),
            ):
                x = a + fraction * d
                if abs(x * x - a * a) >= eps:
                    return False
    return True


def test_each_rejected_delta_in_the_rubric_really_fails_and_the_accepted_one_works() -> None:
    def good(a: Fraction, e: Fraction) -> Fraction:
        return min(Fraction(1), e / (2 * abs(a) + 1))

    assert _delta_is_sufficient(good)
    assert _delta_is_sufficient(lambda a, e: min(Fraction(1), e / (4 * abs(a) + 2)))  # equivalent
    wrong = {
        "no minimum with 1": lambda a, e: e / (2 * abs(a) + 1),
        "ignores the point": lambda a, e: min(Fraction(1), e),
        "coefficient too small": lambda a, e: min(Fraction(1), e / (abs(a) + 1)),
        "plus one": lambda a, e: good(a, e) + 1,
        "doubled": lambda a, e: 2 * good(a, e),
        "epsilon only": lambda a, e: e,
    }
    for name, delta in wrong.items():
        assert not _delta_is_sufficient(delta), name


def test_clarification_review_does_not_get_the_explanation_requirement() -> None:
    from pals_agent.explanations import ProofClarification

    explainer, _ = _explainer(_payload())
    explanation = _explain(explainer)
    clarification = ProofClarification(
        section_id="bound-difference",
        question="なぜ $|x+a|<2|a|+1$ ですか。",
        answer="$|x|<|a|+1$ だからです。",
        key_points=("三角不等式",),
        references=explanation.sections[0].references,
        model="m",
        provider="p",
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )
    reviewer, qa = _reviewer(_approve)
    reviewer.review_clarification(
        theorem_statement=STATEMENT,
        lean_code=SOURCE,
        explanation=explanation,
        clarification=clarification,
        language="ja",
    )
    assert REQUIREMENT_MARKER not in qa.prompts[0]


# Generic structural checks remain in force for the x-squared theorem.


@pytest.mark.parametrize("excerpt", ["continuity", "  sorry"])
def test_inexact_source_references_are_still_rejected(excerpt: str) -> None:
    payload = _payload()
    payload["sections"][0]["references"][0]["excerpt"] = excerpt
    explainer, _ = _explainer(payload, payload)
    with pytest.raises(ExplanationGenerationError) as raised:
        _explain(explainer)
    assert raised.value.attempt_failures == ("reference_excerpt", "reference_excerpt")


def test_out_of_range_source_references_are_still_rejected() -> None:
    payload = _payload()
    payload["sections"][0]["references"][0]["end_line"] = 3
    with pytest.raises(ValueError, match="Lean reference"):
        _parse_explanation(payload, SOURCE)


def test_lean_vocabulary_in_learner_prose_is_still_rejected() -> None:
    payload = _payload(summary=GOOD_SUMMARY + " ここで linarith を使います。")
    with pytest.raises(ValueError, match="Lean tactic"):
        _parse_explanation(payload, SOURCE)


def test_repeated_final_equation_is_still_rejected() -> None:
    payload = _payload(
        summary="よって $|x^2-a^2|=|x-a||x+a|$。", conclusion="$|x^2-a^2|=|x-a||x+a|$。"
    )
    with pytest.raises(ValueError, match="final equation is repeated"):
        _parse_explanation(payload, SOURCE, require_linear_ending=True)


# Latin abbreviations in English prose are not Lean identifiers.


@pytest.mark.parametrize("abbreviation", ["e.g.", "i.e.", "E.g.", "I.e."])
def test_latin_abbreviations_are_not_mistaken_for_lean_identifiers(abbreviation: str) -> None:
    payload = _payload(summary=f"Take any bound on $|x+a|$ ({abbreviation} $2|a|+1$) near $a$.")
    _parse_explanation(payload, SOURCE, language="en")


def test_lean_qualified_identifiers_are_still_rejected() -> None:
    payload = _payload(summary="Apply Nat.add_zero here.")
    with pytest.raises(ValueError, match="Lean identifier"):
        _parse_explanation(payload, SOURCE, language="en")
