"""A fixed, reviewed explanation for a proof that is exactly the x² epsilon-delta template.

When the verified Lean source is byte-for-byte what ``render_x_squared_epsilon_delta`` renders for
some names, the mathematics of the proof is known in advance: ``δ = min 1 (ε / (2|a| + 1))``,
``|x - a| < 1``, ``|x + a| ≤ 2|a| + 1``, ``|x² - a²| = |x - a||x + a|`` and the cancellation
``(ε / C) C = ε``.  A model call would only restate it, so this module writes the prose itself, once
per output language, with the learner-facing names of the rendered proof.

Nothing about the contract changes:

* the text goes through the same ``_parse_explanation`` validation as a model's output (strict
  prose, language share, Lean-term rejection, byte-exact line references into *this* source);
* it is a *candidate*: the caller still runs the independent output review on it and writes it
  with that review's evidence.  Nothing here produces review evidence;
* the source must equal the template rendering exactly, so a model-written proof, an edited
  template or any other claim never receives this text;
* a review rejection falls back to the model explainer (the worker only uses this text for the
  first candidate).
"""

from __future__ import annotations

import re
from typing import Final

from pals_agent.explanations import ProofExplanation, _parse_explanation
from pals_agent.lean_templates import (
    TemplateBindingError,
    XSquaredBindings,
    render_x_squared_epsilon_delta,
)

FIXED_EXPLANATION_MODEL: Final = "pals.fixed-explanation.x-squared-epsilon-delta.v1"
FIXED_EXPLANATION_PROVIDER: Final = "pals"
SUPPORTED_LANGUAGES: Final = ("en", "ja", "zh-Hans", "zh-Hant")

_THEOREM = re.compile(
    r"^theorem (\S+) : Continuous \(fun (\S+) : ℝ => \2 \^ 2\) := by$", re.MULTILINE
)
_POINT_EPSILON = re.compile(r"^  intro (\S+) (\S+) hε$", re.MULTILINE)
_DELTA = re.compile(r"^  let (\S+) : ℝ := min 1 ", re.MULTILINE)
_MOVING = re.compile(r"^  · intro (\S+) hy$", re.MULTILINE)

# Inclusive physical line ranges of the rendered template (the structure never changes; the
# bindings only rename identifiers on a line).
_DELTA_LINES: Final = (8, 13)  # let δ; positivity of the denominator; δ > 0
_NEIGHBOURHOOD_LINES: Final = (14, 25)  # |x-a|<1, |x| ≤ |a|+1, |x+a| ≤ 2|a|+1
_ESTIMATE_LINES: Final = (26, 52)  # factorisation, the bound, the cancellation, the conclusion


def bindings_of_template_proof(lean_code: str) -> XSquaredBindings | None:
    """The names of ``lean_code`` when it is exactly the rendered x² template, else ``None``."""
    theorem = _THEOREM.search(lean_code)
    point_epsilon = _POINT_EPSILON.search(lean_code)
    delta = _DELTA.search(lean_code)
    moving = _MOVING.search(lean_code)
    if not (theorem and point_epsilon and delta and moving):
        return None
    bindings = XSquaredBindings(
        theorem=theorem.group(1),
        variable=theorem.group(2),
        point=point_epsilon.group(1),
        moving=moving.group(1),
        epsilon=point_epsilon.group(2),
        delta=delta.group(1),
    )
    try:
        rendered = render_x_squared_epsilon_delta(bindings)
    except TemplateBindingError:
        return None
    return bindings if lean_code.rstrip() == rendered.rstrip() else None


def _texts(language: str) -> dict[str, str]:
    """Prose per language.  ``@P@`` is the fixed point, ``@M@`` the moving point, ``@V@`` the
    function variable of the statement; every mathematical expression is inside ``$...$``."""
    delta_def = r"$\delta=\min\!\left(1,\ \dfrac{\varepsilon}{2|@P@|+1}\right)$"
    delta_cap = r"$\delta\le\dfrac{\varepsilon}{2|@P@|+1}$"
    chain = (
        r"$|@M@-@P@|(2|@P@|+1)<\dfrac{\varepsilon}{2|@P@|+1}\,(2|@P@|+1)=\varepsilon$"
    )
    if language == "en":
        return {
            "overview": r"Fix a real number $@P@$ and let $\varepsilon>0$ be arbitrary.",
            "delta_title": "Choice of delta",
            "delta": (
                f"Set {delta_def}. Since $\\varepsilon>0$ and $2|@P@|+1>0$, the quotient is "
                f"positive and the minimum of two positive numbers is positive, so "
                f"$\\delta>0$. Moreover $\\delta\\le 1$ and {delta_cap}."
            ),
            "near_title": "Points near the fixed point",
            "near": (
                r"Take any real $@M@$ with $|@M@-@P@|<\delta$. Because $\delta\le 1$, we have "
                r"$|@M@-@P@|<1$. By the triangle inequality, "
                r"$|@M@|=|(@M@-@P@)+@P@|\le|@M@-@P@|+|@P@|\le|@P@|+1$, and therefore "
                r"$|@M@+@P@|\le|@M@|+|@P@|\le 2|@P@|+1$."
            ),
            "est_title": "The estimate",
            "est": (
                r"Factoring the difference of squares gives $@M@^2-@P@^2=(@M@-@P@)(@M@+@P@)$, "
                r"so $|@M@^2-@P@^2|=|@M@-@P@|\,|@M@+@P@|\le|@M@-@P@|\,(2|@P@|+1)$. "
                f"Since $|@M@-@P@|<\\delta$ and {delta_cap}, and $2|@P@|+1>0$, we obtain "
                f"{chain}. Thus $|@M@^2-@P@^2|<\\varepsilon$."
            ),
            "conclusion": (
                r"As $\varepsilon>0$ was arbitrary, the function $@V@\mapsto @V@^2$ is "
                r"continuous at every real point $@P@$, hence continuous on $\mathbb{R}$."
            ),
        }
    if language == "ja":
        return {
            "overview": r"実数 $@P@$ を取り、$\varepsilon>0$ を任意に取る。",
            "delta_title": "δ の選び方",
            "delta": (
                f"{delta_def} と定める。$\\varepsilon>0$ かつ $2|@P@|+1>0$ なので商は正であり、"
                f"二つの正の数の最小値は正なので "
                f"$\\delta>0$ である。また $\\delta\\le 1$ であり、{delta_cap} である。"
            ),
            "near_title": "固定した点の近く",
            "near": (
                r"$|@M@-@P@|<\delta$ を満たす実数 $@M@$ を任意に取る。$\delta\le 1$ より "
                r"$|@M@-@P@|<1$ である。三角不等式から "
                r"$|@M@|=|(@M@-@P@)+@P@|\le|@M@-@P@|+|@P@|\le|@P@|+1$ であり、"
                r"さらに $|@M@+@P@|\le|@M@|+|@P@|\le 2|@P@|+1$ を得る。"
            ),
            "est_title": "評価",
            "est": (
                r"平方の差の因数分解 $@M@^2-@P@^2=(@M@-@P@)(@M@+@P@)$ より、"
                r"$|@M@^2-@P@^2|=|@M@-@P@|\,|@M@+@P@|\le|@M@-@P@|\,(2|@P@|+1)$ である。"
                f"ここで $|@M@-@P@|<\\delta$ かつ {delta_cap}、$2|@P@|+1>0$ なので、"
                f"{chain} となる。したがって $|@M@^2-@P@^2|<\\varepsilon$ が得られる。"
            ),
            "conclusion": (
                r"$\varepsilon>0$ は任意だったので、すべての実数 $@P@$ で連続であり、"
                r"したがって $@V@\mapsto @V@^2$ は $\mathbb{R}$ 上で連続である。"
            ),
        }
    simplified = language == "zh-Hans"

    def pick(simple: str, traditional: str) -> str:
        return simple if simplified else traditional

    return {
        "overview": pick(
            r"任取实数 $@P@$，并任取 $\varepsilon>0$。",
            r"任取實數 $@P@$，並任取 $\varepsilon>0$。",
        ),
        "delta_title": pick("δ 的取法", "δ 的取法"),
        "delta": pick(
            f"令 {delta_def}。因为 $\\varepsilon>0$ 且 $2|@P@|+1>0$，所以商为正，"
            f"两个正数的最小值为正，故 $\\delta>0$。并且 $\\delta\\le 1$，{delta_cap}。",
            f"令 {delta_def}。因為 $\\varepsilon>0$ 且 $2|@P@|+1>0$，所以商為正，"
            f"兩個正數的最小值為正，故 $\\delta>0$。並且 $\\delta\\le 1$，{delta_cap}。",
        ),
        "near_title": pick("固定点附近的点", "固定點附近的點"),
        "near": pick(
            r"任取满足 $|@M@-@P@|<\delta$ 的实数 $@M@$。由 $\delta\le 1$ 得 $|@M@-@P@|<1$。"
            r"由三角不等式，$|@M@|=|(@M@-@P@)+@P@|\le|@M@-@P@|+|@P@|\le|@P@|+1$，"
            r"于是 $|@M@+@P@|\le|@M@|+|@P@|\le 2|@P@|+1$。",
            r"任取滿足 $|@M@-@P@|<\delta$ 的實數 $@M@$。由 $\delta\le 1$ 得 $|@M@-@P@|<1$。"
            r"由三角不等式，$|@M@|=|(@M@-@P@)+@P@|\le|@M@-@P@|+|@P@|\le|@P@|+1$，"
            r"於是 $|@M@+@P@|\le|@M@|+|@P@|\le 2|@P@|+1$。",
        ),
        "est_title": pick("估计", "估計"),
        "est": pick(
            r"由平方差公式 $@M@^2-@P@^2=(@M@-@P@)(@M@+@P@)$，得 "
            r"$|@M@^2-@P@^2|=|@M@-@P@|\,|@M@+@P@|\le|@M@-@P@|\,(2|@P@|+1)$。"
            f"又 $|@M@-@P@|<\\delta$ 且 {delta_cap}，$2|@P@|+1>0$，所以 {chain}。"
            r"因此 $|@M@^2-@P@^2|<\varepsilon$。",
            r"由平方差公式 $@M@^2-@P@^2=(@M@-@P@)(@M@+@P@)$，得 "
            r"$|@M@^2-@P@^2|=|@M@-@P@|\,|@M@+@P@|\le|@M@-@P@|\,(2|@P@|+1)$。"
            f"又 $|@M@-@P@|<\\delta$ 且 {delta_cap}，$2|@P@|+1>0$，所以 {chain}。"
            r"因此 $|@M@^2-@P@^2|<\varepsilon$。",
        ),
        "conclusion": pick(
            r"由于 $\varepsilon>0$ 是任意的，函数在每个实数点 $@P@$ 处连续，"
            r"所以 $@V@\mapsto @V@^2$ 在 $\mathbb{R}$ 上连续。",
            r"由於 $\varepsilon>0$ 是任意的，函數在每個實數點 $@P@$ 處連續，"
            r"所以 $@V@\mapsto @V@^2$ 在 $\mathbb{R}$ 上連續。",
        ),
    }


def _reference(lean_code: str, span: tuple[int, int]) -> dict[str, object]:
    lines = lean_code.splitlines()
    start, end = span
    return {
        "start_line": start,
        "end_line": end,
        "excerpt": "\n".join(lines[start - 1 : end]),
    }


def fixed_explanation_for(lean_code: str, language: str) -> ProofExplanation | None:
    """The fixed explanation of ``lean_code`` when it is exactly the x² template, else ``None``.

    The result still has to pass the independent output review before anything is written.
    """
    if language not in SUPPORTED_LANGUAGES:
        return None
    bindings = bindings_of_template_proof(lean_code)
    if bindings is None:
        return None
    names = {"@P@": bindings.point, "@M@": bindings.moving, "@V@": bindings.variable}

    def named(text: str) -> str:
        for token, name in names.items():
            text = text.replace(token, name)
        return text

    texts = {key: named(value) for key, value in _texts(language).items()}
    payload = {
        "overview": texts["overview"],
        "sections": [
            {
                "id": "choose-delta",
                "title": texts["delta_title"],
                "summary": texts["delta"],
                "references": [_reference(lean_code, _DELTA_LINES)],
            },
            {
                "id": "neighbourhood",
                "title": texts["near_title"],
                "summary": texts["near"],
                "references": [_reference(lean_code, _NEIGHBOURHOOD_LINES)],
            },
            {
                "id": "estimate",
                "title": texts["est_title"],
                "summary": texts["est"],
                "references": [_reference(lean_code, _ESTIMATE_LINES)],
            },
        ],
        "conclusion": texts["conclusion"],
    }
    try:
        overview, sections, conclusion = _parse_explanation(
            payload, lean_code, language=language, require_linear_ending=True, strict_prose=True
        )
    except (KeyError, TypeError, ValueError):
        return None
    return ProofExplanation(
        overview=overview,
        sections=sections,
        conclusion=conclusion,
        model=FIXED_EXPLANATION_MODEL,
        provider=FIXED_EXPLANATION_PROVIDER,
        prompt="",
        raw_model_output="",
        elapsed_ms=0,
    )
