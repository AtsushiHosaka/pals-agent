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
