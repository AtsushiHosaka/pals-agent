"""Notation/bound-alias regressions; no provider/compiler or production acceptance claim."""
from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from pals_agent.explanations import _has_x_squared_epsilon_delta, _normalize_x_squared_math

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
    text = text.replace("$" + equality + "$", ("" if name == "align*" else "$")
                        + beginning + wrapped + ending + ("" if name == "align*" else "$"))
    if multiline:
        bound = BOUND if BOUND in text else BOUND.replace(r"\le\varepsilon", r"\le2\varepsilon")
        lhs, remainder = bound.split(r"\le ", 1)
        wrapped = lhs + r"&\le " + remainder.replace(r"<\delta", r"\\&<\delta")
        wrapped = wrapped.replace(r")\le", r")\\&\le")
        text = text.replace("$" + bound + "$", ("" if name == "align*" else "$")
                            + beginning + wrapped + ending + ("" if name == "align*" else "$"))
    return text


def bound_only(text: str) -> str:
    transformed = environment(text, "aligned", multiline=True)
    return transformed.replace(r"\begin{aligned}" + EQUALITY.replace("=", "&=", 1)
                               + r"\end{aligned}", EQUALITY)


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


@pytest.mark.parametrize("style", STYLES, ids=STYLES)
def test_same_complete_epsilon_delta_proof_in_standard_notation(style: str) -> None:
    assert _has_x_squared_epsilon_delta(STYLES[style](PROOF))


@pytest.mark.parametrize("style", STYLES, ids=STYLES)
@pytest.mark.parametrize("negative", ["delta", "point", "factor"])
def test_mathematical_errors_stay_rejected_in_standard_notation(style: str, negative: str) -> None:
    proof = PROOF
    if negative == "delta":
        proof = proof.replace(r"\delta=\min\{1,\varepsilon/(2|a|+1)\}",
                              r"\delta=\min\{1,\varepsilon/(|a|+1)\}")
    elif negative == "point":
        proof = proof.replace(r"|x-a|<\delta", r"|x-b|<\delta")
    else:
        proof = proof.replace(EQUALITY, EQUALITY.replace("|x-a||x+a|", "|x+a||x+a|"))
    assert not _has_x_squared_epsilon_delta(STYLES[style](proof))


@pytest.mark.parametrize("style", STYLES, ids=STYLES)
def test_weaker_endpoint_does_not_turn_a_later_conclusion_into_the_bridge(style: str) -> None:
    # This is a gate-completeness control, not a claim that the continuous
    # square theorem or its retained delta/auxiliary bounds become false.
    proof = PROOF.replace(r"<\delta(2|a|+1)\le\varepsilon",
                          r"<\delta(2|a|+1)\le2\varepsilon")
    assert not _has_x_squared_epsilon_delta(STYLES[style](proof))


@pytest.mark.parametrize("size", ["big", "Big", "bigg", "Bigg"])
@pytest.mark.parametrize("sides", [False, True])
def test_finite_delimiter_size_family(size: str, sides: bool) -> None:
    left = "\\" + size + ("l" if sides else "") + "|"
    right = "\\" + size + ("r" if sides else "") + "|"
    assert _has_x_squared_epsilon_delta(absolute(PROOF, left, right))


@pytest.mark.parametrize("replacement", [
    r"|x^2-a^2|\unknown=|x-a||x+a|",
    r"|x^2-a^2|\text{=}|x-a||x+a|",
    r"|x^2-a^2|&=|x-a||x+a|",
    r"\begin{unknown}|x^2-a^2|&=|x-a||x+a|\end{unknown}",
    r"\begin{array}{@{}rl@{}}|x^2-a^2|&=|x-a||x+a|\end{array}",
    r"\begin{aligned}|x^2-a^2|&=|x-a||x+a|\end{array}",
    r"\begin{aligned}\begin{unknown}|x^2-a^2|&=|x-a||x+a|\end{unknown}\end{aligned}",
    r"\begin{aligned}\text{|x^2-a^2|&=|x-a||x+a|}\end{aligned}",
    r"\begin{aligned}|x^2-a^2|&=|x-a||x+a|\unknown{value}\end{aligned}",
    r"\begin{array}{ll}|x^2-a^2|=|x-a|&|x+a|\end{array}",
    r"\begin{aligned}|x^2-a^2|=|x-a|\\|x+a|\end{aligned}",
])
def test_unknown_macros_layouts_and_text_are_not_deleted(replacement: str) -> None:
    assert not _has_x_squared_epsilon_delta(PROOF.replace(EQUALITY, replacement))


def test_unknown_size_macro_is_not_erased() -> None:
    assert r"\biglunknown" in _normalize_x_squared_math(r"\biglunknown|a|")
    assert r"\leftarrow" in _normalize_x_squared_math(r"C\leftarrow1")


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


@pytest.mark.parametrize("old,new", [
    ("C", "K"),
    ("2|a|+1", "1+2|a|"),
    ("2|a|+1", "2*|a|+1"),
    (r"\varepsilon/C", r"\frac{\varepsilon}{C}"),
    (r"(\varepsilon/C)C", r"(\varepsilon/C)*C"),
    (r"$C=2|a|+1$", r"$C:=2|a|+1$"),
    (r"$C=2|a|+1$", r"$C\coloneqq 2|a|+1$"),
])
def test_unique_positive_bound_alias_and_exact_cancellation(old: str, new: str) -> None:
    assert _has_x_squared_epsilon_delta(ALIAS_PROOF.replace(old, new))


def test_later_separate_cancellation_is_not_masked_by_earlier_nonfinal_bound() -> None:
    assert _has_x_squared_epsilon_delta(ALIAS_PROOF)


@pytest.mark.parametrize("prose", [
    "Cは2|a|に1を加えた値である。",
    r"$C$は点の絶対値の2倍に1を加えた定数です。",
    "Cを使って差の評価を書き換える。",
    "Cを2倍した値をDと呼ぶ。C自体は変更しない。",
    "Cを2倍してもC自体は更新しない。",
])
def test_explaining_or_using_the_existing_bound_does_not_rebind_it(prose: str) -> None:
    proof = ALIAS_PROOF.replace(r"$C>0$なので", prose + r"$C>0$なので")
    assert _has_x_squared_epsilon_delta(proof)


@pytest.mark.parametrize("old,new", [
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
    (r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon",
     r"|x^2-a^2|\le|x-a|C,0<(\varepsilon/C)C=\varepsilon"),
    (r"|x^2-a^2|<(\varepsilon/C)C=\varepsilon",
     r"|x^2-a^2|\le|x-a|C+0<(\varepsilon/C)C=\varepsilon"),
    (r"|x-a|<\delta", r"|x-b|<\delta"),
])
def test_alias_errors_rebinding_and_inexact_cancellation_are_rejected(old: str, new: str) -> None:
    assert not _has_x_squared_epsilon_delta(ALIAS_PROOF.replace(old, new))


def test_bound_alias_cannot_be_the_varying_variable() -> None:
    proof = ALIAS_PROOF.replace("C", "X").replace("x", "X")
    assert not _has_x_squared_epsilon_delta(proof)


LITERAL_PRODUCT = r"\varepsilon/(2|a|+1)*(2|a|+1)"


def literal_cancellation_proof(*, connected: bool) -> str:
    ending = r"<\delta(2|a|+1)\le" + LITERAL_PRODUCT + r"=\varepsilon"
    replacement = "$" + EQUALITY + ending + "$" if connected else (
        "$" + EQUALITY + "$かつ$"
        + r"|x^2-a^2|\le|x-a|(2|a|+1)" + ending + "$"
    )
    return PROOF.replace("$" + EQUALITY + "$かつ$" + BOUND + "$", replacement)


@pytest.mark.parametrize("point,varying", [("a", "x"), ("b", "y"), ("x_0", "t")])
@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("reordered", [False, True])
def test_literal_sufficient_denominator_cancellation_keeps_exact_point_binding(
    point: str, varying: str, connected: bool, reordered: bool
) -> None:
    proof = literal_cancellation_proof(connected=connected)
    if reordered:
        proof = proof.replace("2|a|+1", "1+2|a|")
    proof = re.sub(r"(?<![A-Za-z0-9_])a(?![A-Za-z0-9_])", point, proof)
    proof = re.sub(r"(?<![A-Za-z0-9_])x(?![A-Za-z0-9_])", varying, proof)
    assert _has_x_squared_epsilon_delta(proof)


@pytest.mark.parametrize("old,new", [
    (LITERAL_PRODUCT, r"\varepsilon/(2|b|+1)*(2|a|+1)"),
    (LITERAL_PRODUCT, r"\varepsilon/(2|a|+1)*(2|b|+1)"),
    (LITERAL_PRODUCT, r"\varepsilon/(3|a|+1)*(2|a|+1)"),
    (LITERAL_PRODUCT, r"2\varepsilon/(2|a|+1)*(2|a|+1)"),
    (LITERAL_PRODUCT + r"=\varepsilon", LITERAL_PRODUCT + r"=\varepsilon+1"),
    (LITERAL_PRODUCT + r"=\varepsilon", LITERAL_PRODUCT + r"=2\varepsilon"),
    (r"<\delta(2|a|+1)\le", r"\le\delta(2|a|+1)\le"),
    (LITERAL_PRODUCT, r"\varepsilon/(2|a|+1)*(2|a|+1)+1"),
])
def test_literal_cancellation_does_not_accept_changed_arithmetic_or_weak_bridge(
    old: str, new: str
) -> None:
    proof = literal_cancellation_proof(connected=True).replace(old, new)
    assert not _has_x_squared_epsilon_delta(proof)
