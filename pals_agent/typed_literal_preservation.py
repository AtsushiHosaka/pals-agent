"""Bounded preservation of explicitly written integer matrices, not semantic QA.

Call only after the profile's complete XML validation. This checks shape/entry
sets, not operand roles, operation choice, multiplicity, hypotheses, or truth.
Unsupported source syntax is not partially interpreted and makes no preservation
claim. No values are inferred from zero/identity or computed from expressions.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_PROFILE = "typed-math-matrix-v1"
_NS = "{http://www.openmath.org/OpenMath}"
_BASE = "urn:pals:openmath:typed-math:v1"
_MAX_STATEMENT = 20_000
_MAX_XML_BYTES = 262_144
_MAX_DIGITS = 128
_INTEGER = r"[+-]?[0-9]+"
_ROW = rf"\[\s*{_INTEGER}(?:\s*,\s*{_INTEGER})*\s*\]"
_MATRIX = re.compile(rf"\[\s*{_ROW}(?:\s*,\s*{_ROW})*\s*\]")
_Matrix = tuple[int, int, tuple[int, ...]]


class LiteralPreservationError(ValueError):
    """Fixed safe text, suitable for bounded private validation feedback."""

    def __init__(self) -> None:
        super().__init__("Explicit matrix literal values or dimensions were not preserved")


def _natural(text: str) -> int:
    digits = text.removeprefix("+")
    if not re.fullmatch(r"[0-9]+", digits) or len(digits) > _MAX_DIGITS:
        raise LiteralPreservationError()
    return int(digits)


def _source_matrices(statement: str) -> set[_Matrix] | None:
    result: set[_Matrix] = set()
    unsupported = False
    index = 0
    while index < len(statement):
        if statement[index] != "[":
            index += 1
            continue
        start, depth = index, 1
        index += 1
        while index < len(statement) and depth:
            depth += (statement[index] == "[") - (statement[index] == "]")
            index += 1
        fragment = statement[start:index]
        if not re.match(r"\[\s*\[", fragment):
            continue
        if depth or not _MATRIX.fullmatch(fragment):
            unsupported = True
            continue
        rows = [re.findall(_INTEGER, row) for row in re.findall(r"\[([^\[\]]*)\]", fragment)]
        if not 1 <= len(rows) <= 8 or not 1 <= len(rows[0]) <= 8:
            raise LiteralPreservationError()
        if any(len(row) != len(rows[0]) for row in rows):
            raise LiteralPreservationError()
        values = tuple(_natural(entry) for row in rows for entry in row)
        result.add((len(rows), len(rows[0]), values))
    # A mixed symbolic/fraction/integer source cannot support an exact set claim.
    return None if unsupported or not result else result


def _is_symbol(node: ET.Element, name: str) -> bool:
    return node.tag == _NS + "OMS" and node.attrib == {
        "cdbase": _BASE,
        "cd": "matrix1",
        "name": name,
    }


def _integer(node: ET.Element) -> int:
    if node.tag != _NS + "OMI" or len(node):
        raise LiteralPreservationError()
    return _natural((node.text or "").strip())


def _xml_matrices(canonical_xml: str) -> set[_Matrix]:
    try:
        raw = canonical_xml.encode("utf-8")
        if len(raw) > _MAX_XML_BYTES or "<!" in canonical_xml:
            raise LiteralPreservationError()
        root = ET.fromstring(raw)
    except (UnicodeError, ET.ParseError):
        raise LiteralPreservationError() from None
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise LiteralPreservationError()
    result: set[_Matrix] = set()
    for node in nodes:
        if node.tag != _NS + "OMA" or not len(node) or not _is_symbol(node[0], "literal"):
            continue
        if len(node) < 4 or node[1].tag != _NS + "OMV":
            raise LiteralPreservationError()
        carrier = node[1].get("name")
        rows, columns = _integer(node[2]), _integer(node[3])
        if not 1 <= rows <= 8 or not 1 <= columns <= 8 or len(node) != 4 + rows * columns:
            raise LiteralPreservationError()
        values = []
        for entry in list(node)[4:]:
            if (
                entry.tag != _NS + "OMA"
                or len(entry) != 3
                or not _is_symbol(entry[0], "field_nat_cast")
                or entry[1].tag != _NS + "OMV"
                or entry[1].get("name") != carrier
            ):
                raise LiteralPreservationError()
            values.append(_integer(entry[2]))
        result.add((rows, columns, tuple(values)))
    return result


def validate_literal_preservation(profile_id: str, statement: str, canonical_xml: str) -> None:
    """Check recognized ASCII-integer matrix sets; do not evaluate the proposition."""
    if profile_id != _PROFILE:
        return
    if not isinstance(statement, str) or len(statement) > _MAX_STATEMENT:
        raise LiteralPreservationError()
    expected = _source_matrices(statement)
    if expected is None:
        return
    if not isinstance(canonical_xml, str) or _xml_matrices(canonical_xml) != expected:
        raise LiteralPreservationError()
