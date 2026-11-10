import json
from pathlib import Path

import pytest

from pals_agent.figure_calls import (
    FigureCallError,
    figure_steps,
    labels_occur_in,
    split_figure,
    validate_figure_bindings,
    validate_figure_call,
)

VECTORS = json.loads((Path(__file__).parents[1] / "fixtures/figure-calls-v1.json").read_text())


@pytest.mark.parametrize("call", VECTORS["valid"], ids=lambda call: call["template"])
def test_accepts_the_shared_catalog(call):
    validate_figure_call(call)


@pytest.mark.parametrize("item", VECTORS["invalid"], ids=lambda item: item["name"])
def test_rejects_outside_the_shared_catalog(item):
    with pytest.raises(FigureCallError):
        validate_figure_call(item["call"])


def test_booleans_are_not_numbers():
    with pytest.raises(FigureCallError):
        validate_figure_call(
            {
                "version": 1,
                "template": "polynomial",
                "parameters": {"coefficients": [True], "domain": [0, 1], "range": [0, 2]},
            }
        )


def test_bindings_only_reach_steps_the_call_exposes():
    call = VECTORS["valid"][0]
    assert figure_steps(call) == ["given", "goal"]
    validate_figure_bindings([{"step_id": "goal", "paragraph": 1}], call)
    with pytest.raises(FigureCallError):
        validate_figure_bindings([{"step_id": "other", "paragraph": 1}], call)
    with pytest.raises(FigureCallError):
        validate_figure_bindings(
            [{"step_id": "goal", "paragraph": 1}, {"step_id": "given", "paragraph": 1}], call
        )


def test_split_figure_separates_the_call_from_its_bindings():
    call = VECTORS["valid"][0]
    bindings = [{"step_id": "goal", "paragraph": 2}]
    assert split_figure({**call, "bindings": bindings}) == (call, bindings)
    assert split_figure(call) == (call, [])


def test_a_flattened_single_mark_group_is_repaired():
    call = {
        "version": 1,
        "template": "triangle",
        "parameters": {
            "shape": "isosceles",
            "labels": {"a": "A", "b": "B", "c": "C"},
            "extra_points": [{"label": "M", "on": ["B", "C"], "t": 0.5}],
            "marks": [{"icon": "right_angle", "at": ["A", "M", "B"], "claim": "conclusion"}],
        },
    }
    repaired, _ = split_figure(call)
    assert repaired["parameters"]["marks"][0]["at"] == [["A", "M", "B"]]


def test_a_bad_paragraph_link_costs_only_the_link():
    call = VECTORS["valid"][0]
    assert split_figure({**call, "bindings": [{"step_id": "nope", "paragraph": 1}]}) == (call, [])


def test_labels_bind_to_point_names_not_to_other_words():
    call = VECTORS["valid"][10]
    assert labels_occur_in(call, r"$\angle APB=\angle AQB$ with center $O$")
    assert labels_occur_in(call, "theorem t (A B P Q O : P') : True")
    # Lean's `Add` and TeX's `\Omega` must not count as the points A and O.
    assert not labels_occur_in(call, r"Add Bool Prop Quot $\Omega$")


def test_instruction_pins_the_graph_parameter_shape():
    from pals_agent.figure_calls import FIGURE_INSTRUCTION

    graph = {
        "version": 1,
        "template": "polynomial",
        "parameters": {"coefficients": [2, -3, 0, 1], "domain": [-3, 3], "range": [-2, 8]},
    }
    validate_figure_call(graph)
    # The documented good example is exactly what the validator accepts.
    compact = FIGURE_INSTRUCTION.replace("\n", "")
    assert json.dumps(graph, separators=(",", ":")) in compact
    assert 'there is no "polynomial" key' in compact
    # The wrong nesting that models produced is rejected, never repaired.
    nested = {
        "version": 1,
        "template": "polynomial",
        "parameters": {"polynomial": graph["parameters"]},
    }
    with pytest.raises(FigureCallError):
        validate_figure_call(nested)
    assert "occur in the Lean source" in compact


def test_explanation_prompt_schema_lists_the_figure_key_and_polynomial_trigger():
    from pals_agent.explanations import _explanation_prompt

    prompt = _explanation_prompt(
        theorem_statement="Let p(x)=x^3-3x+2. Show p(x) >= 0 for x >= -2.",
        lean_code="theorem t (x : ℝ) (h : -2 ≤ x) : 0 ≤ x ^ 3 - 3 * x + 2 := by\n  nlinarith",
        language="en",
    )
    schema = prompt.split("Return exactly one JSON object with this schema:")[1]
    # A schema without the key led Luna to omit the figure on every polynomial statement.
    assert '"figure":' in schema.split("Write all learner-facing prose")[0]
    assert "explicit polynomial" in prompt
