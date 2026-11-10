"""Codex's notation/alias regressions, migrated to the semantic design.

The text gate they tested (`_has_x_squared_epsilon_delta` and its normalizers) no longer exists:
the epsilon-delta requirement is judged by the independent checklist review. What survives is
the part that is independent of the gate:

* every input that the gate had to ACCEPT is a mathematically valid proof (or a valid
  notation of one) and must pass the structural layer in one generation attempt and reach the
  reviewer intact, whatever its layout, delimiter sizing, alias or order of identities;
* every input that the gate had to REFUSE must also reach the reviewer, because only the
  checklist (not a pattern) can refuse it. The mathematical errors among them are cases of the
  real-model regression set (testdata/explanation-qa-v1: wrong-18 .. wrong-22 and the older
  wrong cases); see docs/verification/explanation-semantic-gate-2026-11-06.md for the mapping.

Stub models only; whether the real reviewer decides each case correctly is measured by
scripts/evaluate_explanation_qa.py.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import pytest

from pals_agent.explanations import LeanGroundedOutputReviewer, LeanProofExplainer

SOURCE = "theorem continuous_square : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"
STATEMENT = "x² が連続であることを説明してください。"
REFERENCE = [{"start_line": 1, "end_line": 2, "excerpt": SOURCE}]


PROOF = (
    r"$\varepsilon>0$を任意に取り、実数$a$を固定する。"
    r"$\delta=\min\{1,\varepsilon/(2|a|+1)\}$と定める。"
    r"$2|a|+1>0$なので$\delta>0$。"
    r"$|x-a|<\delta$なら$|x-a|<1$で、"
    r"三角不等式から$|x|\le|x-a|+|a|<1+|a|$。"
    r"よって$|x+a|\le|x|+|a|<2|a|+1$。"
    r"$|x^2-a^2|=|x-a||x+a|$かつ"
    r"$|x^2-a^2|\le |x-a|(2|a|+1)<\delta(2|a|+1)\le\varepsilon$。"
    r"任意の$x$について$|x-a|<\delta$から$|x^2-a^2|<\varepsilon$が従う。"
    r"$a$は任意なので平方関数は実数全体で連続。"
)
EQUALITY = r"|x^2-a^2|=|x-a||x+a|"
BOUND = r"|x^2-a^2|\le |x-a|(2|a|+1)<\delta(2|a|+1)\le\varepsilon"


def absolute(text: str, left: str, right: str) -> str:
    return re.sub(r"\|([^|]+)\|", lambda match: left + match[1] + right, text)


def environment(text: str, name: str, *, multiline: bool, aligned: bool = True) -> str:
    equality = EQUALITY if EQUALITY in text else EQUALITY.replace("|x-a||x+a|", "|x+a||x+a|")
    left, right = equality.split("=", 1)
    wrapped = left + ("&=" if aligned else "=") + right
    beginning = "\\begin{" + name + "}" + ("{rl}" if name == "array" else "")
    ending = "\\end{" + name + "}"
    text = text.replace(
        "$" + equality + "$",
        ("" if name == "align*" else "$")
        + beginning
        + wrapped
        + ending
        + ("" if name == "align*" else "$"),
    )
    if multiline:
        bound = BOUND if BOUND in text else BOUND.replace(r"\le\varepsilon", r"\le2\varepsilon")
        lhs, remainder = bound.split(r"\le ", 1)
        wrapped = lhs + r"&\le " + remainder.replace(r"<\delta", r"\\&<\delta")
        wrapped = wrapped.replace(r")\le", r")\\&\le")
        text = text.replace(
            "$" + bound + "$",
            ("" if name == "align*" else "$")
            + beginning
            + wrapped
            + ending
            + ("" if name == "align*" else "$"),
        )
    return text


def bound_only(text: str) -> str:
    transformed = environment(text, "aligned", multiline=True)
    return transformed.replace(
        r"\begin{aligned}" + EQUALITY.replace("=", "&=", 1) + r"\end{aligned}", EQUALITY
    )


STYLES: dict[str, Callable[[str], str]] = {
    "plain": lambda text: text,
    "left-right": lambda text: absolute(text, r"\left|", r"\right|"),
    "lvert-rvert": lambda text: absolute(text, r"\lvert ", r"\rvert"),
    "bigl-bigr": lambda text: absolute(text, r"\bigl|", r"\bigr|"),
    "Bigl-Bigr": lambda text: absolute(text, r"\Bigl|", r"\Bigr|"),
    "bigl-lvert": lambda text: absolute(text, r"\bigl\lvert ", r"\bigr\rvert"),
    "aligned": lambda text: environment(text, "aligned", multiline=False),
    "align-star": lambda text: environment(text, "align*", multiline=False),
    "array": lambda text: environment(text, "array", multiline=False),
    "aligned-no-ampersand": lambda text: environment(
        text, "aligned", multiline=False, aligned=False
    ),
    "aligned-bound-only": bound_only,
    "aligned-multiline": lambda text: environment(text, "aligned", multiline=True),
    "align-star-multiline": lambda text: environment(text, "align*", multiline=True),
    "array-multiline": lambda text: environment(text, "array", multiline=True),
}


ALIAS_PROOF = (
    r"任意の実数$a$と$\varepsilon>0$に対し、$C=2|a|+1$と定める。"
    r"$C>0$なので$\delta=\min\{1,\varepsilon/C\}>0$。"
    r"$|x-a|<\delta$なら$|x-a|<1$かつ$|x-a|<\varepsilon/C$。"
    r"三角不等式から$|x+a|\le|x-a|+2|a|<1+2|a|=C$。"
    r"$|x^2-a^2|=|x-a||x+a|$。"
    r"したがって$|x^2-a^2|\le|x-a|C$。"
    r"さらに$|x^2-a^2|<(\varepsilon/C)C=\varepsilon$。"
    r"任意の$a$について平方関数は連続。"
)


ALIAS_ACCEPT = [
    ("C", "K"),
    ("2|a|+1", "1+2|a|"),
    ("2|a|+1", "2*|a|+1"),
    (r"\varepsilon/C", r"\frac{\varepsilon}{C}"),
    (r"(\varepsilon/C)C", r"(\varepsilon/C)*C"),
    (r"$C=2|a|+1$", r"$C:=2|a|+1$"),
    (r"$C=2|a|+1$", r"$C\coloneqq 2|a|+1$"),
]

PROSE = [
    "Cは2|a|に1を加えた値である。",
    r"$C$は点の絶対値の2倍に1を加えた定数です。",
    "Cを使って差の評価を書き換える。",
    "Cを2倍した値をDと呼ぶ。C自体は変更しない。",
    "Cを2倍してもC自体は更新しない。",
]

ALIAS_ERRORS = [
    ("2|a|+1", "|a|+1"),
    ("2|a|+1", "2|b|+1"),
    (r"$C=2|a|+1$と定める。", ""),
    (r"$C>0$なので", r"$C=1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$(C:=1)$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"\(C:=1\)と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$\{C:=1\}$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C\coloneqq 1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C\coloneq 1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$(C)=1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$((C))\colon=1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C\gets1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C\leftarrow1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C←1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C<-1$と再定義する。$C>0$なので"),
    (r"$C>0$なので", r"$C$を1に置き換える。$C>0$なので"),
    (r"$C>0$なので", r"Cを2倍して更新する。$C>0$なので"),
    (r"$C>0$なので", r"Cを2倍にする。$C>0$なので"),
    (r"$|x-a|<\delta$なら", r"$C:=2|a|+1$と再定義する。$|x-a|<\delta$なら"),
    (r"$C=2|a|+1$", r"$C=2|C|+1$"),
    (r"(\varepsilon/C)C=\varepsilon", r"(\varepsilon/C)D=\varepsilon"),
    (r"(\varepsilon/C)C=\varepsilon", r"(\varepsilon/D)C=\varepsilon"),
    (r"(\varepsilon/C)C=\varepsilon", r"(\varepsilon/C)(C+1)=\varepsilon"),
    (r"(\varepsilon/C)C=\varepsilon", r"(\varepsilon/C)C=\varepsilon+1"),
    (r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon", r"0<(\varepsilon/C)C=\varepsilon"),
    (r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon", r"|x^2-a^2|<(\varepsilon/C)C=2\varepsilon"),
    (r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon", r"|x^2-a^2|\le(\varepsilon/C)C=\varepsilon"),
    (
        r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon",
        r"|x^2-a^2|\le|x-a|C,0<(\varepsilon/C)C=\varepsilon",
    ),
    (
        r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon",
        r"|x^2-a^2|\le|x-a|C+0<(\varepsilon/C)C=\varepsilon",
    ),
    (r"|x-a|<\delta", r"|x-b|<\delta"),
]
LITERAL_PRODUCT = r"\varepsilon/(2|a|+1)*(2|a|+1)"


def literal_cancellation_proof(*, connected: bool) -> str:
    ending = r"<\delta(2|a|+1)\le" + LITERAL_PRODUCT + r"=\varepsilon"
    replacement = (
        "$" + EQUALITY + ending + "$"
        if connected
        else ("$" + EQUALITY + "$かつ$" + r"|x^2-a^2|\le|x-a|(2|a|+1)" + ending + "$")
    )
    return PROOF.replace("$" + EQUALITY + "$かつ$" + BOUND + "$", replacement)


class _Client:
    def __init__(self, answer: Callable[[str], str]) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str, timeout_seconds: float | None = None) -> str:
        _ = (model, timeout_seconds)
        self.prompts.append(prompt)
        return self.answer(prompt)


def _payload(text: str) -> dict[str, object]:
    """Split a flat proof into overview / sections / conclusion at sentence boundaries."""
    sentences = [part + "。" for part in text.split("。") if part.strip()]
    overview, middle, conclusion = sentences[0], sentences[1:-1], sentences[-1]
    sections: list[str] = []
    current = ""
    for sentence in middle:
        if current and len(current) + len(sentence) > 700:
            sections.append(current)
            current = ""
        current += sentence
    sections.append(current)
    return {
        "overview": overview,
        "sections": [
            {"id": f"s{i}", "title": "t", "summary": summary, "references": REFERENCE}
            for i, summary in enumerate(sections)
        ],
        "conclusion": conclusion,
    }


def _reaches_the_reviewer(text: str) -> None:
    """One generation attempt passes the structural layer; the reviewer sees the text."""
    generator = _Client(lambda _prompt: json.dumps(_payload(text), ensure_ascii=False))
    explainer = LeanProofExplainer(client=generator, model="m", provider="p")
    candidate = explainer.explain(theorem_statement=STATEMENT, lean_code=SOURCE, verified=True)
    assert len(generator.prompts) == 1
    reviewer_client = _Client(lambda _prompt: "unused")
    reviewer = LeanGroundedOutputReviewer(client=reviewer_client, model="m", provider="p")
    from pals_agent.explanations import _output_review_prompt

    prompt = _output_review_prompt(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=candidate, language="ja"
    )
    assert "EPSILON-DELTA REQUIREMENT" in prompt
    visible = prompt[prompt.index("BEGIN LEARNER-VISIBLE PROOF") :]
    assert candidate.sections[0].summary in visible
    del reviewer


@pytest.mark.parametrize("style", STYLES, ids=STYLES)
def test_the_same_complete_proof_in_standard_notation_reaches_the_reviewer(style: str) -> None:
    _reaches_the_reviewer(STYLES[style](PROOF))


@pytest.mark.parametrize("size", ["big", "Big", "bigg", "Bigg"])
@pytest.mark.parametrize("sides", [False, True])
def test_sized_delimiters_reach_the_reviewer(size: str, sides: bool) -> None:
    left = "\\" + size + ("l" if sides else "") + "|"
    right = "\\" + size + ("r" if sides else "") + "|"
    _reaches_the_reviewer(absolute(PROOF, left, right))


@pytest.mark.parametrize("old,new", ALIAS_ACCEPT)
def test_a_named_positive_bound_and_its_cancellation_reach_the_reviewer(old: str, new: str) -> None:
    _reaches_the_reviewer(ALIAS_PROOF.replace(old, new))


@pytest.mark.parametrize("prose", PROSE)
def test_explaining_or_using_the_existing_bound_reaches_the_reviewer(prose: str) -> None:
    _reaches_the_reviewer(ALIAS_PROOF.replace(r"$C>0$なので", prose + r"$C>0$なので"))


@pytest.mark.parametrize("point,varying", [("a", "x"), ("b", "y"), ("x_0", "t")])
@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("reordered", [False, True])
def test_cancellation_by_the_literal_denominator_reaches_the_reviewer(
    point: str, varying: str, connected: bool, reordered: bool
) -> None:
    proof = literal_cancellation_proof(connected=connected)
    if reordered:
        proof = proof.replace("2|a|+1", "1+2|a|")
    proof = re.sub(r"(?<![A-Za-z0-9_])a(?![A-Za-z0-9_])", point, proof)
    proof = re.sub(r"(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", varying, proof)
    _reaches_the_reviewer(proof)


@pytest.mark.parametrize("old,new", ALIAS_ERRORS)
def test_alias_errors_are_not_decided_by_a_pattern_and_reach_the_reviewer(
    old: str, new: str
) -> None:
    # The mathematical errors among these are refused by the checklist (regression set
    # wrong-18 .. wrong-22); here we only pin that no text pattern is involved.
    _reaches_the_reviewer(ALIAS_PROOF.replace(old, new))


@pytest.mark.parametrize("style", STYLES, ids=STYLES)
@pytest.mark.parametrize("negative", ["delta", "point", "factor"])
def test_mathematical_errors_in_any_layout_reach_the_reviewer(style: str, negative: str) -> None:
    proof = PROOF
    if negative == "delta":
        proof = proof.replace(
            r"\delta=\min\{1,\varepsilon/(2|a|+1)\}", r"\delta=\min\{1,\varepsilon/(|a|+1)\}"
        )
    elif negative == "point":
        proof = proof.replace(r"|x-a|<\delta", r"|x-b|<\delta")
    else:
        proof = proof.replace(EQUALITY, EQUALITY.replace("|x-a||x+a|", "|x+a||x+a|"))
    _reaches_the_reviewer(STYLES[style](proof))
