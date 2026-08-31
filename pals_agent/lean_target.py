"""Deterministic target extraction for learner-visible Lean proof candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast


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
        if depth == 0 and source.startswith(":=", index):
            if proposition_start is None:
                return None
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
            index += 2
            continue
        character = source[index]
        output.append(" " if character in {'"', "«"} else character)
        index += 1
        if character == '"':
            in_string = True
        elif character == "«":
            in_quoted_identifier = True
    return "".join(output)
