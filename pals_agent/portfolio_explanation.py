"""Deterministic learner-facing explanation for a portfolio answer (no model call).

A template is only honest when the closing step corresponds to ONE nameable mathematical fact:
a cited Mathlib theorem (``exact?``), or a decision procedure whose reason is the same for
every statement it closes (``ring`` = equal normal forms, ``positivity`` = signs of sums,
products and powers, ...).  ``simp``, ``simp_all``, ``aesop``, ``grind``, ``bound``, ``gcongr``
and the combinators use a changing set of many lemmas, so no template can say why the statement
is true; those closes return ``None`` and the caller falls back to a model-written explanation.
The same holds when the request asks for a method (epsilon-delta, induction, contradiction) or a
justification: the template shows the cited fact, not the requested method.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# tactic -> (statement-shape predicate name, ja sentence, en sentence)
_HEADS_FUN_PROP: Final = (
    "Continuous",
    "ContinuousOn",
    "ContinuousAt",
    "Differentiable",
    "DifferentiableAt",
    "Measurable",
    "StronglyMeasurable",
)


@dataclass(frozen=True, slots=True)
class LemmaInfo:
    name: str
    type_text: str = ""
    doc: str = ""
    call: str = ""  # the `exact …` application Lean found, e.g. "HasDerivAt.fun_add hf hg"


def _depth_zero(text: str, token: str) -> list[int]:
    depth, found = 0, []
    for index, ch in enumerate(text):
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth -= 1
        elif depth == 0 and text.startswith(token, index):
            found.append(index)
    return found


def _body(formal: str) -> str:
    """The conclusion after the leading ∀ prefixes and the last top-level → (shape tests only)."""
    text = formal.strip()
    while text.startswith("∀"):
        commas = _depth_zero(text, ",")
        if not commas:
            break
        text = text[commas[0] + 1 :].strip()
    arrows = _depth_zero(text, "→")
    return text[arrows[-1] + 1 :].strip() if arrows else text


def honest(tactic: str, formal: str) -> bool:
    """Whether a fixed template can truthfully say why ``formal`` holds, given the closer."""
    body = _body(formal)
    if tactic == "exact?":
        return True
    if tactic == "positivity":
        return re.match(r"^(0\s*[≤<]|.+\s*[>≥]\s*0\b|.+\s*≠\s*0\b|0\s*≠)", body) is not None
    if tactic in ("ring", "field_simp_ring"):
        return "=" in body and "≤" not in body and "<" not in body and "↔" not in body
    if tactic == "norm_num":
        return "∀" not in formal and "∃" not in formal and re.search(r"\b[a-z]\b", body) is None
    if tactic in ("decide", "omega", "tauto", "linarith", "nlinarith"):
        return True
    if tactic in ("fun_prop", "continuity", "measurability"):
        return any(body.lstrip("¬ (").startswith(head) for head in _HEADS_FUN_PROP)
    return False


_TACTIC_TEXT: Final = {
    "positivity": (
        "各項・各因子の符号を、和・積・冪・指数関数などの規則から順に判定すると、式が非負(正)になります。",
        "The sign of each term and factor is determined by the rules for sums, products, powers "
        "and the exponential, which shows the expression is nonnegative (positive).",
    ),
    "ring": (
        "両辺を可換環の計算規則で多項式の正規形に直すと、同じ式になります。",
        "Rewriting both sides to their normal form with the commutative-ring rules gives the "
        "same expression.",
    ),
    "field_simp_ring": (
        "分母を払って多項式の等式に直し、両辺を正規形にすると同じ式になります。",
        "Clearing denominators reduces the claim to a polynomial identity, and both sides have the "
        "same normal form.",
    ),
    "norm_num": (
        "数値だけの式なので、数の計算規則で両辺を評価すると主張が成り立ちます。",
        "All quantities are numerals, so evaluating them with the arithmetic rules verifies the "
        "claim.",
    ),
    "decide": (
        "有限個の場合の判定で、すべての場合を計算して確かめられます。",
        "This is a finite decidable statement, verified by computing every case.",
    ),
    "omega": (
        "自然数・整数の一次の不等式・等式だけなので、一次算術の判定手続きで示せます。",
        "Only linear (in)equalities over the naturals or integers occur, so the linear-arithmetic "
        "decision procedure proves it.",
    ),
    "linarith": (
        "仮定の一次結合から結論が導かれます。",
        "The conclusion follows as a linear combination of the hypotheses.",
    ),
    "nlinarith": (
        "仮定とその積の一次結合から結論が導かれます。",
        "The conclusion follows as a linear combination of the hypotheses and their products.",
    ),
    "tauto": (
        "命題論理だけで決まる主張(論理的に常に真)です。",
        "The statement is a propositional tautology.",
    ),
    "fun_prop": (
        "連続性(微分可能性・可測性)は、和・積・合成に対して保たれるという規則を、式の構造に沿って適用すると示せます。",
        "Continuity (differentiability, measurability) is preserved by sums, products and "
        "compositions; applying these rules along the structure of the expression proves it.",
    ),
    "continuity": (
        "連続関数の和・積・合成は連続である、という規則を式の構造に沿って適用すると示せます。",
        "Sums, products and compositions of continuous functions are continuous; applying these "
        "rules along the structure of the expression proves it.",
    ),
    "measurability": (
        "可測関数の和・積・合成は可測である、という規則を式の構造に沿って適用すると示せます。",
        "Sums, products and compositions of measurable functions are measurable; applying these "
        "rules along the structure of the expression proves it.",
    ),
}


def render(language: str, formal: str, tactic: str, lemma: LemmaInfo | None = None) -> str | None:
    """Template text in the request language, or ``None`` when no honest template exists."""
    if not honest(tactic, formal):
        return None
    ja = language == "ja"
    parts = [
        (
            "Lean(Mathlib)で次の命題を形式的に検証しました。"
            if ja
            else "The following statement was verified formally in Lean (Mathlib)."
        ),
        f"`{formal}`",
    ]
    if tactic == "exact?":
        if lemma is None or not lemma.name:
            return None
        parts.append(
            f"これは Mathlib の定理 `{lemma.name}` から直接得られます。"
            if ja
            else f"It follows directly from the Mathlib theorem `{lemma.name}`."
        )
        if lemma.type_text:
            parts.append(
                f"定理の主張: `{lemma.type_text}`"
                if ja
                else f"The theorem states: `{lemma.type_text}`"
            )
        if lemma.doc:
            parts.append(
                f"説明(Mathlib の文書): {lemma.doc}"
                if ja
                else f"Documentation (Mathlib): {lemma.doc}"
            )
        if lemma.call:
            parts.append(
                f"上の命題は、この定理に `{lemma.call}` を当てはめたものです。"
                if ja
                else f"The statement is this theorem applied as `{lemma.call}`."
            )
    else:
        ja_text, en_text = _TACTIC_TEXT[tactic]
        parts.append(ja_text if ja else en_text)
    parts.append(
        "この説明は検証に使った規則を述べたもので、特定の証明方法の指定には対応していません。"
        if ja
        else "This explanation states the rule used by the verification; it does not follow a "
        "specific proof method."
    )
    return "\n\n".join(parts)


_DOC_MARK = "PALS_DOC:"


def lemma_probe_source(name: str) -> str:
    """Lean commands that print the type and docstring of a cited lemma (no side effects)."""
    safe = re.fullmatch(r"[A-Za-z_][\w'.]*", name)
    if safe is None:
        raise ValueError("unsafe lemma name")
    return (
        f"#check @{name}\n"
        "open Lean Elab Command in\n"
        "#eval show CommandElabM Unit from do\n"
        f"  let d ← findDocString? (← getEnv) `{name}\n"
        f'  logInfo m!"{_DOC_MARK}{{d.getD ""}}"\n'
    )


def parse_lemma_probe(name: str, output: str, call: str = "") -> LemmaInfo:
    """Extract the type (``#check`` output) and docstring from the probe's messages."""
    type_text, doc = "", ""
    if _DOC_MARK in output:
        doc = output.split(_DOC_MARK, 1)[1].split("\n\n", 1)[0].strip()
    head = output.split(_DOC_MARK, 1)[0]
    if f"{name} :" in head:
        type_text = " ".join(head.split(f"{name} :", 1)[1].split())
    elif head.strip():
        type_text = " ".join(head.split())
    return LemmaInfo(name, type_text[:600], " ".join(doc.split())[:600], call[:200])
