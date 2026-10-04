"""Conservative retrieval filter for a closed universal-field matrix proposition.

A counterexample in Q refutes only the supplied structured universal proposition.
This is not natural-language equivalence, semantic QA, or a proof receipt. A false
return means unknown/no counterexample found, never a theorem-correctness claim.
The caller must first run the complete canonical profile validator.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction

CONTRACT_VERSION = "pals.typed-matrix-rational-counterexample.v1"
_PROFILE = "typed-math-matrix-v1"
_NS = "{http://www.openmath.org/OpenMath}"
_BASE = "urn:pals:openmath:typed-math:v1"
_STANDARD = "http://www.openmath.org/cd"
_MAX_BYTES = 65_536
_MAX_NODES = 4096
_MAX_DEPTH = 64
_MAX_BITS = 4096
_MAX_OPERATIONS = 20_000
_MAX_DIGITS = 1000


class _Unknown(Exception):
    pass


@dataclass(frozen=True)
class _Matrix:
    entries: tuple[tuple[Fraction, ...], ...]

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.entries), len(self.entries[0])


type _Value = int | Fraction | _Matrix


class _Evaluator:
    def __init__(self, carrier: str) -> None:
        self.carrier = carrier
        self.operations = 0

    def tick(self) -> None:
        self.operations += 1
        if self.operations > _MAX_OPERATIONS:
            raise _Unknown

    def bounded(self, value: Fraction) -> Fraction:
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > _MAX_BITS:
            raise _Unknown
        return value

    def add(self, left: Fraction, right: Fraction) -> Fraction:
        self.tick()
        return self.bounded(left + right)

    def mul(self, left: Fraction, right: Fraction) -> Fraction:
        self.tick()
        return self.bounded(left * right)

    def div(self, left: Fraction, right: Fraction) -> Fraction:
        self.tick()
        if right == 0:
            raise _Unknown
        return self.bounded(left / right)

    def carrier_argument(self, node: ET.Element) -> None:
        if node.tag != _NS + "OMV" or node.attrib != {"name": self.carrier} or len(node):
            raise _Unknown

    def natural(self, node: ET.Element) -> int:
        if node.tag != _NS + "OMI" or len(node):
            raise _Unknown
        text = (node.text or "").strip()
        if len(text) > _MAX_DIGITS or re.fullmatch(r"[0-9]+", text) is None:
            raise _Unknown
        value = int(text)
        if value.bit_length() > _MAX_BITS:
            raise _Unknown
        return value

    def dimension(self, node: ET.Element) -> int:
        value = self.natural(node)
        if not 1 <= value <= 8:
            raise _Unknown
        return value

    @staticmethod
    def matrix(value: _Value) -> _Matrix:
        if not isinstance(value, _Matrix):
            raise _Unknown
        return value

    @staticmethod
    def scalar(value: _Value) -> Fraction:
        if not isinstance(value, Fraction):
            raise _Unknown
        return value

    def product(self, left: _Matrix, right: _Matrix) -> _Matrix:
        rows, inner = left.shape
        if inner != right.shape[0]:
            raise _Unknown
        columns = right.shape[1]
        result = []
        for i in range(rows):
            row = []
            for j in range(columns):
                value = Fraction(0)
                for k in range(inner):
                    value = self.add(value, self.mul(left.entries[i][k], right.entries[k][j]))
                row.append(value)
            result.append(tuple(row))
        return _Matrix(tuple(result))

    def elimination(self, matrix: _Matrix) -> tuple[int, Fraction]:
        """Exact rational row elimination; determinant meaningful only for square input."""
        rows, columns = matrix.shape
        values = [list(row) for row in matrix.entries]
        rank = 0
        determinant = Fraction(1)
        for column in range(columns):
            pivot = next((i for i in range(rank, rows) if values[i][column] != 0), None)
            if pivot is None:
                continue
            if pivot != rank:
                values[pivot], values[rank] = values[rank], values[pivot]
                determinant = -determinant
            pivot_value = values[rank][column]
            determinant = self.mul(determinant, pivot_value)
            for i in range(rank + 1, rows):
                factor = self.div(values[i][column], pivot_value)
                for j in range(column, columns):
                    values[i][j] = self.add(values[i][j], -self.mul(factor, values[rank][j]))
            rank += 1
            if rank == rows:
                break
        return rank, determinant if rank == rows else Fraction(0)

    def expression(self, node: ET.Element) -> _Value:
        self.tick()
        if node.tag == _NS + "OMI":
            return self.natural(node)
        if node.tag != _NS + "OMA" or not len(node):
            raise _Unknown
        operator, *args = list(node)
        name = _matrix_operator(operator)
        if name in {"literal", "zero", "identity", "field_nat_cast"}:
            if not args:
                raise _Unknown
            self.carrier_argument(args[0])
            if name == "field_nat_cast":
                _arity(args, 2)
                return self.bounded(Fraction(self.natural(args[1])))
            if name == "identity":
                _arity(args, 2)
                rows = columns = self.dimension(args[1])
            else:
                if len(args) < 3:
                    raise _Unknown
                rows, columns = self.dimension(args[1]), self.dimension(args[2])
            if name == "literal":
                _arity(args, 3 + rows * columns)
                entries = [self.scalar(self.expression(entry)) for entry in args[3:]]
                return _Matrix(
                    tuple(tuple(entries[i * columns : (i + 1) * columns]) for i in range(rows))
                )
            _arity(args, 2 if name == "identity" else 3)
            return _Matrix(
                tuple(
                    tuple(Fraction(int(name == "identity" and i == j)) for j in range(columns))
                    for i in range(rows)
                )
            )
        if name in {"neg", "transpose", "determinant", "rank"}:
            _arity(args, 1)
            matrix = self.matrix(self.expression(args[0]))
            if name == "neg":
                return _Matrix(tuple(tuple(-v for v in row) for row in matrix.entries))
            if name == "transpose":
                return _Matrix(tuple(zip(*matrix.entries, strict=True)))
            if name == "determinant" and matrix.shape[0] != matrix.shape[1]:
                raise _Unknown
            rank, determinant = self.elimination(matrix)
            return rank if name == "rank" else determinant
        if name in {"add", "mul", "scale"}:
            _arity(args, 2)
            left, right = self.expression(args[0]), self.expression(args[1])
            if name == "scale":
                scalar, matrix = self.scalar(left), self.matrix(right)
                return _Matrix(
                    tuple(tuple(self.mul(scalar, value) for value in row) for row in matrix.entries)
                )
            first, second = self.matrix(left), self.matrix(right)
            if name == "mul":
                return self.product(first, second)
            if first.shape != second.shape:
                raise _Unknown
            return _Matrix(
                tuple(
                    tuple(self.add(a, b) for a, b in zip(x, y, strict=True))
                    for x, y in zip(first.entries, second.entries, strict=True)
                )
            )
        raise _Unknown

    def proposition(self, node: ET.Element) -> bool:
        if node.tag != _NS + "OMA" or len(node) != 3:
            raise _Unknown
        operator, left, right = list(node)
        if _symbol(operator, _STANDARD, "relation1", "eq") or _symbol(
            operator, _STANDARD, "relation1", "neq"
        ):
            a, b = self.expression(left), self.expression(right)
            if type(a) is not type(b):
                raise _Unknown
            equal = a == b
            return equal if operator.get("name") == "eq" else not equal
        if _symbol(operator, _BASE, "matrix1", "is_inverse"):
            a, b = self.matrix(self.expression(left)), self.matrix(self.expression(right))
            if a.shape != b.shape or a.shape[0] != a.shape[1]:
                raise _Unknown
            size = a.shape[0]
            identity = _Matrix(
                tuple(tuple(Fraction(int(i == j)) for j in range(size)) for i in range(size))
            )
            return self.product(a, b) == identity and self.product(b, a) == identity
        raise _Unknown


def _arity(arguments: list[ET.Element], expected: int) -> None:
    if len(arguments) != expected:
        raise _Unknown


def _symbol(node: ET.Element, base: str, cd: str, name: str) -> bool:
    return (
        node.tag == _NS + "OMS"
        and not len(node)
        and node.attrib
        == {
            "cdbase": base,
            "cd": cd,
            "name": name,
        }
    )


def _matrix_operator(node: ET.Element) -> str:
    name = node.get("name", "")
    if not _symbol(node, _BASE, "matrix1", name):
        raise _Unknown
    return name


def _universal_body(root: ET.Element) -> tuple[str, ET.Element]:
    if root.tag != _NS + "OMOBJ" or len(root) != 1:
        raise _Unknown
    binder = root[0]
    if binder.tag != _NS + "OMBIND" or len(binder) != 3:
        raise _Unknown
    operator, declarations, body = list(binder)
    if not _symbol(operator, _BASE, "typed1", "forall"):
        raise _Unknown
    if declarations.tag != _NS + "OMBVAR" or len(declarations) != 1:
        raise _Unknown
    declaration = declarations[0]
    if declaration.tag != _NS + "OMATTR" or len(declaration) != 2:
        raise _Unknown
    annotation, variable = list(declaration)
    if annotation.tag != _NS + "OMATP" or len(annotation) != 2:
        raise _Unknown
    if (
        not _symbol(annotation[0], _BASE, "typed1", "type")
        or not _symbol(annotation[1], _BASE, "algebra1", "Field")
        or variable.tag != _NS + "OMV"
        or len(variable)
        or set(variable.attrib) != {"name"}
        or not variable.attrib["name"]
    ):
        raise _Unknown
    return variable.attrib["name"], body


def has_rational_counterexample(profile_id: str, canonical_xml: str) -> bool:
    """Return True only for a bounded exact-Q counterexample, otherwise no claim."""
    if profile_id != _PROFILE or not isinstance(canonical_xml, str):
        return False
    try:
        if len(canonical_xml.encode("utf-8")) > _MAX_BYTES or "<!" in canonical_xml:
            return False
        root = ET.fromstring(canonical_xml)
        stack = [(root, 1)]
        count = 0
        while stack:
            node, depth = stack.pop()
            count += 1
            if depth > _MAX_DEPTH or count > _MAX_NODES:
                return False
            stack.extend((child, depth + 1) for child in node)
        carrier, body = _universal_body(root)
        return not _Evaluator(carrier).proposition(body)
    except (_Unknown, ET.ParseError, UnicodeError, ValueError, OverflowError, RecursionError):
        return False
