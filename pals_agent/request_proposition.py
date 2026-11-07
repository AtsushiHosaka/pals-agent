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
from pals_agent.request_instructions import split_presentation_instructions

SCHEMA_VERSION: Final = "pals.request-grammar.v1"
_SUPERSCRIPTS: Final = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUPERSCRIPT_RUN: Final = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_SEPARATORS: Final = re.compile(r"[\s、。，,.．!！?？$\\()（）\[\]「」『』:：;；\"`*_]+")
_CONVENTIONS_NOTE: Final = re.compile(r"\n\s*\nConventions:.*\Z", re.DOTALL)
_MAX_REQUEST_CHARS: Final = 400
# A decimal literal slot: at most nine integer digits, no leading zero, up to six decimals.
_DECIMAL: Final = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,6})?")


@dataclass(frozen=True, slots=True)
class RequestProposition:
    proposition: str
    function_id: str
    property_id: str
    variable: str
    slots: tuple[tuple[str, str], ...]
    search_query: str
    preferred_method: str | None = None


@dataclass(frozen=True, slots=True)
class _Grammar:
    variable: re.Pattern[str]
    numerals: dict[str, dict[str, int]]
    functions: tuple[dict[str, Any], ...]
    properties: tuple[dict[str, Any], ...]
    binders: tuple[re.Pattern[str], ...]
    domains: tuple[dict[str, Any], ...]
    fillers: tuple[str, ...]
    filler_patterns: tuple[re.Pattern[str], ...] = ()


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
            if "v" not in compiled.groupindex and not form.get("variable"):
                raise RuntimeError(
                    "every function form must capture the variable as v or name a default"
                )
            forms.append({**form, "compiled": compiled})
        functions.append({**entry, "forms": tuple(forms)})
    properties = tuple(
        {**entry, "forms": _literal_forms(entry["forms"])} for entry in payload["properties"]
    )
    domains = tuple(
        {
            **entry,
            "forms": _literal_forms(entry["forms"]),
            "patterns": tuple(re.compile(pattern) for pattern in entry.get("patterns", ())),
        }
        for entry in payload["domains"]
    )
    return _Grammar(
        variable=re.compile(payload["variable"]["pattern"] + r"\Z"),
        numerals=payload["numerals"],
        functions=tuple(functions),
        properties=properties,
        binders=tuple(re.compile(pattern) for pattern in payload["function_binders"]),
        domains=domains,
        fillers=_literal_forms(payload["fillers"]),
        filler_patterns=tuple(
            re.compile(pattern) for pattern in payload.get("filler_patterns", ())
        ),
    )


def _literal_forms(forms: list[str]) -> tuple[str, ...]:
    """Literal table words, normalized like the request text, longest first."""
    return tuple(
        sorted({_normalize_text(form) for form in forms}, key=len, reverse=True)
    )


def _prepare(text: str) -> str:
    """Superscripts to ``^k``, NFKC, the appended conventions note removed; case is kept."""
    text = _CONVENTIONS_NOTE.sub("", text)
    text = text.replace("ˣ", "^x")  # e\u02e3: NFKC would flatten it to the letters "ex"
    text = _SUPERSCRIPT_RUN.sub(lambda run: "^" + run.group(0).translate(_SUPERSCRIPTS), text)
    return unicodedata.normalize("NFKC", text).strip()


def normalize_request(text: str) -> str:
    """Superscript digits to ``^k``, NFKC, lower case, the appended conventions note removed."""
    return _normalize_text(_prepare(text))


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().strip()


def parse_request(text: object, *, grammar: _Grammar | None = None) -> RequestProposition | None:
    """The Lean proposition of a request the vocabulary covers completely, else ``None``."""
    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_REQUEST_CHARS:
        return None
    grammar = grammar or _grammar()
    # Language, format and tone instructions come from a closed table of their own.
    cased = split_presentation_instructions(_prepare(text)).claim.strip()
    remaining = _normalize_text(cased)

    candidates: list[tuple[int, int, dict[str, Any], re.Match[str]]] = []
    for function in grammar.functions:
        for form in function["forms"]:
            candidates.extend(
                (m.start(), m.end(), {**function, "form": form}, m)
                for m in form["compiled"].finditer(remaining)
            )
    formulas = [c for c in candidates if not c[2]["form"].get("name_only")]
    names = [c for c in candidates if c[2]["form"].get("name_only")]
    if formulas:
        selected = _non_overlapping_best(formulas)
    else:  # a bare function name is a request only when its table row says it is unambiguous
        selected = _non_overlapping_best([c for c in names if c[2]["form"].get("alone", True)])
        names = []
    if selected is None or len(selected) != 1:
        return None
    start, end, function, match = selected[0]
    # A factorial mark glued to the term changes its meaning; the separators would hide it.
    if remaining[end : end + 1] == "!" or (start and remaining[start - 1] == "!"):
        return None
    variable = match.groupdict().get("v") or function["form"].get("variable")
    if not variable or grammar.variable.match(variable) is None:
        return None
    # A capital letter is a set, a random variable or a matrix, not the real variable.
    if re.search(rf"(?<![A-Za-z]){variable.upper()}(?![A-Za-z])", cased):
        return None
    slots = _slots(function, match, grammar)
    if slots is None:
        return None
    spans = [(start, end)]
    # A function name beside its formula ("the fourth power function x^4") only describes it: it
    # is consumed when it names the same function with the same body, and it is a miss otherwise.
    for n_start, n_end, n_function, n_match in names:
        if n_start < end and start < n_end:
            continue
        if n_function["id"] != function["id"]:
            if n_function["form"].get("alone", True):
                return None
            continue
        n_slots = _slots(n_function, n_match, grammar)
        if n_slots is None or _lean_body(n_function, variable, n_slots) != _lean_body(
            function, variable, slots
        ):
            return None
        spans.append((n_start, n_end))
    for span_start, span_end in sorted(spans, reverse=True):
        remaining = remaining[:span_start] + " " + remaining[span_end:]

    remaining, prop_ids = _remove_words(remaining, grammar.properties)
    if len(set(prop_ids)) != 1:  # the same property named twice is still one claim
        return None
    remaining, domain_ids = _remove_words(remaining, grammar.domains)
    remaining, pattern_ids = _remove_patterns(remaining, grammar.domains)
    domain_ids += pattern_ids
    if len(set(domain_ids)) > 1:
        return None
    function_names: set[str] = set()
    for binder in grammar.binders:
        for bound in list(binder.finditer(remaining)):
            bound_name = bound.groupdict().get("v")
            if bound_name is not None and bound_name != variable:
                return None
            symbol = bound.groupdict().get("fn")
            if symbol is not None:
                if symbol == variable:
                    return None
                function_names.add(symbol)
        remaining = binder.sub(" ", remaining)
    # The function symbol a binder introduced (``f`` in ``f(x) = x^2``) may be mentioned again.
    for symbol in function_names:
        remaining = re.sub(rf"(?<![a-z0-9_]){re.escape(symbol)}(?![a-z0-9_])", " ", remaining)
    for pattern in grammar.filler_patterns:
        remaining = pattern.sub(" ", remaining)
    for filler in grammar.fillers:
        remaining = _remove_filler(remaining, filler)
    if _SEPARATORS.sub("", remaining):
        return None

    prop_entry = next(p for p in grammar.properties if p["id"] == prop_ids[0])
    body = _lean_body(function, variable, slots)
    return RequestProposition(
        proposition=prop_entry["lean"].format(v=variable, body=body),
        function_id=function["id"],
        property_id=prop_entry["id"],
        variable=variable,
        slots=tuple(sorted(slots.items())),
        preferred_method=prop_entry.get("preferred_method"),
        search_query=" ".join(
            term for term in (function.get("search_terms"), prop_entry.get("search_terms")) if term
        ),
    )


def _lean_body(function: dict[str, Any], variable: str, slots: dict[str, str]) -> str:
    template = function["form"].get("lean_body") or function["lean_body"]
    return str(template.format(v=variable, **slots))


def _non_overlapping_best(
    matches: list[tuple[int, int, dict[str, Any], re.Match[str]]],
) -> list[tuple[int, int, dict[str, Any], re.Match[str]]] | None:
    """Maximal munch among the candidates; an overlap that is not a containment is ambiguous.

    Wordings of one function may overlap each other (the longest wins).  Two different functions
    may only overlap when one match contains the other (``2*x^3`` contains ``x^3``); the longer
    one is the reading.  A partial overlap or two functions on the same span is ``None``.
    """
    chosen: list[tuple[int, int, dict[str, Any], re.Match[str]]] = []
    for item in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0])):
        overlapping = [o for o in chosen if not (item[1] <= o[0] or item[0] >= o[1])]
        if not overlapping:
            chosen.append(item)
            continue
        for other in overlapping:
            if other[2]["id"] == item[2]["id"]:
                continue
            contained = other[0] <= item[0] and item[1] <= other[1]
            if not contained or (item[0], item[1]) == (other[0], other[1]):
                return None
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
        if kind == "decimal" and _DECIMAL.fullmatch(raw) is None:
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


def _remove_patterns(
    text: str, entries: tuple[dict[str, Any], ...]
) -> tuple[str, list[str]]:
    found: list[str] = []
    for entry in entries:
        for pattern in entry.get("patterns", ()):
            text, count = pattern.subn(" ", text)
            found.extend([entry["id"]] * count)
    return text, found


def _remove_filler(text: str, filler: str) -> str:
    return _word_pattern(filler).sub(" ", text)


def _word_pattern(word: str) -> re.Pattern[str]:
    escaped = re.escape(word)
    if re.fullmatch(r"[a-z][a-z \-]*", word):
        return re.compile(rf"(?<![a-z]){escaped}(?![a-z])")
    return re.compile(escaped)


# --- binding a Recipe's universal parameters to the request -----------------------------------


# The literal a request proposition can hold at a parameter of each kind.  A natural number or an
# integer is a plain digit string; a rational or real value may also be a decimal literal.
_LITERAL: Final = {
    "Nat": r"[0-9]{1,9}",
    "Int": r"[0-9]{1,9}",
    "Rat": r"[0-9]{1,9}(?:\.[0-9]{1,6})?",
    "Real": r"[0-9]{1,9}(?:\.[0-9]{1,6})?",
}


def bind_recipe(target_source: str, proposition: str) -> tuple[tuple[str, str], ...] | None:
    """Integer-literal hints for the Recipe's leading universal parameters, or ``None``.

    A purely syntactic first-order match of the Recipe body against the proposition (bound
    variable names are normalized).  Parameters may be of kind Nat, Int, Rat or Real.  It only
    proposes: Lean elaborates the result and the API recompiles it, so a mistaken match costs a
    failed alternative, never a wrong theorem.

    * An integer literal becomes a hint ``(name, literal)``.
    * A decimal literal (``2.5``) is never sent as a hint, since the wire contract carries integer
      literals only; Lean's unification finds it.  When any parameter took a decimal the result
      is the empty tuple (a match with nothing to hint), so no partial substitution is claimed.
    * A non-natural parameter that sits directly after ``^`` does not bind: the table writes
      natural exponents only, and ``x ^ 2`` elaborates with a natural exponent.
    """
    try:
        parameters, body = _leading_forall(target_source)
    except InstantiationRejected:
        return None
    if not parameters or not body or any(p.kind not in _LITERAL for p in parameters):
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
        if parameter.kind != "Nat" and re.search(
            rf"\\\^(?:\\\()*{re.escape(parameter.name)}(?![\w'.§])", pattern
        ):
            return None  # a real, rational or integer exponent is never written by the table
        pattern = token.sub(_group_replacer(index, _LITERAL[parameter.kind or "Nat"]), pattern)
    found = re.fullmatch(pattern, target_text)
    if found is None:
        return None
    values = [found.group(f"p_{index}") for index in range(len(parameters))]
    if any("." in value for value in values):
        return ()
    names = (parameter.name for parameter in parameters)
    return tuple(zip(names, values, strict=True))


def _group_replacer(index: int, literal: str) -> Callable[[re.Match[str]], str]:
    """First occurrence captures a literal, every later occurrence must repeat it."""
    first = [True]

    def replace(_: re.Match[str]) -> str:
        if first[0]:
            first[0] = False
            return f"(?P<p_{index}>{literal})"
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
    # A property may prefer a proof method (continuity: epsilon-delta); stable otherwise.
    ordered = sorted(
        candidates,
        key=lambda c: 0 if parsed.preferred_method and c.get("proof_method_tag")
        == parsed.preferred_method else 1,
    )
    for candidate in ordered:
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
