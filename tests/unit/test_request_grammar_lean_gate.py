"""Every proposition the vocabulary table can produce is well-formed Lean.

``test_...`` without Lean renders every function x property combination and checks its shape and
the closed proposition syntax.  The opt-in test sends the same propositions to the pinned
Lean 4.32.0-rc1 with Mathlib (one process, one ``#check (p : Prop)`` per line, no ``lake``) and
requires that none is rejected and that every power elaborates with a natural exponent.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from pals_agent.recipe_instantiation import check_proposition
from pals_agent.request_proposition import parse_request
from tests.unit.test_recipe_elaboration_lean import PINNED, mathlib_environment, needs_lean
from tests.unit.test_request_grammar_widened import (
    FRAGMENTS,
    LEAN_PROPERTY,
    PROPERTY_IDS,
    PROPERTY_WORDS,
    _extended,
)

DEC = r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,6})?"
VARIABLES = "stuvwxy"
PREFIXES = (
    r"Continuous", r"UniformContinuous", r"Differentiable ℝ", r"StrictMono", r"Monotone",
    r"Function\.Injective",
)


@dataclass(frozen=True)
class Combination:
    label: str
    function_id: str
    property_id: str
    variable: str
    proposition: str


def _body_pattern(function_id: str, v: str) -> str:
    return {
        "power": rf"{v} \^ [0-9]{{1,9}}",
        "exp": rf"Real\.exp {v}",
        "sin": rf"Real\.sin {v}",
        "cos": rf"Real\.cos {v}",
        "abs": rf"\|{v}\|",
        "sqrt": rf"Real\.sqrt {v}",
        "scaled": rf"{DEC} \* {v}",
        "affine": rf"(?:{DEC} \* {v} \+ {DEC}|{v} \+ {DEC}|{DEC} \+ {DEC} \* {v}|{DEC} \+ {v})",
        "monomial": rf"{DEC} \* {v} \^ [0-9]{{1,9}}",
    }[function_id]


def _fragment_for(function_id: str, v: str) -> str | None:
    return {
        "power": f"{v}^2", "exp": f"e^{v}", "sin": f"sin({v})", "cos": f"cos({v})",
        "abs": f"|{v}|", "sqrt": f"√{v}", "scaled": f"3*{v}", "affine": f"2*{v} + 1",
        "monomial": f"3*{v}^2",
    }[function_id]


def combinations() -> list[Combination]:
    """Everything the packaged table (and the table extended by the monomial row) can produce."""
    extended = _extended()
    found: dict[str, Combination] = {}
    sources: list[tuple[str, str]] = [(fid, frag) for fid, frag, _ in FRAGMENTS]
    sources += [("power", "x^0"), ("power", "x^123456789"), ("scaled", "123456789.123456x"),
                ("affine", "0.000001x + 987654321.5"), ("monomial", "2.5x^3"),
                ("monomial", "7*x^0")]
    for letter in VARIABLES:
        sources += [(fid, frag) for fid in
                    ("power", "exp", "sin", "cos", "abs", "sqrt", "scaled", "affine", "monomial")
                    if (frag := _fragment_for(fid, letter)) is not None]
    for function_id, fragment in sources:
        for prop in PROPERTY_IDS:
            text = f"Prove that {fragment} is {PROPERTY_WORDS[prop][1]}."
            parsed = parse_request(text, grammar=extended)
            if parsed is None:
                continue  # e.g. the letter s with a glued coefficient, which the table refuses
            assert parsed.function_id == function_id, text
            found.setdefault(
                parsed.proposition,
                Combination(text, function_id, prop, parsed.variable, parsed.proposition),
            )
    return list(found.values())


def test_the_enumeration_reaches_every_function_property_pair_and_letter() -> None:
    items = combinations()
    pairs = {(c.function_id, c.property_id) for c in items}
    functions = {"power", "exp", "sin", "cos", "abs", "sqrt", "scaled", "affine", "monomial"}
    assert pairs == {(f, p) for f in functions for p in PROPERTY_IDS}
    for function_id in functions - {"scaled", "affine", "monomial"}:
        assert {c.variable for c in items if c.function_id == function_id} == set(VARIABLES)
    for function_id in ("scaled", "affine", "monomial"):
        assert set("tuvwxy") <= {c.variable for c in items if c.function_id == function_id}
    assert len(items) > 400


def test_every_combination_has_the_expected_shape_without_lean() -> None:
    for item in combinations():
        v = item.variable
        body = _body_pattern(item.function_id, v)
        shape = re.compile("(?:" + "|".join(PREFIXES) + rf") \(fun {v} : ℝ => {body}\)")
        assert shape.fullmatch(item.proposition), item
        template = LEAN_PROPERTY[item.property_id].split(" (fun")[0]
        assert item.proposition.startswith(template + " (fun "), item
        assert check_proposition(item.proposition) == item.proposition, item
        assert item.proposition.count("(") == item.proposition.count(")"), item


def test_the_enumerated_propositions_are_distinct_and_single_line() -> None:
    items = combinations()
    assert len({c.proposition for c in items}) == len(items)
    assert all("\n" not in c.proposition for c in items)


HEADER = ["import Mathlib", "set_option pp.numericTypes true"]


@needs_lean
@pytest.mark.skipif(mathlib_environment() is None, reason="no built Mathlib for v4.32.0-rc1")
def test_pinned_lean_elaborates_every_combination_as_a_proposition(tmp_path: Path) -> None:
    items = combinations()
    control = "Continuous (fun x : ℝ => Real.notAFunction x)"
    lines = HEADER + [f"#check (({item.proposition}) : Prop)" for item in items]
    lines.append(f"#check (({control}) : Prop)")
    (tmp_path / "Main.lean").write_text("\n".join(lines) + "\n", encoding="utf-8")
    done = subprocess.run(
        [str(PINNED), "Main.lean"], cwd=tmp_path, env=mathlib_environment(),
        capture_output=True, text=True, timeout=900,
    )
    errors = [line for line in (done.stdout + done.stderr).splitlines() if ": error" in line]
    first_check_line = len(HEADER) + 1
    rejected = []
    for line in errors:
        number = int(line.split(":")[1])
        index = number - first_check_line
        rejected.append(items[index].proposition if 0 <= index < len(items) else line)
    # The control proves that a rejection would be seen: exactly it, and nothing else, fails.
    assert len(errors) == 1 and "notAFunction" in errors[0], rejected
    # Every power in every combination elaborates with a natural exponent (never a real one).
    shown = [line for line in done.stdout.splitlines() if "^" in line]
    assert shown
    for line in shown:
        assert re.search(r"\^ \([0-9]+ : ℕ\)", line), line
        assert not re.search(r"\^ \([0-9.]+ : ℝ\)", line), line
