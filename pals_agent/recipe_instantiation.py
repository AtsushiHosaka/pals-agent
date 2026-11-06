"""Deterministic instantiation of a stored universal Recipe, never an LLM opinion.

A sealed Recipe proves ``forall p1 .. pm, Body``.  A request that is exactly ``Body`` with a
leading prefix of the parameters replaced by closed integer literals follows by application of
the same verified theorem.  This module forms that application *mechanically* from the Recipe's
exact Lean bytes and returns the full Lean source that a verifier must still compile; it never
decides that the learner's words mean this instance (that stays with the independent reviewers)
and it never produces a success value.  Every unsupported shape raises ``InstantiationRejected``:
implicit or instance binders, hypotheses, existential or shadowed names, names used through field
notation or named arguments, namespaces/sections/variables, non-literal or ill-typed arguments.

pals-api carries the same module (byte-identical logic, same vectors): the API re-derives the source
from its own sealed bytes and never trusts a worker-supplied one.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = "pals.recipe-instantiation.v1"
INSTANCE_NAME: Final = "pals_recipe_instance"
GENERAL_NAME: Final = "pals_recipe_general"
MAX_BINDINGS: Final = 8
_NUMERIC_KINDS: Final = {
    "ℕ": "Nat", "Nat": "Nat", "ℤ": "Int", "Int": "Int",
    "ℚ": "Rat", "Rat": "Rat", "ℝ": "Real", "Real": "Real",
}
_NATURAL_LITERAL = re.compile(r"(?:0|[1-9][0-9]{0,8})\Z")
_INTEGER_LITERAL = re.compile(r"-?(?:0|[1-9][0-9]{0,8})\Z")
_DISPLAY_NAME = re.compile(r"[A-Za-zα-ω][0-9]{0,2}\Z")
_IDENTIFIER = re.compile(r"[^\W\d][\w'?!]*(?:\.[^\W\d][\w'?!]*)*")
_DECLARATION = re.compile(r"(?<![\w'.])(theorem|lemma|example)(?![\w'.])")
_UNSUPPORTED_COMMAND = re.compile(
    r"(?<![\w'.])(namespace|section|variable|variables|universe|mutual|end|private|protected"
    r"|local|scoped|macro|syntax|notation|infix|infixl|infixr|prefix|postfix|elab|instance"
    r"|structure|class|inductive|attribute)(?![\w'.])"
)
_BINDER_WORD = r"(?:(?<![\w'.])(?:fun|λ)|[∀∃∑∏⋃⋂⨆⨅∫ΣΠ]!?)"


_CODES: Final = (
    (("binding count", "too many"), "inst_limit_exceeded"),
    (("remaining binder", "hypothes"), "inst_premise_unprovable"),
    (
        ("closed integer literal", "leading parameters", "no type", "plain typed"),
        "inst_type_mismatch",
    ),
    (
        ("rebound", "projection", "named argument", "field notation", "shadowed"),
        "inst_capture",
    ),
)


class InstantiationRejected(ValueError):
    """The Recipe or the proposed arguments are outside the closed instantiation grammar.

    ``code`` is the typed ``inst_*`` classification recorded as evidence before the DSP runs.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = next(
            (code for keys, code in _CODES if any(key in message for key in keys)),
            "inst_unsupported_shape",
        )


@dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    type_text: str
    kind: str | None  # Nat/Int/Rat/Real when integer literals can instantiate it


@dataclass(frozen=True, slots=True)
class RecipeInstance:
    source: str
    source_sha256: str
    proposition: str
    proposition_sha256: str
    bindings: tuple[tuple[str, str], ...]
    general_name: str

    def binding_objects(self) -> list[dict[str, str]]:
        return [{"variable": name, "value": value} for name, value in self.bindings]


@dataclass(frozen=True, slots=True)
class _Declaration:
    keyword: str
    keyword_span: tuple[int, int]
    name: str | None
    parameters: tuple[Parameter, ...]
    body: str
    remaining_prefix: str


def _mask(source: str) -> str:
    """Length-preserving copy with comments and string literals blanked."""
    out = list(source)
    i, n, depth = 0, len(source), 0
    while i < n:
        if depth:
            if source.startswith("/-", i):
                depth += 1
                step = 2
            elif source.startswith("-/", i):
                depth -= 1
                step = 2
            else:
                step = 1
            for j in range(i, i + step):
                if out[j] != "\n":
                    out[j] = " "
            i += step
        elif source.startswith("/-", i):
            depth = 1
            out[i] = out[i + 1] = " "
            i += 2
        elif source.startswith("--", i):
            while i < n and source[i] != "\n":
                out[i] = " "
                i += 1
        elif source[i] == '"':
            out[i] = " "
            i += 1
            while i < n and source[i] != '"':
                if source[i] == "\\" and i + 1 < n:
                    out[i] = " "
                    i += 1
                if out[i] != "\n":
                    out[i] = " "
                i += 1
            if i >= n:
                raise InstantiationRejected("unterminated string literal")
            out[i] = " "
            i += 1
        else:
            i += 1
    if depth:
        raise InstantiationRejected("unterminated block comment")
    return "".join(out)


def _depth_zero_index(text: str, start: int, stop_at: str) -> int | None:
    """First depth-zero occurrence of ``stop_at`` (a literal) at or after ``start``."""
    depth = 0
    i = start
    while i < len(text):
        character = text[i]
        if character in "([{⟨⦃":
            depth += 1
        elif character in ")]}⟩⦄":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and text.startswith(stop_at, i):
            if stop_at == ":" and text.startswith(":=", i):
                return None
            return i
        i += 1
    return None


def _group_end(text: str, start: int) -> int:
    opener = text[start]
    pairs = {"(": ")", "[": "]", "{": "}", "⟨": "⟩", "⦃": "⦄"}
    depth = 0
    for i in range(start, len(text)):
        if text[i] in "([{⟨⦃":
            depth += 1
        elif text[i] in ")]}⟩⦄":
            depth -= 1
            if depth == 0:
                if text[i] != pairs[opener]:
                    raise InstantiationRejected("mismatched binder brackets")
                return i
    raise InstantiationRejected("unterminated binder group")


def _normal(text: str) -> str:
    return " ".join(text.split())


def _kind(type_text: str) -> str | None:
    return _NUMERIC_KINDS.get(_normal(type_text))


def _parameters_of_group(inner: str) -> list[Parameter]:
    colon = _depth_zero_index(inner, 0, ":")
    if colon is None:
        raise InstantiationRejected("binder has no type")
    names = inner[:colon].split()
    type_text = _normal(inner[colon + 1:])
    if not names or not type_text or ":=" in type_text:
        raise InstantiationRejected("binder is not a plain typed parameter")
    for name in names:
        if _IDENTIFIER.fullmatch(name) is None or "." in name:
            raise InstantiationRejected("binder name is unsupported")
    return [Parameter(name, type_text, _kind(type_text)) for name in names]


def _signature_parameters(text: str) -> list[Parameter]:
    parameters: list[Parameter] = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] != "(":
            raise InstantiationRejected("only explicit parenthesized binders are supported")
        end = _group_end(text, i)
        parameters.extend(_parameters_of_group(text[i + 1:end]))
        i = end + 1
    return parameters


def _leading_forall(proposition: str) -> tuple[list[Parameter], str]:
    """Peel typed ``∀`` binders that precede the body; stop at any other form."""
    parameters: list[Parameter] = []
    rest = proposition.strip()
    while rest.startswith("∀"):
        i = 1
        groups: list[Parameter] = []
        while i < len(rest) and rest[i].isspace():
            i += 1
        if i < len(rest) and rest[i] == "(":
            while i < len(rest) and rest[i] == "(":
                end = _group_end(rest, i)
                groups.extend(_parameters_of_group(rest[i + 1:end]))
                i = end + 1
                while i < len(rest) and rest[i].isspace():
                    i += 1
            if i >= len(rest) or rest[i] != ",":
                break
        else:
            comma = _depth_zero_index(rest, i, ",")
            colon = _depth_zero_index(rest, i, ":")
            if comma is None or colon is None or colon > comma:
                break
            try:
                groups = _parameters_of_group(rest[i:comma])
            except InstantiationRejected:
                break
            i = comma
        parameters.extend(groups)
        rest = rest[i + 1:].strip()
    return parameters, rest


def _parse(source: str) -> tuple[_Declaration, str]:
    if not isinstance(source, str) or not 0 < len(source) <= 200_000 or "\x00" in source:
        raise InstantiationRejected("Recipe source is invalid")
    masked = _mask(source)
    if "'(" in masked or "')" in masked or "'[" in masked or "']" in masked:
        raise InstantiationRejected("character literal near a bracket is ambiguous")
    if _UNSUPPORTED_COMMAND.search(masked) or re.search(r"(?<![\w'.])open\b[^\n]*\bin\b", masked):
        raise InstantiationRejected("Recipe uses scoped commands")
    keywords = []
    depth = 0
    for match in _DECLARATION.finditer(masked):
        depth = 0
        for character in masked[:match.start()]:
            if character in "([{⟨⦃":
                depth += 1
            elif character in ")]}⟩⦄":
                depth -= 1
        if depth == 0:
            keywords.append(match)
    if len(keywords) != 1:
        raise InstantiationRejected("exactly one proof declaration is required")
    match = keywords[0]
    position = match.end()
    name: str | None = None
    if match.group(1) != "example":
        named = re.compile(r"\s+([^\W\d][\w'.]*)").match(masked, position)
        if named is None:
            raise InstantiationRejected("declaration has no name")
        name = named.group(1)
        position = named.end()
    colon = _depth_zero_index(masked, position, ":")
    assign = _depth_zero_index(masked, position, ":=")
    if colon is None or assign is None or assign < colon:
        raise InstantiationRejected("declaration signature is unsupported")
    signature = _signature_parameters(masked[position:colon])
    proposition = _normal(masked[colon + 1:assign])
    if source[colon + 1:assign] != masked[colon + 1:assign]:
        raise InstantiationRejected("comments or strings inside the statement are unsupported")
    quantified, body = _leading_forall(proposition)
    parameters = tuple(signature + quantified)
    if len({parameter.name for parameter in parameters}) != len(parameters):
        raise InstantiationRejected("shadowed parameter names are ambiguous")
    if not body:
        raise InstantiationRejected("statement body is empty")
    return _Declaration(
        match.group(1), (match.start(), match.end()), name, parameters, body, ""
    ), masked


def universal_parameters(source: str) -> tuple[Parameter, ...]:
    """The maximal prefix of parameters that integer literals could instantiate (maybe empty)."""
    try:
        declaration, _ = _parse(source)
    except InstantiationRejected:
        return ()
    prefix: list[Parameter] = []
    for parameter in declaration.parameters[:MAX_BINDINGS]:
        if parameter.kind is None:
            break
        prefix.append(parameter)
    return tuple(prefix)


def canonical_value(kind: str, value: object) -> str:
    pattern = _NATURAL_LITERAL if kind == "Nat" else _INTEGER_LITERAL
    if not isinstance(value, str) or pattern.fullmatch(value) is None or value == "-0":
        raise InstantiationRejected("argument is not a closed integer literal of the binder type")
    return value


def _lean_term(value: str) -> str:
    return f"({value})" if value.startswith("-") else value


def _binds_name(body: str, name: str) -> bool:
    escaped = re.escape(name)
    patterns = (
        rf"{_BINDER_WORD}\s*[^,↦=>]*?(?<![\w'.]){escaped}(?![\w'.])",
        rf"(?<![\w'.]){escaped}\s*(?:↦|=>|:=)",
        rf"\{{\s*{escaped}\s*(?:\||∈|:)",
    )
    return any(re.search(pattern, body) for pattern in patterns)


def _substitute(body: str, replacements: dict[str, str]) -> str:
    out: list[str] = []
    last = 0
    for token in _IDENTIFIER.finditer(body):
        text = token.group(0)
        head = text.split(".", 1)[0]
        if head in replacements and text != head:
            raise InstantiationRejected("field notation on a substituted variable")
        if text in replacements:
            if token.start() and body[token.start() - 1] in ".@":
                raise InstantiationRejected("substituted variable is used as a projection")
            out.append(body[last:token.start()])
            out.append(replacements[text])
            last = token.end()
    out.append(body[last:])
    return "".join(out)


def instantiate(source: str, bindings: object) -> RecipeInstance:
    """Form ``source`` plus one appended application of the Recipe at literal arguments."""
    declaration, masked = _parse(source)
    if (
        not isinstance(bindings, (list, tuple))
        or not 1 <= len(bindings) <= min(MAX_BINDINGS, len(declaration.parameters))
    ):
        raise InstantiationRejected("binding count is invalid")
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(bindings):
        if isinstance(item, dict):
            if set(item) != {"variable", "value"}:
                raise InstantiationRejected("binding fields are invalid")
            variable, value = item["variable"], item["value"]
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            variable, value = item
        else:
            raise InstantiationRejected("binding shape is invalid")
        parameter = declaration.parameters[index]
        if variable != parameter.name or parameter.kind is None:
            raise InstantiationRejected("bindings must instantiate the leading parameters in order")
        if _DISPLAY_NAME.fullmatch(variable) is None:
            raise InstantiationRejected("variable name cannot be displayed unambiguously")
        pairs.append((variable, canonical_value(parameter.kind, value)))
    substituted = {name for name, _ in pairs}
    remaining = declaration.parameters[len(pairs):]
    for parameter in remaining:
        if any(
            token.group(0).split(".", 1)[0] in substituted
            for token in _IDENTIFIER.finditer(parameter.type_text)
        ):
            raise InstantiationRejected("a remaining binder depends on a substituted variable")
    for name in substituted:
        if _binds_name(declaration.body, name):
            raise InstantiationRejected("a substituted name is rebound inside the statement")
        if re.search(rf"(?<![\w'.]){re.escape(name)}\s*:=", declaration.body):
            raise InstantiationRejected("a substituted name is used as a named argument")
    body = _substitute(declaration.body, {name: _lean_term(value) for name, value in pairs})
    proposition = (
        "∀ " + " ".join(f"({p.name} : {p.type_text})" for p in remaining) + ", " + body
        if remaining else body
    )
    general = declaration.name or GENERAL_NAME
    if re.search(rf"(?<![\w'.])({INSTANCE_NAME}|{GENERAL_NAME})(?![\w'.])", masked):
        raise InstantiationRejected("reserved declaration name already used")
    start, end = declaration.keyword_span
    head = source[:start]
    renamed = source[start:end] if declaration.name else f"theorem {GENERAL_NAME}"
    instance = (
        head + renamed + source[end:]
    ).rstrip("\n") + (
        f"\n\ntheorem {INSTANCE_NAME} : {proposition} := "
        f"{general} {' '.join(_lean_term(value) for _, value in pairs)}\n"
    )
    return RecipeInstance(
        source=instance,
        source_sha256=hashlib.sha256(instance.encode()).hexdigest(),
        proposition=proposition,
        proposition_sha256=hashlib.sha256(proposition.encode()).hexdigest(),
        bindings=tuple(pairs),
        general_name=general,
    )


# --- learner-facing wrapper: deterministic, language aware, adds nothing mathematical ----------
_WRAPPER: Final = {
    "en": (
        "This is the special case {subst} of the following general result.",
        "General result: {statement}",
        "Setting {subst} in this general result gives exactly the statement you asked about.",
    ),
    "ja": (
        "この主張は、次の一般的な結果で {subst} とおいた特別な場合です。",
        "一般的な結果：{statement}",
        "この一般的な結果で {subst} とおくと、ご質問の主張が得られます。",
    ),
    "zh-Hans": (
        "这是下面这个一般性结果在 {subst} 时的特例。",
        "一般性结果：{statement}",
        "在这个一般性结果中取 {subst}，就得到您所问的命题。",
    ),
    "zh-Hant": (
        "這是下面這個一般性結果在 {subst} 時的特例。",
        "一般性結果：{statement}",
        "在這個一般性結果中取 {subst}，就得到您所問的命題。",
    ),
}


def render_answer(
    language: str, general_statement: str, bindings: tuple[tuple[str, str], ...] | list[
        tuple[str, str]
    ], stored_answer: str,
) -> str:
    """The displayed text: wrapper, the stored answer byte for byte, closing sentence."""
    if language not in _WRAPPER or not bindings:
        raise InstantiationRejected("unsupported answer language or empty substitution")
    for variable, value in bindings:
        if _DISPLAY_NAME.fullmatch(variable) is None or _INTEGER_LITERAL.fullmatch(value) is None:
            raise InstantiationRejected("substitution cannot be displayed")
    subst = ", ".join(f"${variable}={value}$" for variable, value in bindings)
    intro, general, closing = _WRAPPER[language]
    return (
        intro.format(subst=subst) + "\n\n" + general.format(statement=general_statement)
        + "\n\n" + stored_answer + "\n\n" + closing.format(subst=subst)
    )
