"""Closed figure template calls; generated figures that fail here are dropped, keeping the answer.

A figure illustrates an answer. Accepting a call or drawing it never verifies a claim, and a
call carries no coordinates, code or prose. pals-webfront `lib/figureCalls.ts` owns rendering;
`tests/fixtures/figure-calls-v1.json` holds the same vectors in each repository.
"""

from __future__ import annotations

import math
import re
from typing import Any

_LABEL = re.compile(r"[A-Za-z][0-9']?\Z", re.ASCII)
_STEP = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z", re.ASCII)
_MAX_MARKS = 12
_MAX_TERMS = 8
_TRIANGLE = ("a", "b", "c")
_SLOTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "triangle": (_TRIANGLE, ()),
    "congruent-triangles": ((*_TRIANGLE, "d", "e", "f"), ()),
    "similar-triangles": ((*_TRIANGLE, "d", "e", "f"), ()),
    "triangle-center": ((*_TRIANGLE, "center"), ()),
    "ceva": ((*_TRIANGLE, "d", "e", "f", "p"), ()),
    "menelaus": ((*_TRIANGLE, "d", "e", "f"), ()),
    "inscribed-angle": (("chord_start", "chord_end", "on_arc_1"), ("on_arc_2", "center")),
    "tangent-chord": (("touch", "chord_end", "on_arc", "tangent_point"), ()),
    "power-of-point": (("p", "a", "b", "c"), ("d",)),
    "cyclic-quadrilateral": (("a", "b", "c", "d"), ()),
    "tangent-lengths": (("p", "touch_1", "touch_2"), ("center",)),
}
_REQUIRED_CHOICE: dict[str, tuple[str, tuple[str, ...]]] = {
    "triangle": ("shape", ("scalene", "isosceles", "right", "equilateral")),
    "triangle-center": (
        "kind",
        ("circumcenter", "incenter", "centroid", "orthocenter", "excenter"),
    ),
    "power-of-point": ("kind", ("chords", "secants", "tangent_secant")),
}
_CRITERIA = ("sss", "sas", "asa", "aa")
_MARK_ARITY = {
    "equal_length": (2, 2, 4),
    "equal_angle": (3, 2, 4),
    "right_angle": (3, 1, 4),
    "parallel": (2, 2, 2),
}


class FigureCallError(ValueError):
    """The call is outside the closed catalog."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FigureCallError(reason)


def _exact(value: Any, required: tuple[str, ...], optional: tuple[str, ...], reason: str) -> None:
    _require(isinstance(value, dict), reason)
    keys = set(value)
    _require(set(required) <= keys <= {*required, *optional}, reason)


def _finite(value: Any, reason: str) -> float:
    _require(type(value) in (int, float), reason)
    number = float(value)
    _require(math.isfinite(number) and abs(number) <= 1e6, reason)
    return number


def _numbers(value: Any, minimum: int, maximum: int, reason: str) -> list[float]:
    _require(isinstance(value, list) and minimum <= len(value) <= maximum, reason)
    return [_finite(item, reason) for item in value]


def _interval(value: Any, reason: str) -> tuple[float, float]:
    low, high = _numbers(value, 2, 2, reason)
    _require(high - low >= 0.01, reason)
    return low, high


def _polynomial(coefficients: list[float], x: float) -> float:
    total = 0.0
    for coefficient in reversed(coefficients):
        total = total * x + coefficient
    return total


def _validate_graph(template: str, parameters: Any) -> None:
    derivative = template == "polynomial-derivative"
    _exact(
        parameters,
        ("coefficients", "domain", "range", *(("anchor", "offsets") if derivative else ())),
        (),
        "graph parameters",
    )
    coefficients = _numbers(parameters["coefficients"], 1, _MAX_TERMS, "coefficients")
    domain = _interval(parameters["domain"], "domain")
    y_range = _interval(parameters["range"], "range")
    if not derivative:
        return
    anchor = _finite(parameters["anchor"], "anchor")
    offsets = _numbers(parameters["offsets"], 2, 12, "offsets")
    _require(all(h != 0 and (h > 0) == (offsets[0] > 0) for h in offsets), "offsets")

    def visible(x: float) -> bool:
        y = _polynomial(coefficients, x)
        return domain[0] <= x <= domain[1] and y_range[0] <= y <= y_range[1]

    _require(visible(anchor) and all(visible(anchor + h) for h in offsets), "offsets visible")


def _optional_list(value: Any, maximum: int, reason: str) -> list[Any]:
    if value is None:
        return []
    _require(isinstance(value, list) and len(value) <= maximum, reason)
    return list(value)


def _validate_geometry(template: str, parameters: Any) -> None:
    required_choice = _REQUIRED_CHOICE.get(template)
    required = ("labels", *((required_choice[0],) if required_choice else ()))
    optional = ["marks", "segments"]
    if template == "triangle":
        optional.append("extra_points")
    if template in {"congruent-triangles", "similar-triangles"}:
        optional.append("criterion")
    _exact(parameters, required, tuple(optional), "geometry parameters")
    if required_choice:
        _require(parameters[required_choice[0]] in required_choice[1], required_choice[0])
    criterion = parameters.get("criterion")
    _require(criterion is None or criterion in _CRITERIA, "criterion")

    slots_required, slots_optional = _SLOTS[template]
    labels = parameters["labels"]
    _exact(labels, slots_required, slots_optional, "labels")
    if template == "power-of-point":
        _require((parameters["kind"] == "tangent_secant") != ("d" in labels), "labels d")
    for label in labels.values():
        _require(isinstance(label, str) and _LABEL.fullmatch(label) is not None, "label grammar")
    known = set(labels.values())
    _require(len(known) == len(labels), "duplicate label")

    for extra in _optional_list(parameters.get("extra_points"), 4, "extra_points"):
        _exact(extra, ("label", "on", "t"), (), "extra point")
        label = extra["label"]
        _require(
            isinstance(label, str) and _LABEL.fullmatch(label) is not None and label not in known,
            "extra point label",
        )
        on = extra["on"]
        _require(
            isinstance(on, list)
            and len(on) == 2
            and all(isinstance(item, str) and item in known for item in on)
            and on[0] != on[1],
            "extra point on",
        )
        t = _finite(extra["t"], "extra point t")
        _require(0 < t < 1, "extra point t")
        known.add(label)

    def group(value: Any, size: int, reason: str) -> None:
        _require(
            isinstance(value, list)
            and len(value) == size
            and all(isinstance(item, str) and item in known for item in value)
            and len(set(value)) == size,
            reason,
        )

    for segment in _optional_list(parameters.get("segments"), 12, "segments"):
        group(segment, 2, "segment")
    for mark in _optional_list(parameters.get("marks"), _MAX_MARKS, "marks"):
        _exact(mark, ("icon", "at", "claim"), ("step",), "mark")
        _require(mark["icon"] in _MARK_ARITY, "mark icon")
        size, minimum, maximum = _MARK_ARITY[mark["icon"]]
        _require(isinstance(mark["at"], list) and minimum <= len(mark["at"]) <= maximum, "mark at")
        for item in mark["at"]:
            group(item, size, "mark group")
        _require(mark["claim"] in ("given", "conclusion"), "mark claim")
        if "step" in mark:
            step = mark["step"]
            _require(isinstance(step, str) and _STEP.fullmatch(step) is not None, "mark step")


def validate_figure_call(value: Any) -> None:
    """Raise FigureCallError unless ``value`` is a call in the closed catalog."""
    _exact(value, ("version", "template", "parameters"), (), "call")
    _require(type(value["version"]) is int and value["version"] == 1, "version")
    template = value["template"]
    _require(isinstance(template, str), "template")
    if template in {"polynomial", "polynomial-derivative"}:
        _validate_graph(template, value["parameters"])
    else:
        _require(template in _SLOTS, "template")
        _validate_geometry(template, value["parameters"])


def figure_steps(call: dict[str, Any]) -> list[str]:
    template = call["template"]
    if template == "polynomial":
        return []
    if template == "polynomial-derivative":
        count = len(call["parameters"]["offsets"])
        return [
            "continuity"
            if index == 0
            else "limit"
            if index == count - 1
            else "secant"
            if index == 1
            else f"step-{index + 1}"
            for index in range(count)
        ]
    steps: dict[str, None] = {}
    for mark in call["parameters"].get("marks") or []:
        if "step" in mark:
            steps[mark["step"]] = None
    return list(steps)


def validate_figure_bindings(value: Any, call: dict[str, Any]) -> None:
    _require(isinstance(value, list) and len(value) <= _MAX_MARKS, "bindings")
    steps = figure_steps(call)
    seen: set[int] = set()
    for binding in value:
        _exact(binding, ("step_id", "paragraph"), (), "binding")
        _require(binding["step_id"] in steps, "binding step")
        paragraph = binding["paragraph"]
        _require(type(paragraph) is int and 0 <= paragraph <= 199, "binding paragraph")
        _require(paragraph not in seen, "duplicate binding")
        seen.add(paragraph)


FIGURE_INSTRUCTION = """Add one figure whenever the answer concerns plane geometry that a template
below covers, or the graph of a polynomial; otherwise use null. A figure only illustrates and
proves nothing. Call a template and do not describe the figure in the text. Never give coordinates,
code, colors or captions.
Example: {"version":1,"template":"inscribed-angle","parameters":{"labels":{"chord_start":"A",
"chord_end":"B","on_arc_1":"P","on_arc_2":"Q"},"marks":[{"icon":"equal_angle","at":[["A","P","B"],
["A","Q","B"]],"claim":"conclusion","step":"angles"}]},"bindings":[{"step_id":"angles","paragraph":1}]}
Geometry parameters always include "labels" mapping every required slot to a point name of the
answer, matching [A-Za-z][0-9']?. Add "marks" for what the mathematics states: equal_length and
parallel take vertex pairs; equal_angle and right_angle take triples with the vertex in the middle;
"at" lists groups even for one, as in [["A","M","B"]]; claim is given or conclusion.
"segments" optionally adds [[label,label]]. A mark's optional step
names a stage; a binding links that step_id to a zero-based paragraph of the answer text, and
bindings may be empty.
T and slots: triangle a b c, requires "shape": scalene|isosceles|right|equilateral, optional
"extra_points":[{"label":L,"on":[L1,L2],"t":0..1 exclusive}]; congruent-triangles and
similar-triangles a b c d e f in correspondence order, optional "criterion": sss|sas|asa|aa;
triangle-center a b c center, requires "kind":
circumcenter|incenter|centroid|orthocenter|excenter; ceva a b c d e f p; menelaus a b c d e f;
inscribed-angle chord_start chord_end on_arc_1, optional on_arc_2 center; tangent-chord touch
chord_end on_arc tangent_point; power-of-point requires "kind": chords|secants|tangent_secant, p a b
c d (tangent_secant: p a b c, c is the tangent point); cyclic-quadrilateral a b c d; tangent-lengths
p touch_1 touch_2, optional center.
Graph templates are "polynomial" and "polynomial-derivative". The template name is the top-level
"template" value; there is no "polynomial" key anywhere inside "parameters". The keys of
"parameters" are exactly "coefficients" (numbers c0,c1,..., lowest degree first, at most 8),
"domain":[lo,hi] and "range":[lo,hi], all three directly in "parameters" (no nesting, no "labels"
or "marks"). Only numbers, never expressions. For x^3-3x+2 use
{"version":1,"template":"polynomial","parameters":{"coefficients":[2,-3,0,1],"domain":[-3,3],
"range":[-2,8]}}. Wrong: "parameters":{"polynomial":{"coefficients":[2,-3,0,1],...}} and
"parameters":{"polynomial":"x^3-3x+2"}.
polynomial-derivative also takes "anchor":x and "offsets":[h1,...] (same sign, nonzero, largest
first; steps are continuity, secant, limit), again directly in "parameters"; keep the anchor and
anchor+h visible inside domain and range.
For geometry, "labels" values must be point names that occur in the Lean source (or, in a chat
answer, in the text); the figure is dropped when any label, including each extra point, does not
occur there. Copy each name with the spelling and case used there (a, b, c if the source names
its points or vectors in lowercase), never new letters; if the source has no usable point names,
use null."""


def _wrap_single_mark_groups(call: dict[str, Any]) -> None:
    """Models often flatten the one-group form, which is unambiguous to repair."""
    parameters = call.get("parameters")
    marks = parameters.get("marks") if isinstance(parameters, dict) else None
    for mark in marks if isinstance(marks, list) else []:
        at = mark.get("at") if isinstance(mark, dict) else None
        if isinstance(at, list) and at and all(isinstance(item, str) for item in at):
            mark["at"] = [at]


def split_figure(value: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate a generated figure and separate its call from its paragraph bindings."""
    _require(isinstance(value, dict), "figure")
    call = {key: item for key, item in value.items() if key != "bindings"}
    _wrap_single_mark_groups(call)
    validate_figure_call(call)
    bindings = value.get("bindings", [])
    try:
        validate_figure_bindings(bindings, call)
    except FigureCallError:
        # Paragraph links are optional, so a bad one costs only the hover link.
        return call, []
    return call, bindings


def figure_labels(call: dict[str, Any]) -> set[str]:
    parameters = call["parameters"]
    labels = set((parameters.get("labels") or {}).values())
    labels.update(extra["label"] for extra in parameters.get("extra_points") or [])
    return labels


def labels_occur_in(call: dict[str, Any], source: str) -> bool:
    """Whether every point name appears in ``source``. Binds names only, not the mathematics."""
    return all(
        re.search(rf"(?<![a-z\\]){re.escape(label)}(?![a-z])", source) is not None
        for label in figure_labels(call)
    )
