"""Deterministic, independently authored continuity-v1 collection material.

The collection deliberately records mathematical propositions, not text from a source book.  It
keeps the concrete formula AST small enough to render both the typed OpenMath term and its Lean
counterpart without accepting arbitrary source text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal
from xml.etree import ElementTree as ET

import rfc8785

from pals_agent.openmath import (
    OPENMATH_NAMESPACE,
    PALS_OPENMATH_CDBASE,
    canonicalize_continuity_v1_openmath_xml,
    continuity_v1_novelty_key,
)


FormulaKind = Literal["integer", "variable", "add", "sub", "mul", "neg", "pow", "div"]


@dataclass(frozen=True, slots=True)
class Formula:
    kind: FormulaKind
    value: int | str | None = None
    left: "Formula | None" = None
    right: "Formula | None" = None

    def __post_init__(self) -> None:
        if self.kind in {"integer", "variable"}:
            if self.value is None or self.left is not None or self.right is not None:
                raise ValueError("atomic formula is invalid")
        elif self.kind == "neg":
            if self.left is None or self.right is not None or self.value is not None:
                raise ValueError("negated formula is invalid")
        elif self.left is None or self.right is None or self.value is not None:
            raise ValueError("binary formula is invalid")


def integer(value: int) -> Formula:
    return Formula("integer", value=value)


def variable() -> Formula:
    return Formula("variable", value="x")


def add(left: Formula, right: Formula) -> Formula:
    return Formula("add", left=left, right=right)


def sub(left: Formula, right: Formula) -> Formula:
    return Formula("sub", left=left, right=right)


def mul(left: Formula, right: Formula) -> Formula:
    return Formula("mul", left=left, right=right)


def neg(value: Formula) -> Formula:
    return Formula("neg", left=value)


def power(base: Formula, exponent: int) -> Formula:
    return Formula("pow", left=base, right=integer(exponent))


def divide(left: Formula, right: Formula) -> Formula:
    return Formula("div", left=left, right=right)


X = variable()
ONE = integer(1)


@dataclass(frozen=True, slots=True)
class FormulaCard:
    slug: str
    display: str
    formula: Formula
    rational: bool = False


FORMULAS: tuple[FormulaCard, ...] = (
    FormulaCard("identity", "x", X),
    FormulaCard("negative_identity", "−x", neg(X)),
    FormulaCard("shift_plus_one", "x + 1", add(X, ONE)),
    FormulaCard("shift_minus_one", "x − 1", sub(X, ONE)),
    FormulaCard("double", "2x", mul(integer(2), X)),
    FormulaCard("affine_three_x_minus_two", "3x − 2", sub(mul(integer(3), X), integer(2))),
    FormulaCard("square", "x²", power(X, 2)),
    FormulaCard("square_plus_one", "x² + 1", add(power(X, 2), ONE)),
    FormulaCard("square_minus_x", "x² − x", sub(power(X, 2), X)),
    FormulaCard("square_plus_x_plus_one", "x² + x + 1", add(add(power(X, 2), X), ONE)),
    FormulaCard("cube", "x³", power(X, 3)),
    FormulaCard("cube_minus_x", "x³ − x", sub(power(X, 3), X)),
    FormulaCard("cube_plus_two_x", "x³ + 2x", add(power(X, 3), mul(integer(2), X))),
    FormulaCard("fourth_power", "x⁴", power(X, 4)),
    FormulaCard("fourth_plus_square", "x⁴ + x²", add(power(X, 4), power(X, 2))),
    FormulaCard("shifted_square", "(x + 1)²", power(add(X, ONE), 2)),
    FormulaCard("shifted_square_minus", "(x − 1)²", power(sub(X, ONE), 2)),
    FormulaCard("neighbor_product", "x(x + 1)", mul(X, add(X, ONE))),
    FormulaCard("symmetric_neighbor_product", "(x + 1)(x − 1)", mul(add(X, ONE), sub(X, ONE))),
    FormulaCard(
        "quadratic_affine", "2x² + 3x + 1", add(add(mul(integer(2), power(X, 2)), mul(integer(3), X)), ONE)
    ),
    FormulaCard("x_over_square_plus_one", "x/(x² + 1)", divide(X, add(power(X, 2), ONE)), True),
    FormulaCard("shifted_over_square_plus_one", "(x + 1)/(x² + 1)", divide(add(X, ONE), add(power(X, 2), ONE)), True),
    FormulaCard("square_minus_one_over_square_plus_one", "(x² − 1)/(x² + 1)", divide(sub(power(X, 2), ONE), add(power(X, 2), ONE)), True),
    FormulaCard("one_over_square_plus_one", "1/(x² + 1)", divide(ONE, add(power(X, 2), ONE)), True),
    FormulaCard("affine_over_square_plus_one", "(2x + 1)/(x² + 1)", divide(add(mul(integer(2), X), ONE), add(power(X, 2), ONE)), True),
)

LIMIT_CONSTANTS: tuple[int, ...] = (-6, -4, -3, -2, -1, 0, 1, 2, 3, 5, 7, 11)
SEQUENCE_CONSTANTS: tuple[int, ...] = (-5, -3, -1, 0, 1, 2, 3, 4, 6, 8, 13)


def _coverage(*, topic: str, context: str, representation: str) -> dict[str, Any]:
    return {
        "context": context,
        "operators": [],
        "prerequisites": [],
        "proof_schema": "concrete_instance",
        "representation": representation,
        "stratum": "instance",
        "topic": topic,
    }


GLOBAL_COVERAGE = _coverage(
    topic="continuity_on", context="continuity_on", representation="concrete_lambda"
)
POINT_COVERAGE = _coverage(
    topic="continuity_at", context="continuity_at", representation="concrete_lambda"
)
LIMIT_COVERAGE = _coverage(
    topic="limit_at", context="limit_at", representation="concrete_lambda"
)
SEQUENCE_COVERAGE = _coverage(
    topic="sequence_convergence", context="sequence", representation="sequence_lambda"
)


def _tag(name: str) -> str:
    return f"{{{OPENMATH_NAMESPACE}}}{name}"


def _oms(parent: ET.Element, cd: str, name: str, *, pals: bool = False) -> ET.Element:
    attributes = {"cd": cd, "name": name}
    if pals:
        attributes["cdbase"] = PALS_OPENMATH_CDBASE
    return ET.SubElement(parent, _tag("OMS"), attributes)


def _omi(parent: ET.Element, value: int) -> ET.Element:
    element = ET.SubElement(parent, _tag("OMI"))
    element.text = str(value)
    return element


def _omv(parent: ET.Element, name: str) -> ET.Element:
    return ET.SubElement(parent, _tag("OMV"), {"name": name})


def _formula_xml(parent: ET.Element, formula: Formula, *, variable_name: str = "x") -> None:
    if formula.kind == "integer":
        _omi(parent, int(formula.value))
        return
    if formula.kind == "variable":
        _omv(parent, variable_name)
        return
    application = ET.SubElement(parent, _tag("OMA"))
    names = {
        "add": "plus",
        "sub": "minus",
        "mul": "times",
        "neg": "unary_minus",
        "pow": "power",
        "div": "divide",
    }
    _oms(application, "arith1", names[formula.kind])
    assert formula.left is not None
    _formula_xml(application, formula.left, variable_name=variable_name)
    if formula.right is not None:
        _formula_xml(application, formula.right, variable_name=variable_name)


def _lambda(parent: ET.Element, body: Formula, *, sequence: bool = False) -> None:
    binding = ET.SubElement(parent, _tag("OMBIND"))
    if sequence:
        _oms(binding, "pals1", "sequence_lambda", pals=True)
        name = "n"
    else:
        _oms(binding, "fns1", "lambda")
        name = "x"
    variables = ET.SubElement(binding, _tag("OMBVAR"))
    _omv(variables, name)
    _formula_xml(binding, body, variable_name=name)


def _quantified_real(parent: ET.Element, name: str) -> ET.Element:
    binding = ET.SubElement(parent, _tag("OMBIND"))
    _oms(binding, "quant1", "forall")
    variables = ET.SubElement(binding, _tag("OMBVAR"))
    _omv(variables, name)
    return binding


def _canonical_xml(kind: str, formula: Formula) -> str:
    root = ET.Element(_tag("OMOBJ"), {"version": "2.0"})
    if kind == "global":
        application = ET.SubElement(root, _tag("OMA"))
        _oms(application, "pals1", "continuous_on", pals=True)
        _oms(application, "setname1", "R")
        _lambda(application, formula)
    elif kind == "point":
        binding = _quantified_real(root, "a")
        application = ET.SubElement(binding, _tag("OMA"))
        _oms(application, "pals1", "continuous_at", pals=True)
        _lambda(application, formula)
        _omv(application, "a")
    elif kind == "limit":
        binding = _quantified_real(root, "a")
        application = ET.SubElement(binding, _tag("OMA"))
        _oms(application, "pals1", "has_limit_at", pals=True)
        function = ET.SubElement(application, _tag("OMA"))
        _oms(function, "pals1", "constant_function", pals=True)
        _formula_xml(function, formula)
        _omv(application, "a")
        _formula_xml(application, formula)
    elif kind == "sequence":
        application = ET.SubElement(root, _tag("OMA"))
        _oms(application, "pals1", "converges_to", pals=True)
        _lambda(application, formula, sequence=True)
        _formula_xml(application, formula, variable_name="n")
    else:
        raise ValueError("unknown card kind")
    return canonicalize_continuity_v1_openmath_xml(ET.tostring(root, encoding="unicode"))


def _lean_formula(formula: Formula, *, variable_name: str = "x") -> str:
    if formula.kind == "integer":
        return str(int(formula.value))
    if formula.kind == "variable":
        return variable_name
    assert formula.left is not None
    if formula.kind == "neg":
        return f"(-({_lean_formula(formula.left, variable_name=variable_name)}))"
    assert formula.right is not None
    operators = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "^"}
    return (
        f"({_lean_formula(formula.left, variable_name=variable_name)} "
        f"{operators[formula.kind]} {_lean_formula(formula.right, variable_name=variable_name)})"
    )


def _proof_body(*, kind: str, rational: bool) -> str:
    if kind == "limit":
        return "by\n  intro a\n  exact tendsto_const_nhds"
    if kind == "sequence":
        return "by\n  exact tendsto_const_nhds"
    if not rational:
        return "by\n  fun_prop"
    if kind == "global":
        return "by\n  apply Continuous.div\n  · fun_prop\n  · fun_prop\n  · intro x\n    positivity"
    return "by\n  intro a\n  apply ContinuousAt.div\n  · fun_prop\n  · fun_prop\n  · positivity"


def _card(
    *,
    draft_id: str,
    statement: str,
    japanese: str,
    kind: str,
    formula: Formula,
    coverage: dict[str, Any],
    rational: bool = False,
) -> dict[str, Any]:
    canonical = _canonical_xml(kind, formula)
    formula_lean = _lean_formula(formula)
    if kind == "global":
        lean_target = f"Continuous (fun x : ℝ => {formula_lean})"
    elif kind == "point":
        lean_target = f"∀ (a : ℝ), ContinuousAt (fun x : ℝ => {formula_lean}) a"
    elif kind == "limit":
        lean_target = (
            f"∀ (a : ℝ), Filter.Tendsto (fun _ : ℝ => {formula_lean}) "
            f"(𝓝[≠] a) (𝓝 ({formula_lean}))"
        )
    elif kind == "sequence":
        lean_target = (
            f"Filter.Tendsto (fun _ : ℕ => {formula_lean}) Filter.atTop (𝓝 ({formula_lean}))"
        )
    else:
        raise ValueError("unknown card kind")
    return {
        "canonical_statement": statement,
        "coverage": coverage,
        "coverage_objective": coverage["topic"],
        "draft_id": draft_id,
        "english_expected_draft_id": draft_id,
        "english_query": f"Prove the concrete statement: {statement}",
        "hard_negative_expected_result": "no_match",
        "hard_negative_query": (
            f"May I conclude {statement} after replacing its function with an unrelated function?"
        ),
        "japanese_expected_draft_id": draft_id,
        "japanese_query": f"具体的な命題を証明したい: {japanese}",
        "lean_target": lean_target,
        "novelty_key": continuity_v1_novelty_key(coverage, canonical),
        "openmath_xml": canonical,
        "proof_strategy": (
            "Use the algebraic continuity rules for the displayed expression and discharge the "
            "positive quadratic denominator when it occurs."
            if kind in {"global", "point"}
            else "Use the constant-function convergence rule at the stated filter."
        ),
        "sketch_steps": (
            [
                "Read the displayed real expression as a composition of elementary continuous functions",
                "Apply the matching continuity rule",
                "For a quotient, prove the denominator is positive",
            ]
            if kind in {"global", "point"}
            else [
                "Recognize the function or sequence as constant",
                "Apply convergence of a constant map to its constant value",
            ]
        ),
        "_proof_body": _proof_body(kind=kind, rational=rational),
    }


def concrete_cards() -> tuple[dict[str, Any], ...]:
    cards: list[dict[str, Any]] = []
    for formula in FORMULAS:
        cards.append(
            _card(
                draft_id=f"cv1_global_{formula.slug}",
                statement=f"The real function x ↦ {formula.display} is continuous on the real line.",
                japanese=f"実関数 x ↦ {formula.display} は実数全体で連続である。",
                kind="global",
                formula=formula.formula,
                coverage=GLOBAL_COVERAGE,
                rational=formula.rational,
            )
        )
        cards.append(
            _card(
                draft_id=f"cv1_at_{formula.slug}",
                statement=f"For every real a, x ↦ {formula.display} is continuous at a.",
                japanese=f"任意の実数 a において、x ↦ {formula.display} は a で連続である。",
                kind="point",
                formula=formula.formula,
                coverage=POINT_COVERAGE,
                rational=formula.rational,
            )
        )
    for value in LIMIT_CONSTANTS:
        formula = integer(value)
        cards.append(
            _card(
                draft_id=f"cv1_limit_constant_{'neg_' + str(-value) if value < 0 else value}",
                statement=f"For every real a, the constant function with value {value} tends to {value} at a.",
                japanese=f"任意の実数 a で、値 {value} の定数関数の極限は {value} である。",
                kind="limit",
                formula=formula,
                coverage=LIMIT_COVERAGE,
            )
        )
    for value in SEQUENCE_CONSTANTS:
        formula = integer(value)
        cards.append(
            _card(
                draft_id=f"cv1_sequence_constant_{'neg_' + str(-value) if value < 0 else value}",
                statement=f"The constant real sequence with value {value} converges to {value}.",
                japanese=f"値 {value} の定数実数列は {value} に収束する。",
                kind="sequence",
                formula=formula,
                coverage=SEQUENCE_COVERAGE,
            )
        )
    if len(cards) != 73:
        raise AssertionError("the concrete continuity collection must contain 73 cards")
    return tuple(cards)


def build_catalog(existing_catalog: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return the 110-card no-LF-JCS payload and proof bodies keyed by card ID."""
    if set(existing_catalog) != {"cards", "coverage_profile", "schema_version"}:
        raise ValueError("existing catalog root is invalid")
    profile = existing_catalog["coverage_profile"]
    if not isinstance(profile, dict) or set(profile) != {"required_signatures", "schema_version"}:
        raise ValueError("existing coverage profile is invalid")
    cards = [dict(card) for card in existing_catalog["cards"]]
    concrete = concrete_cards()
    cards.extend({key: value for key, value in card.items() if key != "_proof_body"} for card in concrete)
    cards.sort(key=lambda card: card["draft_id"].encode("utf-8"))
    signatures = list(profile["required_signatures"])
    signatures.extend((GLOBAL_COVERAGE, POINT_COVERAGE, LIMIT_COVERAGE, SEQUENCE_COVERAGE))
    signatures.sort(key=rfc8785.dumps)
    if len(signatures) != len({rfc8785.dumps(item) for item in signatures}):
        raise ValueError("coverage signatures are not unique")
    if len(cards) != 110 or len({card["draft_id"] for card in cards}) != 110:
        raise ValueError("catalog must have exactly 110 unique cards")
    payload = {
        "cards": cards,
        "coverage_profile": {"required_signatures": signatures, "schema_version": profile["schema_version"]},
        "schema_version": existing_catalog["schema_version"],
    }
    proof_bodies = {card["draft_id"]: card["_proof_body"] for card in concrete}
    return payload, proof_bodies


def canonical_catalog_bytes(payload: dict[str, Any]) -> bytes:
    return rfc8785.dumps(payload)


def catalog_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_catalog_bytes(payload)).hexdigest()
