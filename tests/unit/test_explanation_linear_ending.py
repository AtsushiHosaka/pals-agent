import pytest

from pals_agent.explanations import _reject_repeated_final_equation


@pytest.mark.parametrize(
    "closing",
    [
        r"$(x+y)^2=x^2+2xy+y^2$ が示された。",
        r"\((x+y)^2 = x^2 + 2xy + y^2\) follows.",
        r"\[(x+y)^2=x^2+2xy+y^2\]。",
    ],
)
def test_observed_double_final_equation_is_rejected(closing):
    section = r"実数では $xy=yx$ なので中項をまとめる。したがって $(x+y)^2=x^2+2xy+y^2$ である。"
    with pytest.raises(ValueError, match="final equation is repeated"):
        _reject_repeated_final_equation(section, closing)


def test_final_equation_once_after_intermediate_calculation_is_valid():
    _reject_repeated_final_equation(
        r"中項は $xy+yx=2xy$ にまとめられる。",
        r"したがって $(x+y)^2=x^2+2xy+y^2$ である。",
    )


def test_reused_premise_before_new_final_calculation_is_valid():
    _reject_repeated_final_equation(
        r"$a=b$ を用いて $f(a)=f(b)$ を得る。",
        r"従って $a=b$ ならば両者の関数値は等しい。",
    )


def test_kernel_argument_can_reuse_a_premise_in_a_new_implication():
    _reject_repeated_final_equation(
        r"先ほどの基底表示で $T(v)=0$ の係数を比較すると、すべての係数が零となる。",
        r"したがって $T(v)=0$ ならば $v=0$ であり、核は零空間である。",
    )


def test_conclusion_may_use_old_equation_to_draw_new_prose_consequence():
    _reject_repeated_final_equation(
        r"したがって $T(v)=0$ である。",
        r"$T(v)=0$ より、このベクトルは核に属する。",
    )
