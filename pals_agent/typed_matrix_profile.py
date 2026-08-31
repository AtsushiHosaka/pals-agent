"""Fail-closed OpenMath validation for ``typed-math-matrix-v1``.

This is an explicit sibling of :mod:`pals_agent.typed_math`, not an extension
of it.  The generic retrieval profile and the group/ring profile therefore
retain their fixed accepted languages.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from importlib import resources
from typing import Literal, cast

from .openmath import (
    OPENMATH_NAMESPACE,
    OPENMATH_STANDARD_CDBASE,
    MathXMLValidationError,
    _canonicalize_openmath_v4_root,
    _element_depth,
    _local_name,
    _openmath_parents,
    _operator_symbol,
    validate_openmath_xml,
)
from .typed_math import TYPED_MATH_OPENMATH_CDBASE

TYPED_MATRIX_PROFILE = "typed-math-matrix-v1"

_MatrixSortName = Literal["prop", "nat", "field", "element", "matrix", "vector"]
_Symbol = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class TypedMatrixSort:
    """A sort in the finite-dimensional field matrix profile."""

    name: _MatrixSortName
    carrier: str | None = None
    rows: int | None = None
    columns: int | None = None

    def render(self) -> str:
        if self.name == "field":
            return f"Field({self.carrier})" if self.carrier is not None else "Field"
        if self.name == "element":
            assert self.carrier is not None
            return f"Elem({self.carrier})"
        if self.name == "matrix":
            assert self.carrier is not None and self.rows is not None and self.columns is not None
            return f"Matrix({self.carrier},{self.rows},{self.columns})"
        if self.name == "vector":
            assert self.carrier is not None and self.rows is not None
            return f"ColumnVector({self.carrier},{self.rows})"
        return {"prop": "Prop", "nat": "Nat"}[self.name]


_PROP = TypedMatrixSort("prop")
_NAT = TypedMatrixSort("nat")
_FIELD = TypedMatrixSort("field")
_TYPED_BINDERS = frozenset({"forall", "exists"})
_LOGICAL_APPLICATIONS = frozenset({"and", "or", "implies", "equivalent"})
_UNARY_LOGICAL_APPLICATIONS = frozenset({"not"})
_RELATION_APPLICATIONS = frozenset({"eq", "neq"})
_MATRIX_OPERATIONS = frozenset(
    {
        "field_nat_cast",
        "literal",
        "column_literal",
        "zero",
        "identity",
        "add",
        "neg",
        "scale",
        "mul",
        "transpose",
        "determinant",
        "rank",
        "is_inverse",
        "mul_vec",
    }
)


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-math-matrix-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-matrix-v1 symbol registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-math-matrix-registry.v1"
        or payload.get("profile_id") != TYPED_MATRIX_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_MATH_OPENMATH_CDBASE,
        }
    ):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-matrix-v1 symbol registry header is invalid.")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-matrix-v1 symbol registry has no symbols list.")
    identities: set[_Symbol] = set()
    for entry in symbols:
        if not isinstance(entry, dict):  # pragma: no cover - packaging invariant
            raise RuntimeError("typed-math-matrix-v1 symbol registry entry is invalid.")
        identity = tuple(entry.get(field) for field in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed-math-matrix-v1 symbol registry identity is invalid.")
        identities.add(cast(_Symbol, identity))
    if len(identities) != len(symbols):  # pragma: no cover - packaging invariant
        raise RuntimeError("typed-math-matrix-v1 symbol registry contains duplicates.")
    return frozenset(identities)


_TYPED_MATRIX_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_matrix_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed matrix-profile proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed-matrix byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_matrix_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_matrix_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for the matrix profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-matrix canonical bytes.")
    canonical = canonicalize_typed_matrix_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact typed-matrix canonical bytes.")
    return canonical


def validate_typed_matrix_openmath_xml(xml: str) -> None:
    """Validate one closed ``typed-math-matrix-v1`` proposition."""
    root = validate_openmath_xml(xml)
    validate_typed_matrix_openmath_root(root)


def validate_typed_matrix_openmath_root(root: ET.Element) -> None:
    """Validate a core-validated OpenMath tree under this explicit profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed-matrix tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_typed_matrix_tree_shape(root, nodes=nodes, parents=parents)
    if not _contains_matrix_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed-math-matrix-v1 proposition.")
    expression = list(root)[0]
    inferred = _infer_expression(expression, environment={}, parents=parents, path="root")
    if inferred != _PROP:
        raise MathXMLValidationError("typed-math-matrix-v1 root must have sort `Prop`.")


def _validate_typed_matrix_tree_shape(
    root: ET.Element,
    *,
    nodes: list[ET.Element],
    parents: dict[ET.Element, ET.Element],
) -> None:
    allowed = {"OMOBJ", "OMS", "OMV", "OMI", "OMA", "OMBIND", "OMBVAR", "OMATTR", "OMATP"}
    for element in nodes:
        local_name = _local_name(element)
        if local_name not in allowed:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` is outside typed-math-matrix-v1."
            )
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed-matrix tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("OpenMath typed-matrix text exceeds 20,000 code points.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("OpenMath typed-matrix elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "OpenMath typed-matrix attribute exceeds 20,000 code points."
            )
        if local_name == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_typed_declaration_annotation(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed-math-matrix-v1 permits OMATTR only as one typed OMBVAR declaration."
                )
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_typed_declaration_annotation(declaration, parents=parents)
                for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "typed-math-matrix-v1 OMBVAR requires 1..256 typed OMV declarations."
                )
        if local_name == "OMBIND":
            binder, _variables, _body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if (
                symbol is None
                or symbol[0:2] != (TYPED_MATH_OPENMATH_CDBASE, "typed1")
                or symbol[2] not in _TYPED_BINDERS
            ):
                raise MathXMLValidationError(
                    "typed-math-matrix-v1 OMBIND must use typed1:forall or typed1:exists."
                )
        if local_name == "OMA" and _local_name(list(element)[0]) != "OMS":
            raise MathXMLValidationError("typed-math-matrix-v1 OMA head must be an OMS.")
        if local_name == "OMS":
            _validate_typed_matrix_symbol(element, parents=parents)


def _validate_typed_matrix_symbol(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed-math-matrix-v1 OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_MATH_OPENMATH_CDBASE and direct_cdbase != symbol[0]:
        raise MathXMLValidationError(
            "typed-math-matrix-v1 OMS must directly declare its typed cdbase."
        )
    if symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed-math-matrix-v1 OMS may omit cdbase only without "
                    "inherited cdbase."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _TYPED_MATRIX_SYMBOL_REGISTRY:
        cdbase, cd, name = symbol
        raise MathXMLValidationError(
            f"Symbol `{cd}:{name}` with cdbase `{cdbase}` is outside typed-math-matrix-v1."
        )


def _contains_matrix_profile_construct(
    root: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    has_typed_binder = False
    has_type_annotation = False
    has_matrix_construct = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None:
            continue
        if symbol[0:2] == (TYPED_MATH_OPENMATH_CDBASE, "typed1"):
            has_typed_binder = has_typed_binder or symbol[2] in _TYPED_BINDERS
            has_type_annotation = has_type_annotation or symbol[2] == "type"
        has_matrix_construct = has_matrix_construct or symbol[0:2] == (
            TYPED_MATH_OPENMATH_CDBASE,
            "matrix1",
        )
    return has_typed_binder and has_type_annotation and has_matrix_construct


def _is_typed_declaration_annotation(
    declaration: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    if _local_name(declaration) != "OMATTR" or len(list(declaration)) != 2:
        return False
    attributes, variable = list(declaration)
    if _local_name(attributes) != "OMATP" or _local_name(variable) != "OMV":
        return False
    pairs = list(attributes)
    if len(pairs) != 2 or _local_name(pairs[0]) != "OMS":
        return False
    return _operator_symbol(pairs[0], parents=parents) == (
        TYPED_MATH_OPENMATH_CDBASE,
        "typed1",
        "type",
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, TypedMatrixSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedMatrixSort:
    local_name = _local_name(expression)
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed-math-matrix-v1 has a free or undeclared variable `{name or ''}` at {path}."
            )
        declared_sort = environment[name]
        if declared_sort.name == "field":
            return TypedMatrixSort("field", name)
        return declared_sort
    if local_name == "OMI":
        value = "".join((expression.text or "").split())
        if value.startswith("-"):
            raise MathXMLValidationError(
                "typed-math-matrix-v1 does not admit negative OMI literals."
            )
        return _NAT
    if local_name == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"typed-math-matrix-v1 cannot infer a sort for `{local_name}` at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed-math-matrix-v1 OMA has an invalid operator at {path}.")
    argument_sorts = [
        _infer_expression(
            argument,
            environment=environment,
            parents=parents,
            path=f"{path}/{index}",
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, argument_sorts, argument_nodes=arguments, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, TypedMatrixSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedMatrixSort:
    binder, variables, body = list(binding)
    symbol = _operator_symbol(binder, parents=parents)
    assert symbol is not None
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration,
            environment=local_environment,
            parents=parents,
            path=f"{path}/bind/{index}",
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed-math-matrix-v1 redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
    body_sort = _infer_expression(
        body,
        environment=local_environment,
        parents=parents,
        path=f"{path}/body",
    )
    if body_sort != _PROP:
        raise MathXMLValidationError(
            f"The body of `{symbol[1]}:{symbol[2]}` must have sort `Prop`; "
            f"received `{body_sort.render()}`."
        )
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, TypedMatrixSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, TypedMatrixSort]:
    attributes, variable = list(declaration)
    _key, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(
            f"typed-math-matrix-v1 bound OMV is missing `name` at {path}."
        )
    return name, _parse_sort(sort_expression, environment=environment, parents=parents, path=path)


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, TypedMatrixSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> TypedMatrixSort:
    if _local_name(expression) == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        if symbol == (TYPED_MATH_OPENMATH_CDBASE, "algebra1", "Field"):
            return _FIELD
    if _local_name(expression) == "OMA":
        operator, *arguments = list(expression)
        symbol = _operator_symbol(operator, parents=parents)
        if symbol == (TYPED_MATH_OPENMATH_CDBASE, "typed1", "Elem") and len(arguments) == 1:
            return TypedMatrixSort(
                "element", _parse_field_variable(arguments[0], environment, path=path)
            )
        if symbol == (TYPED_MATH_OPENMATH_CDBASE, "matrix1", "Matrix") and len(arguments) == 3:
            return TypedMatrixSort(
                "matrix",
                _parse_field_variable(arguments[0], environment, path=path),
                _parse_dimension(arguments[1], path=path),
                _parse_dimension(arguments[2], path=path),
            )
        if (
            symbol == (TYPED_MATH_OPENMATH_CDBASE, "matrix1", "ColumnVector")
            and len(arguments) == 2
        ):
            return TypedMatrixSort(
                "vector",
                _parse_field_variable(arguments[0], environment, path=path),
                _parse_dimension(arguments[1], path=path),
            )
    raise MathXMLValidationError(
        f"typed-math-matrix-v1 has an invalid type annotation at {path}; "
        "expected a supported SortExpr."
    )


def _parse_field_variable(
    expression: ET.Element,
    environment: dict[str, TypedMatrixSort],
    *,
    path: str,
) -> str:
    if _local_name(expression) != "OMV":
        raise MathXMLValidationError(
            f"typed-math-matrix-v1 requires a bound Field variable at {path}."
        )
    name = expression.get("name")
    if name is None or environment.get(name) != _FIELD:
        raise MathXMLValidationError(
            f"typed-math-matrix-v1 requires a previously bound Field variable at {path}."
        )
    return name


def _parse_dimension(expression: ET.Element, *, path: str) -> int:
    if _local_name(expression) != "OMI":
        raise MathXMLValidationError(
            f"typed-math-matrix-v1 requires a direct OMI dimension at {path}."
        )
    text = "".join((expression.text or "").split())
    if text not in {str(value) for value in range(1, 9)}:
        raise MathXMLValidationError(
            f"typed-math-matrix-v1 dimensions must be direct OMI values 1..8 at {path}."
        )
    return int(text)


def _infer_application(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    *,
    argument_nodes: list[ET.Element],
    path: str,
) -> TypedMatrixSort:
    cdbase, cd, name = symbol
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in _RELATION_APPLICATIONS:
        _require_arity(symbol, arguments, exact=2)
        if arguments[0] != arguments[1]:
            raise MathXMLValidationError(
                f"Argument 2 of `{cd}:{name}` at {path} must have sort "
                f"`{arguments[0].render()}`; received `{arguments[1].render()}`."
            )
        return _PROP
    if (cdbase, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in _LOGICAL_APPLICATIONS:
            _require_arity(
                symbol,
                arguments,
                minimum=2,
                maximum=2 if name in {"implies", "equivalent"} else None,
            )
            _require_all(symbol, arguments, _PROP, path=path)
            return _PROP
        if name in _UNARY_LOGICAL_APPLICATIONS:
            _require_arity(symbol, arguments, exact=1)
            _require_argument(symbol, arguments, 0, _PROP, path=path)
            return _PROP
    if (cdbase, cd) == (TYPED_MATH_OPENMATH_CDBASE, "matrix1") and name in _MATRIX_OPERATIONS:
        return _infer_matrix_application(
            symbol,
            arguments,
            argument_nodes=argument_nodes,
            path=path,
        )
    raise MathXMLValidationError(
        f"Unsupported typed-math-matrix-v1 application `{cd}:{name}` at {path}."
    )


def _infer_matrix_application(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    *,
    argument_nodes: list[ET.Element],
    path: str,
) -> TypedMatrixSort:
    _cdbase, _cd, name = symbol
    if name == "field_nat_cast":
        _require_arity(symbol, arguments, exact=2)
        carrier = _require_field_argument(symbol, arguments, 0, path=path)
        _require_argument(symbol, arguments, 1, _NAT, path=path)
        _require_nonnegative_omi_argument(symbol, argument_nodes, 1, path=path)
        return TypedMatrixSort("element", carrier)
    if name == "literal":
        _require_minimum_arity(symbol, arguments, minimum=3)
        carrier = _require_field_argument(symbol, arguments, 0, path=path)
        rows = _require_dimension_argument(symbol, arguments, argument_nodes, 1, path=path)
        columns = _require_dimension_argument(symbol, arguments, argument_nodes, 2, path=path)
        expected_count = rows * columns
        if len(arguments) != 3 + expected_count:
            raise MathXMLValidationError(
                f"`matrix1:literal` at {path} requires exactly {expected_count} entries; "
                f"received {len(arguments) - 3}."
            )
        for index in range(3, len(arguments)):
            _require_argument(
                symbol,
                arguments,
                index,
                TypedMatrixSort("element", carrier),
                path=path,
            )
        return TypedMatrixSort("matrix", carrier, rows, columns)
    if name == "column_literal":
        _require_minimum_arity(symbol, arguments, minimum=2)
        carrier = _require_field_argument(symbol, arguments, 0, path=path)
        rows = _require_dimension_argument(symbol, arguments, argument_nodes, 1, path=path)
        if len(arguments) != 2 + rows:
            raise MathXMLValidationError(
                f"`matrix1:column_literal` at {path} requires exactly {rows} entries; "
                f"received {len(arguments) - 2}."
            )
        for index in range(2, len(arguments)):
            _require_argument(
                symbol,
                arguments,
                index,
                TypedMatrixSort("element", carrier),
                path=path,
            )
        return TypedMatrixSort("vector", carrier, rows)
    if name == "zero":
        _require_arity(symbol, arguments, exact=3)
        carrier = _require_field_argument(symbol, arguments, 0, path=path)
        rows = _require_dimension_argument(symbol, arguments, argument_nodes, 1, path=path)
        columns = _require_dimension_argument(symbol, arguments, argument_nodes, 2, path=path)
        return TypedMatrixSort("matrix", carrier, rows, columns)
    if name == "identity":
        _require_arity(symbol, arguments, exact=2)
        carrier = _require_field_argument(symbol, arguments, 0, path=path)
        dimension = _require_dimension_argument(symbol, arguments, argument_nodes, 1, path=path)
        return TypedMatrixSort("matrix", carrier, dimension, dimension)
    if name == "add":
        _require_arity(symbol, arguments, exact=2)
        left = _require_matrix_argument(symbol, arguments, 0, path=path)
        _require_argument(symbol, arguments, 1, left, path=path)
        return left
    if name == "neg":
        _require_arity(symbol, arguments, exact=1)
        return _require_matrix_argument(symbol, arguments, 0, path=path)
    if name == "scale":
        _require_arity(symbol, arguments, exact=2)
        matrix = _require_matrix_argument(symbol, arguments, 1, path=path)
        assert matrix.carrier is not None
        _require_argument(
            symbol,
            arguments,
            0,
            TypedMatrixSort("element", matrix.carrier),
            path=path,
        )
        return matrix
    if name == "mul":
        _require_arity(symbol, arguments, exact=2)
        left = _require_matrix_argument(symbol, arguments, 0, path=path)
        right = _require_matrix_argument(symbol, arguments, 1, path=path)
        assert left.carrier is not None and left.rows is not None and left.columns is not None
        assert right.carrier is not None and right.rows is not None and right.columns is not None
        if left.carrier != right.carrier or left.columns != right.rows:
            expected = TypedMatrixSort("matrix", left.carrier, left.columns, right.columns)
            raise MathXMLValidationError(
                f"Argument 2 of `matrix1:mul` at {path} must have sort `{expected.render()}`; "
                f"received `{right.render()}`."
            )
        return TypedMatrixSort("matrix", left.carrier, left.rows, right.columns)
    if name == "transpose":
        _require_arity(symbol, arguments, exact=1)
        matrix = _require_matrix_argument(symbol, arguments, 0, path=path)
        assert matrix.carrier is not None and matrix.rows is not None and matrix.columns is not None
        return TypedMatrixSort("matrix", matrix.carrier, matrix.columns, matrix.rows)
    if name == "determinant":
        _require_arity(symbol, arguments, exact=1)
        matrix = _require_matrix_argument(symbol, arguments, 0, path=path)
        assert matrix.carrier is not None and matrix.rows is not None and matrix.columns is not None
        if matrix.rows != matrix.columns:
            raise MathXMLValidationError(
                f"Argument 1 of `matrix1:determinant` at {path} must be square; "
                f"received `{matrix.render()}`."
            )
        return TypedMatrixSort("element", matrix.carrier)
    if name == "rank":
        _require_arity(symbol, arguments, exact=1)
        _require_matrix_argument(symbol, arguments, 0, path=path)
        return _NAT
    if name == "is_inverse":
        _require_arity(symbol, arguments, exact=2)
        left = _require_matrix_argument(symbol, arguments, 0, path=path)
        assert left.rows is not None and left.columns is not None
        if left.rows != left.columns:
            raise MathXMLValidationError(
                f"Argument 1 of `matrix1:is_inverse` at {path} must be square; "
                f"received `{left.render()}`."
            )
        _require_argument(symbol, arguments, 1, left, path=path)
        return _PROP
    if name == "mul_vec":
        _require_arity(symbol, arguments, exact=2)
        matrix = _require_matrix_argument(symbol, arguments, 0, path=path)
        assert matrix.carrier is not None and matrix.rows is not None and matrix.columns is not None
        expected = TypedMatrixSort("vector", matrix.carrier, matrix.columns)
        _require_argument(symbol, arguments, 1, expected, path=path)
        return TypedMatrixSort("vector", matrix.carrier, matrix.rows)
    raise AssertionError(f"Unhandled matrix operation `{name}`.")  # pragma: no cover


def _require_arity(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    *,
    exact: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> None:
    valid = (
        (exact is None or len(arguments) == exact)
        and (minimum is None or len(arguments) >= minimum)
        and (maximum is None or len(arguments) <= maximum)
    )
    if valid:
        return
    _cdbase, cd, name = symbol
    expectation = str(exact) if exact is not None else f"{minimum or 0}..{maximum or 'n'}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_minimum_arity(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    *,
    minimum: int,
) -> None:
    if len(arguments) >= minimum:
        return
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires at least {minimum} arguments; received {len(arguments)}."
    )


def _require_all(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    expected: TypedMatrixSort,
    *,
    path: str,
) -> None:
    for index in range(len(arguments)):
        _require_argument(symbol, arguments, index, expected, path=path)


def _require_argument(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    index: int,
    expected: TypedMatrixSort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if actual == expected:
        return
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort "
        f"`{expected.render()}`; received `{actual.render()}`."
    )


def _require_field_argument(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    index: int,
    *,
    path: str,
) -> str:
    actual = arguments[index]
    if actual.name == "field" and actual.carrier is not None:
        return actual.carrier
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort `Field`; "
        f"received `{actual.render()}`."
    )


def _require_matrix_argument(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    index: int,
    *,
    path: str,
) -> TypedMatrixSort:
    actual = arguments[index]
    if actual.name == "matrix":
        return actual
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have a Matrix sort; "
        f"received `{actual.render()}`."
    )


def _require_dimension_argument(
    symbol: _Symbol,
    arguments: list[TypedMatrixSort],
    argument_nodes: list[ET.Element],
    index: int,
    *,
    path: str,
) -> int:
    _require_argument(symbol, arguments, index, _NAT, path=path)
    return _parse_dimension(argument_nodes[index], path=f"{path}/argument-{index + 1}")


def _require_nonnegative_omi_argument(
    symbol: _Symbol,
    argument_nodes: list[ET.Element],
    index: int,
    *,
    path: str,
) -> None:
    if _local_name(argument_nodes[index]) == "OMI":
        return
    _cdbase, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must be a direct nonnegative OMI."
    )
