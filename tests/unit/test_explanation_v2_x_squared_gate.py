# ruff: noqa: E501
"""The v2 writer's x² epsilon-delta text gate accepts a valid proof written in ordinary prose.

Regression for a measured defect: a correct, Lean-faithful epsilon-delta explanation (the
final bound and the positivity of delta stated in their own `$...$` spans and sentences) was
rejected on every attempt, so v2 returned ``generation_failed`` for the request. The gate must
keep rejecting an explanation that lacks the delta choice, a sufficient delta, or the final bound.
"""

from __future__ import annotations

import pytest

from pals_agent.explanations import _has_x_squared_epsilon_delta

VALID = r"""関数 $f(x)=x^2$ は実数全体で連続です。任意の点 $a$ と $\varepsilon>0$ に対し、$\delta=\min\left(1,\frac{\varepsilon}{2|a|+1}\right)$ と選びます。
任意の $a\in\mathbb R$ と $\varepsilon>0$ を取ります。$2|a|+1>0$ なので、$\delta=\min\left(1,\frac{\varepsilon}{2|a|+1}\right)$ は正です。この選び方から、$|x-a|<\delta$ なら $|x-a|<1$ かつ $|x-a|<\frac{\varepsilon}{2|a|+1}$ です。
平方差の因数分解から $|x^2-a^2|=|x-a||x+a|$ です。$|x+a|\le 2|a|+1$ なので、$|x^2-a^2|\le |x-a|(2|a|+1)$ です。したがって $|x-a|<\delta$ なら $|x^2-a^2|<\varepsilon$ です。
よって $x\mapsto x^2$ は連続です。"""


def test_valid_epsilon_delta_in_ordinary_prose_is_accepted() -> None:
    assert _has_x_squared_epsilon_delta(VALID)


@pytest.mark.parametrize(
    ("label", "text"),
    [
        ("no_final_bound", VALID.replace(r"$|x^2-a^2|<\varepsilon$", "$|x^2-a^2|$ は小さい")),
        (
            "insufficient_delta",
            VALID.replace(r"\frac{\varepsilon}{2|a|+1}\right)$ と選び", r"\frac{\varepsilon}{|a|+1}\right)$ と選び")
            .replace(r"\frac{\varepsilon}{2|a|+1}\right)$ は正", r"\frac{\varepsilon}{|a|+1}\right)$ は正"),
        ),
        ("delta_bound_is_not_the_final_bound", VALID.replace(r"|x^2-a^2|<\varepsilon$ です", r"|x-a|<\varepsilon$ です")),
        ("no_delta_construction", VALID.replace(r"\delta=\min", r"\delta\approx\min")),
        ("no_factorization", VALID.replace("|x^2-a^2|=|x-a||x+a|", "|x^2-a^2|\\le |x-a||x+a|")),
    ],
)
def test_incomplete_epsilon_delta_is_still_rejected(label: str, text: str) -> None:
    assert text != VALID, label
    assert not _has_x_squared_epsilon_delta(text), label


CHAIN = r"""任意の $a$ と $\varepsilon>0$ に対し $\delta=\min\{1,\varepsilon/(2|a|+1)\}$ は正です。$|x-a|<\delta$ から $|x-a|<1$ かつ $|x-a|<\varepsilon/(2|a|+1)$ です。
$x^2-a^2=(x-a)(x+a)$ なので $|x^2-a^2|=|x-a||x+a|$ です。$|x+a|\le 2|a|+1$ より、$|x^2-a^2|\le |x-a|(2|a|+1)<\frac{\varepsilon}{2|a|+1}(2|a|+1)=\varepsilon$ となります。よって連続です。"""


def test_bound_written_as_a_chain_that_ends_at_epsilon_is_accepted() -> None:
    assert _has_x_squared_epsilon_delta(CHAIN)


def test_chain_that_never_reaches_epsilon_is_rejected() -> None:
    cut = CHAIN.replace(r"<\frac{\varepsilon}{2|a|+1}(2|a|+1)=\varepsilon$", r"$")
    assert cut != CHAIN
    assert not _has_x_squared_epsilon_delta(cut)
