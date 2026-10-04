import json
import xml.etree.ElementTree as ET

import pytest

from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.natural_query_tree import tree_to_openmath
from pals_agent.openmath import canonicalize_retrieval_openmath_xml


def fixture_tree(source):
    """Translate only a test fixture; production never reads a seed."""

    def visit(node):
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "OMS":
            return {"kind": "symbol", "symbol": node.attrib["cd"] + ":" + node.attrib["name"]}
        if tag == "OMV":
            return {"kind": "variable", "name": node.attrib["name"]}
        if tag == "OMI":
            return {"kind": "integer", "value": node.text}
        if tag == "OMA":
            return {
                "kind": "apply",
                "operator": node[0].attrib["cd"] + ":" + node[0].attrib["name"],
                "arguments": [visit(child) for child in list(node)[1:]],
            }
        if tag == "OMBIND":
            return {
                "kind": "bind",
                "binder": node[0].attrib["cd"] + ":" + node[0].attrib["name"],
                "variables": [child.attrib["name"] for child in node[1]],
                "body": visit(node[2]),
            }
        raise ValueError(tag)

    return {"expression": visit(ET.fromstring(source)[0])}


@pytest.mark.parametrize(
    "identifier", ["continuous_square", "continuous_power", "continuous_affine"]
)
def test_actual_catalog_query_tree_preserves_v4_semantics(identifier):
    source = SeedDraftCatalog().find_by_id(identifier).openmath_xml
    serialized = tree_to_openmath(json.dumps(fixture_tree(source)))
    assert canonicalize_retrieval_openmath_xml(serialized) == canonicalize_retrieval_openmath_xml(
        source
    )
    ET.fromstring(serialized)  # mismatched closing tags are impossible from the serializer


@pytest.mark.parametrize(
    "tree",
    [
        {"expression": {"kind": "variable", "name": "x", "extra": True}},
        {"expression": {"kind": "integer", "value": "1.5"}},
        {"expression": {"kind": "variable", "name": "x</OMV>"}},
        {"expression": {"kind": "apply", "operator": {}, "arguments": []}},
        {
            "expression": {
                "kind": "bind",
                "binder": "quant1:lambda",
                "variables": ["x"],
                "body": {"kind": "variable", "name": "x"},
            }
        },
    ],
)
def test_invalid_tree_is_not_repaired(tree):
    with pytest.raises(ValueError):
        tree_to_openmath(json.dumps(tree))


def test_duplicate_fields_and_deep_trees_fail_closed():
    with pytest.raises(ValueError, match="Duplicate"):
        tree_to_openmath('{"expression":{},"expression":{}}')
    node = {"kind": "variable", "name": "x"}
    for _ in range(34):
        node = {
            "kind": "bind",
            "binder": "quant1:forall",
            "variables": ["x"],
            "body": node,
        }
    with pytest.raises(ValueError, match="complexity"):
        tree_to_openmath(json.dumps({"expression": node}))


def test_serializer_does_not_bypass_semantic_profile_validation():
    from pals_agent.openmath import MathXMLValidationError

    candidate = tree_to_openmath(json.dumps({"expression": {"kind": "variable", "name": "free"}}))
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(candidate)


def test_symbol_and_binder_schema_use_exact_generic_pairs():
    from pals_agent.natural_query_tree import APPLICATIONS, CONSTANTS, SYMBOLS, TREE_SCHEMA

    variants = TREE_SCHEMA["$defs"]["node"]["anyOf"]
    assert "pals1:continuous_on" in SYMBOLS
    assert "pals1:continuous_at" not in SYMBOLS
    assert variants[0]["properties"]["symbol"]["enum"] == list(CONSTANTS)
    assert "fns1:lambda" not in APPLICATIONS
    assert "quant1:forall" not in APPLICATIONS
    for unsupported in ("pals1:continuous_at", "arith1:continuous_on", "pals1:power"):
        with pytest.raises(ValueError, match="outside generic"):
            tree_to_openmath(json.dumps({"expression": {"kind": "symbol", "symbol": unsupported}}))


def test_binder_cannot_be_misencoded_as_application():
    tree = {
        "expression": {
            "kind": "apply",
            "operator": "fns1:lambda",
            "arguments": [{"kind": "variable", "name": "x"}],
        }
    }
    with pytest.raises(ValueError, match="not a generic application"):
        tree_to_openmath(json.dumps(tree))
