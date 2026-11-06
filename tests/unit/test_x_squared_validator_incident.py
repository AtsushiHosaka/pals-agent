"""Synthetic regressions for the production x-squared explanation failure.

These exercise the actual parser/gate; they do not emulate production model success
or certify the supplied Lean source. Independent mathematical review remains required.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from typing import Any

import pytest

from pals_agent.explanations import _has_x_squared_epsilon_delta, _parse_explanation


def _proof(*, point: str = "a", varying: str = "x") -> str:
    return (
        f"任意の実数{point}とε>0に対し、δ=min(1,ε/(2|{point}|+1))>0。"
        f"|{varying}-{point}|<δなら "
        f"|{varying}^2-{point}^2|=|{varying}-{point}||{varying}+{point}|"
        f"<δ(2|{point}|+1)<=ε。よって{point}で連続。"
    )


@pytest.mark.parametrize(("point", "varying"), [("a", "x"), ("b", "y"), ("x_0", "t")])
def test_incident_alpha_renaming_preserves_a_valid_estimate(point: str, varying: str) -> None:
    assert _has_x_squared_epsilon_delta(_proof(point=point, varying=varying))


@pytest.mark.parametrize("suffix", ["。", "とおく。", "と定めます。", "を選ぶ。"])
def test_incident_delta_expression_ends_before_japanese_prose(suffix: str) -> None:
    proof = _proof(point="b", varying="y").replace(">0。", ">0" + suffix)
    assert _has_x_squared_epsilon_delta(proof)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("2|a|+1", "1+2|a|"),
        ("ε/(2|a|+1)", "ε/(4|a|+2)"),
        ("|x^2-a^2|", "|a^2-x^2|"),
        ("|x-a|", "|a-x|"),
        ("|x+a|", "|a+x|"),
        ("|x-a|<δ", "δ>|x-a|"),
        ("|x-a||x+a|", "|x+a|*|x-a|"),
        (
            "|x-a||x+a|<δ(2|a|+1)<=ε",
            "|x-a||x+a|。一方、|x-a||x+a|<δ(2|a|+1)<=ε",
        ),
        (
            "|x-a||x+a|<δ(2|a|+1)<=ε",
            "|x-a||x+a|。一方、|a+x|*|a-x|<δ(2|a|+1)<=ε",
        ),
    ],
)
def test_incident_equivalent_bound_notation_is_accepted(old: str, new: str) -> None:
    assert _has_x_squared_epsilon_delta(_proof().replace(old, new))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("ε/(2|a|+1)", "ε/(1|a|+1)"),
        ("ε/(2|a|+1)", "ε/(2|b|+1)"),
        ("min(1,ε/(2|a|+1))", "ε"),
        ("min(1,ε/(2|a|+1))", "min(1,ε)"),
        ("min(1,ε/(2|a|+1))", "min(1,ε/(2|a|+1))+1"),
        ("min(1,ε/(2|a|+1))", "min(1,ε/(2|a|+1))*2"),
        ("min(1,ε/(2|a|+1))", "min(1,ε/(2|a|+1))=1"),
        ("))>0。", "))の2倍とおく。δ>0である。"),
        ("))>0。", "))に1を加えた値とおく。δ>0である。"),
        ("))>0。", "))を2倍して取る。δ>0である。"),
        ("))>0。", "))と定めた値の2倍とおく。δ>0である。"),
        ("δ=min(1,ε/(2|a|+1))>0。", "正のδを選ぶ。"),
        (">0。", "。"),
        ("|x-a|<δなら", "|x-b|<δなら"),
        ("|x-a|<δなら", "|x-a|<εなら"),
        ("|x-a||x+a|", "|x+a||x+a|"),
        ("<δ(2|a|+1)<=ε", ""),
        ("<δ(2|a|+1)<=ε", "。別に0<ε"),
        ("<δ(2|a|+1)<=ε", "<δ(2|a|+1)<=2ε"),
        ("<δ(2|a|+1)<=ε", "<δ(2|a|+1)<=ε+1"),
        (
            "|x-a||x+a|<δ(2|a|+1)<=ε",
            "|x-a||x+a|。一方、0.5|x-a||x+a|<δ(2|a|+1)<=ε",
        ),
    ],
)
def test_incident_wrong_delta_or_missing_bridge_is_still_rejected(old: str, new: str) -> None:
    assert not _has_x_squared_epsilon_delta(_proof().replace(old, new))


def test_incident_japanese_double_delta_has_an_actual_counterexample() -> None:
    epsilon = Fraction(1, 2)
    point = Fraction(0)
    varying = Fraction(9, 10)
    doubled_delta = 2 * min(1, epsilon / (2 * abs(point) + 1))
    assert abs(varying - point) < doubled_delta
    assert abs(varying**2 - point**2) > epsilon
    invalid = _proof().replace("))>0。", "))の2倍とおく。δ>0である。")
    assert not _has_x_squared_epsilon_delta(invalid)


@pytest.mark.parametrize(
    "prefix",
    [
        "",
        "一般に|u^2-v^2|=|u-v||u+v|である。",
        "一般に|z^2-a^2|=|z-a||z+a|である。",
        "一般に|x^2-a^2|=|x-a||x+a|である。",
    ],
)
def test_review_followup_connected_equalities_keep_the_same_epsilon_estimate(prefix: str) -> None:
    proof = _proof().replace(
        "|x-a||x+a|<δ(2|a|+1)<=ε",
        "|x-a||x+a|=|x-a||2a+(x-a)|<=|x-a|(2|a|+|x-a|)<δ(2|a|+1)<=ε",
    )
    assert _has_x_squared_epsilon_delta(prefix + proof)


@pytest.mark.parametrize(
    "prefix",
    [
        "一般に|u^2-v^2|=|u-v||u+v|である。",
        "一般に|z^2-a^2|=|z-a||z+a|である。",
        "一般に|x^2-a^2|=|x-a||x+a|である。",
    ],
)
def test_review_followup_general_identity_does_not_choose_the_proof_variables(prefix: str) -> None:
    assert _has_x_squared_epsilon_delta(prefix + _proof())


def test_review_followup_all_later_factorizations_of_the_same_pair_are_considered() -> None:
    proof = (
        "任意の実数aとε>0に対し、δ=min(1,ε/(2|a|+1))>0。"
        "|x-a|<δとする。まず一般に|x^2-a^2|=|x-a||x+a|である。"
        "この恒等式から|x^2-a^2|=|x-a||x+a|=|x-a||2a+(x-a)|"
        "<=|x-a|(2|a|+|x-a|)<δ(2|a|+1)<=ε。よってaで連続。"
    )
    assert _has_x_squared_epsilon_delta(proof)


@pytest.mark.parametrize(
    "proof",
    [
        (
            "一般に|y^2-b^2|=|y-b||y+b|である。"
            "任意の実数bとε>0に対し、δ=min(1,ε/(2|b|+1))>0。"
            "|y-b|<δなら |y^2-a^2|=|y-a||y+a|<δ(2|b|+1)<=ε。よってbで連続。"
        ),
        (
            "一般に|y^2-b^2|=|y-b||y+b|。"
            "任意の実数bとε>0に対し、δ=min(1,ε/(2|b|+1))>0。"
            "|y-b|<δとする。別の点aと変数xについて"
            "|x^2-a^2|=|x-a||x+a|<ε。よってbで連続。"
        ),
    ],
)
def test_review_followup_other_point_names_are_not_captured_by_alpha_renaming(proof: str) -> None:
    assert not _has_x_squared_epsilon_delta(proof)


@pytest.mark.parametrize(
    "tail",
    [
        "=|x-a||2a+(x-a)|",
        "=|x-a||2a+(x-a)|。別に0<ε",
        "=|x-a||2a+(x-a)|<=δ(2|a|+1)<=ε+1",
        "=|x-a||2a+(x-a)|<=δ(2|a|+1)<=2ε",
        "=別の数0<ε",
    ],
)
def test_review_followup_equalities_do_not_replace_a_bound_on_the_difference(tail: str) -> None:
    proof = _proof().replace("<δ(2|a|+1)<=ε", tail)
    assert not _has_x_squared_epsilon_delta(proof)


SOURCE = "theorem continuous_square : Continuous (fun x : ℝ => x ^ 2) := by\n  continuity"


def _payload() -> dict[str, Any]:
    return {
        "overview": "$0<\\epsilon$ を任意に取り、実数 $b$ を固定します。",
        "sections": [
            {
                "id": "bound-difference",
                "title": "差の評価",
                "summary": (
                    "$\\delta=\\min(1,\\epsilon/(2|b|+1))>0$ とおく。"
                    "$|y-b|<\\delta$ なら "
                    "$|y^2-b^2|=|y-b||y+b|<\\delta(2|b|+1)\\le\\epsilon$ です。"
                ),
                "references": [{"start_line": 2, "end_line": 2, "excerpt": "  continuity"}],
            }
        ],
        "conclusion": "$b$ は任意なので、平方関数は実数全体で連続です。",
    }


def test_incident_actual_parser_accepts_renamed_proof_and_equivalent_epsilon_setup() -> None:
    overview, sections, conclusion = _parse_explanation(
        _payload(), SOURCE, language="ja", require_epsilon_delta=True, require_linear_ending=True
    )
    assert overview.startswith("$0<\\epsilon$")
    assert "|y-b|" in sections[0].summary
    assert "連続" in conclusion


@pytest.mark.parametrize("general_identity", [False, True])
@pytest.mark.parametrize("connected_equalities", [False, True])
def test_review_followup_actual_parser_accepts_the_same_bound_structure(
    general_identity: bool, connected_equalities: bool
) -> None:
    payload = _payload()
    summary = payload["sections"][0]["summary"]
    if connected_equalities:
        summary = summary.replace(
            "|y-b||y+b|<",
            "|y-b||y+b|=|y-b||2b+(y-b)|\\le|y-b|(2|b|+|y-b|)<",
        )
    if general_identity:
        summary = "一般に$|u^2-v^2|=|u-v||u+v|$です。" + summary
    payload["sections"][0]["summary"] = summary
    _parse_explanation(
        payload, SOURCE, language="ja", require_epsilon_delta=True, require_linear_ending=True
    )


@pytest.mark.parametrize("excerpt", ["continuity", "  sorry"])
def test_incident_parser_still_rejects_inexact_source_references(excerpt: str) -> None:
    payload = deepcopy(_payload())
    payload["sections"][0]["references"][0]["excerpt"] = excerpt
    with pytest.raises(ValueError, match="excerpt does not exactly match"):
        _parse_explanation(payload, SOURCE, require_epsilon_delta=True)


def test_incident_parser_still_rejects_out_of_range_source_references() -> None:
    payload = deepcopy(_payload())
    payload["sections"][0]["references"][0]["end_line"] = 3
    with pytest.raises(ValueError, match="Lean reference"):
        _parse_explanation(payload, SOURCE, require_epsilon_delta=True)


def test_incident_parser_still_rejects_missing_positive_epsilon_setup() -> None:
    payload = deepcopy(_payload())
    payload["overview"] = "平方関数について、連続性の証明方針を説明します。"
    with pytest.raises(ValueError, match="must start"):
        _parse_explanation(payload, SOURCE, require_epsilon_delta=True)
