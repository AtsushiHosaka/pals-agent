"""Deterministic request -> Lean proposition -> Recipe binding, driven by a vocabulary table.

The Recipe instantiation route needs the Lean proposition of the learner's request.  Until now a
model proposed it.  This module derives it by itself for requests that the vocabulary table
(``content_dictionaries/request-grammar-v1.json``) covers completely, and for nothing else:

* every character of the request must be consumed by exactly one function form, exactly one
  property, at most one domain, the optional ``f(x)=`` binder, or a filler word;
* any leftover (another operation, a restricted domain, a negation, a second claim, a different
  property, a negative or fractional exponent) is a miss, and the request keeps its existing
  route (model proposal, then the full Lean pipeline).

Widening the grammar is a data change: add a row to the table.  The table is a *selector*, not
a verdict: the proposition is still elaborated against the stored Recipe by Lean, reviewed by an
independent reviewer, and compiled by the API before anything is shown as an answer.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Final

from pals_agent.recipe_instantiation import InstantiationRejected, _leading_forall

SCHEMA_VERSION: Final = "pals.request-grammar.v1"
_SUPERSCRIPTS: Final = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUPERSCRIPT_RUN: Final = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_SEPARATORS: Final = re.compile(r"[\s、。，,.．!！?？$\\()（）\[\]「」『』:：;；\"'`*_]+")
_CONVENTIONS_NOTE: Final = re.compile(r"\n\s*\nConventions:.*\Z", re.DOTALL)
_MAX_REQUEST_CHARS: Final = 400


@dataclass(frozen=True, slots=True)
class RequestProposition:
    proposition: str
    function_id: str
    property_id: str
    variable: str
    slots: tuple[tuple[str, str], ...]
    search_query: str


@dataclass(frozen=True, slots=True)
class _Grammar:
    variable: re.Pattern[str]
    numerals: dict[str, dict[str, int]]
    functions: tuple[dict[str, Any], ...]
    properties: tuple[dict[str, Any], ...]
    binders: tuple[re.Pattern[str], ...]
    domains: tuple[dict[str, Any], ...]
    fillers: tuple[str, ...]


@lru_cache(maxsize=1)
def _grammar() -> _Grammar:
    return build_grammar(
        json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("request-grammar-v1.json")
            .read_text(encoding="utf-8")
        )
    )


def build_grammar(payload: dict[str, Any]) -> _Grammar:
    """Compile a vocabulary table (the packaged one, or a table a test supplies)."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("request grammar has an unexpected schema version")
    functions = []
    for entry in payload["functions"]:
        forms = []
        for form in entry["forms"]:
            compiled = re.compile(form["re"])
            if "v" not in compiled.groupindex:
                raise RuntimeError("every function form must capture the variable as v")
            forms.append({**form, "compiled": compiled})
        functions.append({**entry, "forms": tuple(forms)})
    properties = tuple(
        {**entry, "forms": tuple(sorted(entry["forms"], key=len, reverse=True))}
        for entry in payload["properties"]
    )
    domains = tuple(
        {**entry, "forms": tuple(sorted(entry["forms"], key=len, reverse=True))}
        for entry in payload["domains"]
    )
    return _Grammar(
        variable=re.compile(payload["variable"]["pattern"] + r"\Z"),
        numerals=payload["numerals"],
        functions=tuple(functions),
        properties=properties,
        binders=tuple(re.compile(pattern) for pattern in payload["function_binders"]),
        domains=domains,
        fillers=tuple(sorted(payload["fillers"], key=len, reverse=True)),
    )


def normalize_request(text: str) -> str:
    """Superscript digits to ``^k``, NFKC, lower case, the appended conventions note removed."""
    text = _CONVENTIONS_NOTE.sub("", text)
    text = _SUPERSCRIPT_RUN.sub(lambda run: "^" + run.group(0).translate(_SUPERSCRIPTS), text)
    return unicodedata.normalize("NFKC", text).lower().strip()


def parse_request(text: object, *, grammar: _Grammar | None = None) -> RequestProposition | None:
    """The Lean proposition of a request the vocabulary covers completely, else ``None``."""
    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_REQUEST_CHARS:
        return None
    grammar = grammar or _grammar()
    remaining = normalize_request(text)

    matches: list[tuple[int, int, dict[str, Any], re.Match[str]]] = []
    for function in grammar.functions:
        for form in function["forms"]:
            matches.extend(
                (m.start(), m.end(), {**function, "form": form}, m)
                for m in form["compiled"].finditer(remaining)
            )
    matches = _non_overlapping_best(matches)
    if len(matches) != 1:
        return None
    start, end, function, match = matches[0]
    variable = match.group("v")
    if grammar.variable.match(variable) is None:
        return None
    slots = _slots(function, match, grammar)
    if slots is None:
        return None
    remaining = remaining[:start] + " " + remaining[end:]

    remaining, prop_ids = _remove_words(remaining, grammar.properties)
    if len(prop_ids) != 1:
        return None
    remaining, domain_ids = _remove_words(remaining, grammar.domains)
    if len(set(domain_ids)) > 1:
        return None
    for binder in grammar.binders:
        for bound in list(binder.finditer(remaining)):
            names = bound.groupdict().get("v")
            if names is not None and names != variable:
                return None
        remaining = binder.sub(" ", remaining)
    for filler in grammar.fillers:
        remaining = _remove_filler(remaining, filler)
    if _SEPARATORS.sub("", remaining):
        return None

    prop_entry = next(p for p in grammar.properties if p["id"] == prop_ids[0])
    body = function["lean_body"].format(v=variable, **dict(slots))
    return RequestProposition(
        proposition=prop_entry["lean"].format(v=variable, body=body),
        function_id=function["id"],
        property_id=prop_entry["id"],
        variable=variable,
        slots=tuple(sorted(slots.items())),
        search_query=" ".join(
            term for term in (function.get("search_terms"), prop_entry.get("search_terms")) if term
        ),
    )


def _non_overlapping_best(
    matches: list[tuple[int, int, dict[str, Any], re.Match[str]]],
) -> list[tuple[int, int, dict[str, Any], re.Match[str]]]:
    """Keep the longest match of overlapping candidates; distinct regions all stay."""
    chosen: list[tuple[int, int, dict[str, Any], re.Match[str]]] = []
    for item in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0])):
        if all(item[1] <= other[0] or item[0] >= other[1] for other in chosen):
            chosen.append(item)
    return sorted(chosen, key=lambda m: m[0])


def _slots(
    function: dict[str, Any], match: re.Match[str], grammar: _Grammar
) -> dict[str, str] | None:
    form = function["form"]
    values: dict[str, str] = {name: str(value) for name, value in form.get("fixed", {}).items()}
    for name, kind in function.get("slots", {}).items():
        if name in values:
            continue
        raw = match.groupdict().get(name)
        if raw is None:
            return None
        if "numerals" in form:
            raw = str(grammar.numerals[form["numerals"]].get(raw, ""))
        if kind == "natural" and re.fullmatch(r"(?:0|[1-9][0-9]{0,8})", raw) is None:
            return None
        values[name] = raw
    return values


def _remove_words(
    text: str, entries: tuple[dict[str, Any], ...]
) -> tuple[str, list[str]]:
    found: list[str] = []
    for entry in entries:
        for form in entry["forms"]:
            pattern = _word_pattern(form)
            while True:
                text, count = pattern.subn(" ", text, count=1)
                if count == 0:
                    break
                found.append(entry["id"])
    return text, found


def _remove_filler(text: str, filler: str) -> str:
    return _word_pattern(filler).sub(" ", text)


def _word_pattern(word: str) -> re.Pattern[str]:
    escaped = re.escape(word)
    if re.fullmatch(r"[a-z][a-z ]*", word):
        return re.compile(rf"(?<![a-z]){escaped}(?![a-z])")
    return re.compile(escaped)


# --- binding a Recipe's universal parameters to the request -----------------------------------


def bind_recipe(target_source: str, proposition: str) -> tuple[tuple[str, str], ...] | None:
    """Literal values of the Recipe's leading universal parameters that give ``proposition``.

    A purely syntactic first-order match of the Recipe body against the proposition (bound
    variable names are normalized).  It only proposes: Lean elaborates the result and the API
    recompiles it, so a mistaken match costs a failed alternative, never a wrong theorem.
    """
    try:
        parameters, body = _leading_forall(target_source)
    except InstantiationRejected:
        return None
    # Only natural-number parameters: a literal in the proposition elaborates as a natural
    # number unless the context forces another type, so Int/Rat/Real parameters stay a miss.
    if not parameters or not body or any(parameter.kind != "Nat" for parameter in parameters):
        return None
    pattern_text = _canonical(body)
    target_text = _canonical(proposition)
    if pattern_text is None or target_text is None:
        return None
    pattern = re.escape(pattern_text)
    for index, parameter in enumerate(parameters):
        token = re.compile(rf"(?<![\w'.§]){re.escape(parameter.name)}(?![\w'.§])")
        if token.search(pattern) is None:
            return None  # a parameter that does not occur cannot be determined
        pattern = token.sub(_group_replacer(index), pattern)
    found = re.fullmatch(pattern, target_text)
    if found is None:
        return None
    return tuple(
        (parameter.name, found.group(f"p_{index}")) for index, parameter in enumerate(parameters)
    )


def _group_replacer(index: int) -> Callable[[re.Match[str]], str]:
    """First occurrence captures a literal, every later occurrence must repeat it."""
    first = [True]

    def replace(_: re.Match[str]) -> str:
        if first[0]:
            first[0] = False
            return f"(?P<p_{index}>[0-9]{{1,9}})"
        return f"(?P=p_{index})"

    return replace


def _canonical(text: str) -> str | None:
    """Whitespace-free text with a single lambda binder renamed to ``§``."""
    spaced = " ".join(text.split())
    binders = re.findall(r"(?:fun|λ)\s+([A-Za-z][\w']*)\s*[:=]", spaced)
    if len(binders) > 1:
        return None
    if binders:
        name = re.escape(binders[0])
        spaced = re.sub(rf"(?<![\w'.]){name}(?![\w'.])", "§", spaced)
    return re.sub(r"\s+", "", spaced)


def deterministic_instance_proposal(
    statement: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """A model-free instance proposal, in the shape the instantiation route consumes.

    ``candidates`` are the eligible Recipes (those with an explicit universal parameter).  The
    first one whose universal target matches the request's proposition is chosen.
    """
    parsed = parse_request(statement)
    if parsed is None:
        return None
    for candidate in candidates:
        bindings = bind_recipe(candidate.get("target_source", ""), parsed.proposition)
        if bindings is None:
            continue
        return {
            "instance_recipe_id": candidate["recipe_id"],
            "instance_recipe_revision": candidate["recipe_revision"],
            "bindings": [{"variable": name, "value": value} for name, value in bindings],
            "requested_proposition": parsed.proposition,
            "rationale": (
                f"Vocabulary grammar: {parsed.function_id} + {parsed.property_id}, "
                + ", ".join(f"{k}={v}" for k, v in parsed.slots)
            ),
            "chosen": candidate,
        }
    return None
