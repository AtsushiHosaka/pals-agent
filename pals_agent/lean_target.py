"""Deterministic target extraction for learner-visible Lean proof candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

_TERM_IDENTIFIER = re.compile(r"[^\W\d][\w'.?]*")


@dataclass(frozen=True, slots=True)
class LeanTargetDeclaration:
    kind: Literal["theorem", "lemma", "example"]
    name: str | None
    proposition: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "name": self.name,
            "proposition": self.proposition,
        }


def extract_single_target_declaration(source: str) -> LeanTargetDeclaration | None:
    """Return exactly one executable top-level proof declaration, or fail closed.

    Comments, strings, and quoted identifiers cannot create a declaration.  Auxiliary ``def``
    declarations are allowed; a learner proof candidate must nevertheless expose one and only one
    theorem/lemma/example proposition for semantic review.
    """
    if not isinstance(source, str) or not source.strip():
        return None
    executable = _without_lean_comments_and_literals(source)
    declarations = _top_level_proof_declarations(executable)
    if len(declarations) != 1:
        return None
    return _parse_declaration(executable, declarations[0])


def _top_level_proof_declarations(source: str) -> list[re.Match[str]]:
    declarations: list[re.Match[str]] = []
    depth = 0
    index = 0
    pattern = re.compile(r"(?:theorem|lemma|example)\b")
    while index < len(source):
        character = source[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            declaration = pattern.match(source, index)
            if declaration is not None and (
                index == 0
                or not (source[index - 1].isalnum() or source[index - 1] == "_")
            ):
                declarations.append(declaration)
                index = declaration.end()
                continue
        index += 1
    return declarations


def _parse_declaration(source: str, declaration: re.Match[str]) -> LeanTargetDeclaration | None:
    raw_kind = declaration.group(0)
    if raw_kind not in {"theorem", "lemma", "example"}:
        return None
    kind = cast(Literal["theorem", "lemma", "example"], raw_kind)
    index = declaration.end()
    while index < len(source) and source[index].isspace():
        index += 1
    name: str | None = None
    if kind != "example":
        name_match = re.match(r"[A-Za-z_][A-Za-z0-9_'.]*", source[index:])
        if name_match is None:
            return None
        name = name_match.group(0)
        index += name_match.end()

    depth = 0
    proposition_start: int | None = None
    pending_let_initializers = 0
    while index < len(source):
        character = source[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif (
            depth == 0
            and proposition_start is None
            and character == ":"
            and not source.startswith(":=", index)
        ):
            proposition_start = index + 1
        if depth == 0 and proposition_start is not None:
            # Only declaration-form, nonrecursive lets are scanned without an
            # enclosing delimiter. More complex term blocks can contain their
            # own local assignments: require parentheses instead of guessing
            # which assignment begins the theorem proof. Lean remains the parser.
            token = _TERM_IDENTIFIER.match(source, index)
            if token is not None and (
                index == 0 or not (source[index - 1].isalnum() or source[index - 1] in "_'.")
            ):
                word = token.group(0)
                if word in {
                    "by", "do", "match", "have", "suffices", "letI", "letI'",
                    "letI?", "let?", "rec", "mut", "where",
                }:
                    return None
                if word == "let":
                    pending_let_initializers += 1
                index = token.end()
                continue
        if depth == 0 and source.startswith(":=", index):
            if proposition_start is None:
                return None
            if pending_let_initializers:
                pending_let_initializers -= 1
                index += 2
                continue
            proposition = " ".join(source[proposition_start:index].split())
            if not proposition:
                return None
            return LeanTargetDeclaration(
                kind=kind,
                name=name,
                proposition=proposition,
            )
        index += 1
    return None


def _without_lean_comments_and_literals(source: str) -> str:
    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    in_quoted_identifier = False
    escaped = False
    while index < len(source):
        if block_depth > 0:
            if source.startswith("/-", index):
                block_depth += 1
                index += 2
            elif source.startswith("-/", index):
                block_depth -= 1
                index += 2
            else:
                if source[index] == "\n":
                    output.append("\n")
                index += 1
            continue
        if in_quoted_identifier:
            character = source[index]
            output.append("\n" if character == "\n" else " ")
            index += 1
            if character == "»":
                in_quoted_identifier = False
            continue
        if in_string:
            character = source[index]
            output.append("\n" if character == "\n" else " ")
            index += 1
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if source.startswith("--", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                break
            output.append("\n")
            index = newline + 1
            continue
        if source.startswith("/-", index):
            block_depth = 1
            # `/--` and `/-!` open doc comments, so their `-` or `!` cannot start the closing `-/`.
            index += 3 if source[index + 2 : index + 3] in ("-", "!") else 2
            continue
        character = source[index]
        output.append(" " if character in {'"', "«"} else character)
        index += 1
        if character == '"':
            in_string = True
        elif character == "«":
            in_quoted_identifier = True
    return "".join(output)


def strip_redundant_parentheses(value: str) -> str | None:
    """Strip only balanced pairs that surround the complete expression."""
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return None
    if depth != 0:
        return None

    while value.startswith("(") and value.endswith(")"):
        depth = 0
        surrounds_complete_expression = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            if depth == 0 and index != len(value) - 1:
                surrounds_complete_expression = False
                break
        if not surrounds_complete_expression:
            break
        value = value[1:-1]
    return value


_BINDER_NAME = r"[A-Za-z_][A-Za-z0-9_']*"
_OTHER_PROPERTY_TARGET = re.compile(
    r"(?<![A-Za-z0-9_.])(?:deriv\w*|fderiv\w*|Differentiable\w*|HasDeriv\w*|HasFDeriv\w*"
    r"|UniformContinuous\w*|LipschitzWith\w*|AntilipschitzWith\w*)(?![A-Za-z0-9_])"
)


def targets_another_property_of_a_function(proposition: str) -> bool:
    """Whether the Lean statement is about a derivative, differentiability, uniform continuity or
    a Lipschitz bound, i.e. a property other than plain continuity."""
    return _OTHER_PROPERTY_TARGET.search(proposition) is not None


def matches_x_squared_continuity(proposition: str) -> bool:
    """Whether a formalized proposition is `Continuous` of the real square function.

    Recognised: `fun x : ℝ => x ^ 2` with the binder as `x : ℝ` or `(x : ℝ)`, `Real` for `ℝ`,
    a type-ascribed body `(x ^ 2 : ℝ)`, the exponent `(2 : ℕ)`, the product `x * x`, and the
    typed sections `((· ^ 2) : ℝ → ℝ)` / `(· * ·  : ℝ → ℝ)`. An untyped function (`fun x => x ^ 2`
    or `(· ^ 2)`) elaborates over a default type, not necessarily ℝ, so it is not recognised.
    Everything else (x ^ 3, x ^ 2 + x, (x - 1) ^ 2, x ^ 2 ^ 2, x ^ 22, ContinuousAt, conjunctions,
    ℕ, 2 ^ x) is not.

    This reads the verified Lean statement, so it does not depend on how the learner phrased the
    request (language, `x^{2}`, `xの2乗`, full-width characters, ...).
    """
    declaration = re.sub(r"\s+", "", proposition).replace("²", "^2")
    declaration = re.sub(r"(?<![A-Za-z0-9_.])Real(?![A-Za-z0-9_.])", "ℝ", declaration)
    if not declaration.startswith("Continuous"):
        return False
    expression = strip_redundant_parentheses(declaration[len("Continuous") :])
    if expression is None:
        return False
    if re.fullmatch(r"\(?(?:·\^2|·\*·)\)?:ℝ→ℝ", expression):
        return True
    if not expression.startswith("fun"):
        return False

    lambda_body = expression[len("fun") :]
    arrow_positions = [
        position for position in (lambda_body.find("=>"), lambda_body.find("↦")) if position >= 0
    ]
    if not arrow_positions:
        return False
    arrow_position = min(arrow_positions)
    arrow_width = 2 if lambda_body[arrow_position:].startswith("=>") else 1
    binder = lambda_body[:arrow_position]
    body = lambda_body[arrow_position + arrow_width :]

    binder_match = re.fullmatch(
        rf"(?:\((?P<v1>{_BINDER_NAME}):(?P<t1>.+)\)|(?P<v2>{_BINDER_NAME}):(?P<t2>.+))", binder
    )
    if binder_match is None:
        return False
    variable = binder_match.group("v1") or binder_match.group("v2")
    binder_type = binder_match.group("t1") or binder_match.group("t2")
    if strip_redundant_parentheses(binder_type) != "ℝ":
        return False

    normalized_body = strip_redundant_parentheses(body)
    if normalized_body is not None and normalized_body.endswith(":ℝ"):
        normalized_body = strip_redundant_parentheses(normalized_body[: -len(":ℝ")])
    if normalized_body is None:
        return False
    if normalized_body == f"{variable}*{variable}":
        return True
    if "^" not in normalized_body:
        return False
    base, exponent = normalized_body.rsplit("^", maxsplit=1)
    normalized_base = strip_redundant_parentheses(base)
    normalized_exponent = strip_redundant_parentheses(exponent)
    return normalized_base == variable and normalized_exponent in {"2", "2:ℕ"}
