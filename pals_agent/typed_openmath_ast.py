"""Profile-aware expression transport; serialization never completes mathematics."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from pals_agent.typed_expression_signatures import signatures, sort_signatures

SCHEMA_VERSION = "pals.typed-openmath-expression.v5"
MAX_BYTES = 262_144
MAX_NODES = 4096
MAX_DEPTH = 64
MAX_TEXT = 20_000
_NAMESPACE = "http://www.openmath.org/OpenMath"
_MATRIX_LITERALS = {
    ("urn:pals:openmath:typed-math:v1", "matrix1", "literal"): ("matrix_literal", "v3"),
    ("urn:pals:openmath:typed-math:v1", "matrix1", "column_literal"): ("column_literal", "v2"),
}
_FIELDS = {
    "0": (),
    "1": ("argument",),
    "2": ("left", "right"),
    "relation": ("lhs", "rhs"),
    **{str(n): tuple(f"argument{i}" for i in range(1, n + 1)) for n in range(3, 7)},
}
_KINDS = {
    "0": "nullary",
    "1": "unary",
    "2": "binary",
    "relation": "relation",
    **{str(n): f"application{n}" for n in range(3, 7)},
    "v2": "variadic2",
    "v3": "variadic3",
    "atom": "symbol",
    "binder": "binder",
}


class TypedOpenMathASTError(ValueError):
    """Closed diagnostic; no provider prose or exception text."""


def _closed(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _symbol_schema(symbols: list[tuple[str, str, str]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[str]] = {}
    for base, cd, name in symbols:
        groups.setdefault((base, cd), []).append(name)
    variants = [
        _closed(
            {
                "cdbase": {"type": "string", "enum": [base]},
                "cd": {"type": "string", "enum": [cd]},
                "name": {"type": "string", "enum": sorted(names)},
            }
        )
        for (base, cd), names in sorted(groups.items())
    ]
    return variants[0] if len(variants) == 1 else {"anyOf": variants}


def response_schema(profile_id: str) -> dict[str, Any]:
    mapping = signatures(profile_id)
    sorts = sort_signatures(profile_id)
    expr = {"$ref": "#/$defs/expression"}
    string = {"type": "string"}
    variants = [
        _closed({"kind": {"type": "string", "enum": ["variable"]}, "name": string}),
        _closed({"kind": {"type": "string", "enum": ["integer"]}, "value": string}),
    ]
    definitions: dict[str, Any] = {}
    for signature, kind in _KINDS.items():
        allowed = [
            s
            for s, kinds in mapping.items()
            if signature in kinds and s not in sorts and s not in _MATRIX_LITERALS
        ]
        if not allowed:
            continue
        props = {"kind": {"type": "string", "enum": [kind]}, "operator": _symbol_schema(allowed)}
        if signature in _FIELDS:
            props.update({field: expr for field in _FIELDS[signature]})
        elif signature.startswith("v"):
            props["arguments"] = {
                "type": "array",
                "items": expr,
                "minItems": int(signature[1:]),
                "maxItems": MAX_NODES,
            }
        elif signature == "binder":
            if profile_id == "typed-geometry-complex-v1":
                declaration = _closed({"name": string})
            else:
                declaration = _closed(
                    {
                        "name": string,
                        "type_key": _symbol_schema(
                            [s for s, kinds in mapping.items() if "type" in kinds]
                        ),
                        "sort": {"$ref": "#/$defs/sort"},
                    }
                )
            definitions["declaration"] = declaration
            props["declarations"] = {
                "type": "array",
                "items": {"$ref": "#/$defs/declaration"},
                "minItems": 1,
                "maxItems": MAX_NODES,
            }
            props["body"] = expr
        variants.append(_closed(props))
    if profile_id == "typed-math-matrix-v1":
        # Exactly the validator's Elem(K)-producing forms. Variables' sort and
        # determinants' carrier/square shape remain full-validator obligations.
        base = "urn:pals:openmath:typed-math:v1"
        variable = _closed({"kind": {"type": "string", "enum": ["variable"]}, "name": string})
        definitions["matrix_scalar"] = {
            "anyOf": [
                variable,
                _closed(
                    {
                        "kind": {"type": "string", "enum": ["binary"]},
                        "operator": _symbol_schema([(base, "matrix1", "field_nat_cast")]),
                        "left": {
                            **variable,
                            "description": "The previously bound Field variable, e.g. K.",
                        },
                        "right": _closed(
                            {
                                "kind": {"type": "string", "enum": ["integer"]},
                                "value": {
                                    "type": "string",
                                    "description": (
                                        "Exact nonnegative entry numeral as text; "
                                        "not a matrix dimension."
                                    ),
                                },
                            }
                        ),
                    }
                ),
                _closed(
                    {
                        "kind": {"type": "string", "enum": ["unary"]},
                        "operator": _symbol_schema([(base, "matrix1", "determinant")]),
                        "argument": expr,
                    }
                ),
            ]
        }
    # Literal payload slots are explicit: dimensions cannot replace or hide entries.
    for identity, (kind, _signature) in _MATRIX_LITERALS.items():
        if identity not in mapping:
            continue
        dimension = _closed(
            {
                "kind": {"type": "string", "enum": ["integer"]},
                "value": {"type": "string", "enum": [str(n) for n in range(1, 9)]},
            }
        )
        props = {
            "kind": {"type": "string", "enum": [kind]},
            "operator": _symbol_schema([identity]),
            "carrier": _closed({"kind": {"type": "string", "enum": ["variable"]}, "name": string}),
            "rows": dimension,
        }
        if kind == "matrix_literal":
            props["columns"] = dimension
        props["entries"] = {
            "type": "array",
            "items": {"$ref": "#/$defs/matrix_scalar"},
            "minItems": 1,
            "maxItems": 64 if kind == "matrix_literal" else 8,
            "description": "Preserve every supplied entry in row-major order, without replacement.",
        }
        variants.append(_closed(props))
    if sorts:
        sort_variants = []
        for pattern in sorted(set(sorts.values())):
            signature = str(len(pattern)) if pattern else "atom"
            props = {
                "kind": {"type": "string", "enum": [_KINDS[signature]]},
                "operator": _symbol_schema([s for s, p in sorts.items() if p == pattern]),
            }
            for field, slot in zip(_FIELDS.get(signature, ()), pattern, strict=True):
                props[field] = (
                    _closed({"kind": {"type": "string", "enum": ["variable"]}, "name": string})
                    if slot == "v"
                    else _closed(
                        {
                            "kind": {"type": "string", "enum": ["integer"]},
                            "value": {"type": "string", "enum": [str(n) for n in range(1, 9)]},
                        }
                    )
                )
            sort_variants.append(_closed(props))
        definitions["sort"] = {"anyOf": sort_variants}
    definitions["expression"] = {"anyOf": variants}
    schema = _closed({"version": {"type": "string", "enum": ["2.0"]}, "body": expr})
    schema["$defs"] = definitions
    return schema


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TypedOpenMathASTError("AST duplicate JSON member")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise TypedOpenMathASTError("AST non-JSON numeric constant")


def _xml_text(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise TypedOpenMathASTError("AST string type or size invalid")
    if any(
        not (
            ord(c) in (9, 10, 13)
            or 0x20 <= ord(c) <= 0xD7FF
            or 0xE000 <= ord(c) <= 0xFFFD
            or 0x10000 <= ord(c) <= 0x10FFFF
        )
        for c in value
    ):
        raise TypedOpenMathASTError("AST invalid XML character")
    return value


def to_openmath_xml(raw: str, profile_id: str) -> str:
    mapping = signatures(profile_id)
    sorts = sort_signatures(profile_id)
    if not isinstance(raw, str):
        raise TypedOpenMathASTError("Expression response must be JSON text")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeError:
        raise TypedOpenMathASTError("AST invalid Unicode") from None
    if size > MAX_BYTES:
        raise TypedOpenMathASTError("AST response byte bound exceeded")
    try:
        parsed = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
    except TypedOpenMathASTError:
        raise
    except (ValueError, RecursionError):
        raise TypedOpenMathASTError("AST malformed or excessively nested JSON") from None
    count = 0

    def fields(value: object, expected: set[str]) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != expected:
            raise TypedOpenMathASTError("Expression fields invalid")
        return value

    def element(tag: str, attrs: dict[str, str] | None = None) -> ET.Element:
        nonlocal count
        count += 1
        if count > MAX_NODES:
            raise TypedOpenMathASTError("AST tree resource bound exceeded")
        return ET.Element(tag, attrs or {})

    def symbol(value: object, signature: str, *, sort_context: bool = False) -> ET.Element:
        obj = fields(value, {"cdbase", "cd", "name"})
        attrs = {key: _xml_text(obj[key]) for key in ("cdbase", "cd", "name")}
        identity = (attrs["cdbase"], attrs["cd"], attrs["name"])
        if signature not in mapping.get(identity, frozenset()):
            raise TypedOpenMathASTError("Expression operator signature invalid")
        if (identity in sorts) != sort_context:
            raise TypedOpenMathASTError("Sort/expression operator context invalid")
        return element("OMS", attrs)

    def sequence(value: object, minimum: int) -> list[Any]:
        if not isinstance(value, list) or not minimum <= len(value) <= MAX_NODES:
            raise TypedOpenMathASTError("Expression sequence size invalid")
        return value

    by_kind = {kind: signature for signature, kind in _KINDS.items()}

    def node(value: object, depth: int) -> ET.Element:
        if depth > MAX_DEPTH:
            raise TypedOpenMathASTError("AST tree resource bound exceeded")
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise TypedOpenMathASTError("Expression kind invalid")
        kind = value["kind"]
        if kind == "variable":
            obj = fields(value, {"kind", "name"})
            return element("OMV", {"name": _xml_text(obj["name"])})
        if kind == "integer":
            obj = fields(value, {"kind", "value"})
            result = element("OMI")
            result.text = _xml_text(obj["value"])
            return result
        if kind in {"matrix_literal", "column_literal"}:
            literal_fields = {"kind", "operator", "carrier", "rows", "entries"}
            if kind == "matrix_literal":
                literal_fields.add("columns")
            obj = fields(value, literal_fields)
            expected = next(identity for identity, (k, _) in _MATRIX_LITERALS.items() if k == kind)
            if obj["operator"] != dict(zip(("cdbase", "cd", "name"), expected, strict=True)):
                raise TypedOpenMathASTError("Literal operator invalid")
            carrier = fields(obj["carrier"], {"kind", "name"})
            if carrier["kind"] != "variable":
                raise TypedOpenMathASTError("Literal carrier must be a bound variable")
            dimensions = []
            for field in ("rows", "columns") if kind == "matrix_literal" else ("rows",):
                dimension = fields(obj[field], {"kind", "value"})
                if dimension["kind"] != "integer" or dimension["value"] not in tuple(
                    str(n) for n in range(1, 9)
                ):
                    raise TypedOpenMathASTError("Literal dimension must be direct integer 1..8")
                dimensions.append(dimension)
            entries = sequence(obj["entries"], 1)
            required = int(dimensions[0]["value"]) * (
                int(dimensions[1]["value"]) if len(dimensions) == 2 else 1
            )
            if len(entries) != required:
                raise TypedOpenMathASTError("Literal entry count does not match dimensions")
            result = element("OMA")
            result.append(symbol(obj["operator"], _MATRIX_LITERALS[expected][1]))
            result.extend(node(arg, depth + 1) for arg in (carrier, *dimensions))
            result.extend(scalar_node(entry, depth + 1) for entry in entries)
            return result
        signature = by_kind.get(kind)
        if signature is None:
            raise TypedOpenMathASTError("Expression kind invalid")
        if signature == "atom":
            obj = fields(value, {"kind", "operator"})
            return symbol(obj["operator"], signature)
        if signature == "binder":
            obj = fields(value, {"kind", "operator", "declarations", "body"})
            result = element("OMBIND")
            result.append(symbol(obj["operator"], signature))
            declarations = element("OMBVAR")
            for declaration in sequence(obj["declarations"], 1):
                if profile_id == "typed-geometry-complex-v1":
                    decl = fields(declaration, {"name"})
                    declarations.append(element("OMV", {"name": _xml_text(decl["name"])}))
                else:
                    decl = fields(declaration, {"name", "type_key", "sort"})
                    attributed = element("OMATTR")
                    pair = element("OMATP")
                    pair.append(symbol(decl["type_key"], "type"))
                    pair.append(sort_node(decl["sort"], depth + 1))
                    attributed.append(pair)
                    attributed.append(element("OMV", {"name": _xml_text(decl["name"])}))
                    declarations.append(attributed)
            result.extend((declarations, node(obj["body"], depth + 1)))
            return result
        if signature in _FIELDS:
            names = _FIELDS[signature]
            obj = fields(value, {"kind", "operator", *names})
            arguments = [obj[name] for name in names]
        else:
            obj = fields(value, {"kind", "operator", "arguments"})
            arguments = sequence(obj["arguments"], int(signature[1:]))
        operator_value = obj["operator"]
        if isinstance(operator_value, dict) and any(
            operator_value == dict(zip(("cdbase", "cd", "name"), identity, strict=True))
            for identity in _MATRIX_LITERALS
        ):
            raise TypedOpenMathASTError("Literal requires explicit carrier, dimensions and entries")
        result = element("OMA")
        result.append(symbol(obj["operator"], signature))
        result.extend(node(arg, depth + 1) for arg in arguments)
        return result

    def scalar_node(value: object, depth: int) -> ET.Element:
        if not isinstance(value, dict):
            raise TypedOpenMathASTError("Matrix entry must be a scalar expression")
        kind = value.get("kind")
        if kind == "variable":
            fields(value, {"kind", "name"})
        elif kind == "binary":
            obj = fields(value, {"kind", "operator", "left", "right"})
            if obj["operator"] != {
                "cdbase": "urn:pals:openmath:typed-math:v1",
                "cd": "matrix1",
                "name": "field_nat_cast",
            }:
                raise TypedOpenMathASTError("Matrix entry must be a scalar expression")
            if (
                not isinstance(obj["left"], dict)
                or obj["left"].get("kind") != "variable"
                or not isinstance(obj["right"], dict)
                or obj["right"].get("kind") != "integer"
            ):
                raise TypedOpenMathASTError(
                    "Scalar cast requires Field variable and direct integer"
                )
        elif kind == "unary":
            obj = fields(value, {"kind", "operator", "argument"})
            if obj["operator"] != {
                "cdbase": "urn:pals:openmath:typed-math:v1",
                "cd": "matrix1",
                "name": "determinant",
            }:
                raise TypedOpenMathASTError("Matrix entry must be a scalar expression")
        else:
            raise TypedOpenMathASTError("Matrix entry must be a scalar expression")
        return node(value, depth)

    def sort_node(value: object, depth: int) -> ET.Element:
        if depth > MAX_DEPTH or not isinstance(value, dict):
            raise TypedOpenMathASTError("Sort expression invalid")
        kind = value.get("kind")
        if not isinstance(kind, str):
            raise TypedOpenMathASTError("Sort expression kind invalid")
        signature = by_kind.get(kind)
        if signature not in {"atom", "1", "2", "3"}:
            raise TypedOpenMathASTError("Sort expression kind invalid")
        names = _FIELDS.get(signature, ())
        obj = fields(value, {"kind", "operator", *names})
        operator = symbol(obj["operator"], signature, sort_context=True)
        pattern = sorts[(operator.attrib["cdbase"], operator.attrib["cd"], operator.attrib["name"])]
        if signature == "atom":
            return operator
        result = element("OMA")
        result.append(operator)
        for field, slot in zip(names, pattern, strict=True):
            argument = obj[field]
            if not isinstance(argument, dict) or argument.get("kind") != (
                "variable" if slot == "v" else "integer"
            ):
                raise TypedOpenMathASTError("Sort argument must be direct variable or dimension")
            if slot == "i" and argument.get("value") not in tuple(str(n) for n in range(1, 9)):
                raise TypedOpenMathASTError("Sort dimension must be direct integer 1..8")
            result.append(node(argument, depth + 1))
        return result

    doc = fields(parsed, {"version", "body"})
    if doc["version"] != "2.0":
        raise TypedOpenMathASTError("Expression document version invalid")
    root = element("OMOBJ", {"version": doc["version"], "xmlns": _NAMESPACE})
    root.append(node(doc["body"], 1))
    xml = ET.tostring(root, encoding="unicode")
    if len(xml.encode("utf-8")) > MAX_BYTES:
        raise TypedOpenMathASTError("AST serialized XML byte bound exceeded")
    return xml
