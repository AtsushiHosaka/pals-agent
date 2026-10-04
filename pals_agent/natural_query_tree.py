"""Closed structured output for retrieval queries; serialize XML deterministically."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from pals_agent.openmath import (
    _SUPPORTED_SYMBOLS,
    OPENMATH_NAMESPACE,
    PALS_OPENMATH_CDBASE,
)


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


# Generic retrieval is distinct from typed continuity-v1. Never advertise typed-only
# function/sequence operators to this grammar merely because they share a registry.
_GENERIC_PALS = {
    "continuous_on",
    "compact",
    "rank",
    "nullity",
    "dimension",
    "domain",
    "finite_dimensional",
    "linear_map",
}
SYMBOLS = tuple(
    sorted(
        f"{cd}:{name}"
        for _, cd, name in _SUPPORTED_SYMBOLS
        if cd != "pals1" or name in _GENERIC_PALS
    )
)
BINDERS = ("quant1:forall", "quant1:exists", "fns1:lambda")
APPLICATIONS = tuple(
    sorted(
        f"{cd}:{name}"
        for (_, cd, name), spec in _SUPPORTED_SYMBOLS.items()
        if f"{cd}:{name}" in SYMBOLS and spec.role == "application"
    )
)
CONSTANTS = tuple(
    sorted(
        f"{cd}:{name}"
        for (_, cd, name), spec in _SUPPORTED_SYMBOLS.items()
        if f"{cd}:{name}" in SYMBOLS and spec.role == "constant"
    )
)
_NODE = {"$ref": "#/$defs/node"}
TREE_SCHEMA = _object({"expression": _NODE})
TREE_SCHEMA["$defs"] = {
    "node": {
        "anyOf": [
            _object(
                {
                    "kind": {"type": "string", "enum": ["symbol"]},
                    "symbol": {"type": "string", "enum": list(CONSTANTS)},
                }
            ),
            _object({"kind": {"type": "string", "enum": ["variable"]}, "name": {"type": "string"}}),
            _object({"kind": {"type": "string", "enum": ["integer"]}, "value": {"type": "string"}}),
            _object(
                {
                    "kind": {"type": "string", "enum": ["apply"]},
                    "operator": {"type": "string", "enum": list(APPLICATIONS)},
                    "arguments": {"type": "array", "items": _NODE},
                }
            ),
            _object(
                {
                    "kind": {"type": "string", "enum": ["bind"]},
                    "binder": {"type": "string", "enum": list(BINDERS)},
                    "variables": {"type": "array", "items": {"type": "string"}},
                    "body": _NODE,
                }
            ),
        ]
    }
}
VOCABULARY = ", ".join(SYMBOLS)
_FIELDS = {
    "symbol": {"kind", "symbol"},
    "variable": {"kind", "name"},
    "integer": {"kind", "value"},
    "apply": {"kind", "operator", "arguments"},
    "bind": {"kind", "binder", "variables", "body"},
}
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]{0,30})\Z")


def _closed(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate query field")
        value[key] = item
    return value


def tree_to_openmath(output: str) -> str:
    if len(output.encode()) > 65536:
        raise ValueError("Query tree byte budget exceeded")
    document = json.loads(output, object_pairs_hook=_closed)
    if not isinstance(document, dict) or set(document) != {"expression"}:
        raise ValueError("Query tree root invalid")
    count = 0

    def element(tag: str, attributes: dict[str, str] | None = None) -> ET.Element:
        return ET.Element("{" + OPENMATH_NAMESPACE + "}" + tag, attributes or {})

    def name(value: Any) -> str:
        if not isinstance(value, str) or not _NAME.fullmatch(value):
            raise ValueError("Query name invalid")
        return value

    def symbol(identity: Any) -> ET.Element:
        if not isinstance(identity, str) or identity not in SYMBOLS:
            raise ValueError("Query symbol is outside generic vocabulary")
        cd, symbol_name = identity.split(":", 1)
        attrs = {"cd": cd, "name": symbol_name}
        if cd == "pals1":
            attrs["cdbase"] = PALS_OPENMATH_CDBASE
        return element("OMS", attrs)

    def visit(node: Any, depth: int = 0) -> ET.Element:
        nonlocal count
        count += 1
        if count > 512 or depth > 32:
            raise ValueError("Query tree complexity exceeded")
        if not isinstance(node, dict) or not isinstance(node.get("kind"), str):
            raise ValueError("Query node invalid")
        kind = node["kind"]
        if kind not in _FIELDS or set(node) != _FIELDS[kind]:
            raise ValueError("Query node fields invalid")
        if kind == "symbol":
            if node["symbol"] not in CONSTANTS:
                raise ValueError("Query symbol is outside generic constants")
            return symbol(node["symbol"])
        if kind == "variable":
            return element("OMV", {"name": name(node["name"])})
        if kind == "integer":
            if not isinstance(node["value"], str) or not _INTEGER.fullmatch(node["value"]):
                raise ValueError("Query integer invalid")
            result = element("OMI")
            result.text = node["value"]
            return result
        if kind == "apply":
            arguments = node["arguments"]
            if not isinstance(arguments, list) or not 1 <= len(arguments) <= 32:
                raise ValueError("Query application arity invalid")
            result = element("OMA")
            if not isinstance(node["operator"], str) or node["operator"] not in APPLICATIONS:
                raise ValueError("Query operator is not a generic application")
            result.append(symbol(node["operator"]))
            result.extend(visit(argument, depth + 1) for argument in arguments)
            return result
        binder, variables = node["binder"], node["variables"]
        if (
            not isinstance(binder, str)
            or binder not in BINDERS
            or not isinstance(variables, list)
            or not 1 <= len(variables) <= 16
            or len({name(variable) for variable in variables}) != len(variables)
        ):
            raise ValueError("Query binder invalid")
        result = element("OMBIND")
        result.append(symbol(binder))
        declarations = element("OMBVAR")
        declarations.extend(element("OMV", {"name": name(variable)}) for variable in variables)
        result.append(declarations)
        result.append(visit(node["body"], depth + 1))
        return result

    root = element("OMOBJ", {"version": "2.0"})
    root.append(visit(document["expression"]))
    return ET.tostring(root, encoding="unicode")
