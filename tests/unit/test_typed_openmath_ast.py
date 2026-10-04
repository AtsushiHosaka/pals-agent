import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from pals_agent.private_typed_candidates import profile_contract
from pals_agent.typed_expression_signatures import _GROUPS, signatures, sort_signatures
from pals_agent.typed_openmath_ast import (
    _FIELDS,
    _KINDS,
    TypedOpenMathASTError,
    response_schema,
    to_openmath_xml,
)
from tests.unit.test_typed_algebra_guidance import PROFILES, symbolic_formula
from tests.unit.test_typed_profile_guidance import _GUIDANCE, example

PROFILE = "typed-math-matrix-v1"


def ast_from_xml(xml, profile=PROFILE):
    mapping = signatures(profile)

    def symbol(element):
        return {key: element.attrib[key] for key in ("cdbase", "cd", "name")}

    def node(element):
        tag = element.tag.split("}")[-1]
        if tag == "OMV":
            return {"kind": "variable", "name": element.get("name")}
        if tag == "OMI":
            return {"kind": "integer", "value": element.text}
        if tag == "OMS":
            return {"kind": "symbol", "operator": symbol(element)}
        head = symbol(element[0])
        if tag == "OMBIND":
            declarations = []
            for decl in element[1]:
                if decl.tag.split("}")[-1] == "OMV":
                    declarations.append({"name": decl.get("name")})
                else:
                    declarations.append(
                        {
                            "name": decl[1].get("name"),
                            "type_key": symbol(decl[0][0]),
                            "sort": node(decl[0][1]),
                        }
                    )
            return {
                "kind": "binder",
                "operator": head,
                "declarations": declarations,
                "body": node(element[2]),
            }
        assert tag == "OMA"
        if head["cd"] == "matrix1" and head["name"] in {"literal", "column_literal"}:
            is_matrix = head["name"] == "literal"
            args = [node(child) for child in list(element)[1:]]
            result = {
                "kind": "matrix_literal" if is_matrix else "column_literal",
                "operator": head,
                "carrier": args[0],
                "rows": args[1],
                "entries": args[3:] if is_matrix else args[2:],
            }
            if is_matrix:
                result["columns"] = args[2]
            return result
        signature = next(v for v in mapping[tuple(head.values())] if v != "atom")
        result = {"kind": _KINDS[signature], "operator": head}
        args = [node(child) for child in list(element)[1:]]
        if signature in _FIELDS:
            assert len(args) == len(_FIELDS[signature])
            result.update(zip(_FIELDS[signature], args, strict=True))
        else:
            result["arguments"] = args
        return result

    root = ET.fromstring(xml)
    return {"version": root.attrib["version"], "body": node(root[0])}


def ast_json(xml, profile=PROFILE):
    return json.dumps(ast_from_xml(xml, profile))


def document(body=None):
    return {
        "version": "2.0",
        "body": body if body is not None else {"kind": "integer", "value": "-7"},
    }


def operator(cd="matrix1", name="transpose", base="urn:pals:openmath:typed-math:v1"):
    return dict(cdbase=base, cd=cd, name=name)


def decode(value, profile=PROFILE):
    return to_openmath_xml(json.dumps(value), profile)


@pytest.mark.parametrize("profile", sorted(set(_GUIDANCE) | set(PROFILES)))
def test_all_sixteen_profiles_roundtrip_through_real_validators_without_semantic_changes(profile):
    if profile in PROFILES:
        xml = symbolic_formula(profile)
    else:
        g, doc, _ = example(profile)
        xml = g.document(doc)
    spec, _ = profile_contract(profile)
    canonical = spec.canonicalize(xml)
    restored = to_openmath_xml(ast_json(canonical, profile), profile)
    assert spec.validate_canonical(spec.canonicalize(restored)) == canonical


def test_serializer_escapes_instead_of_interpreting_text_and_attributes():
    root = ET.fromstring(decode(document({"kind": "variable", "name": 'x"<&>'})))
    assert root[0].get("name") == 'x"<&>'
    assert len(list(root.iter())) == 2
    assert ">-7<" in decode(document())


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(extra=1),
        lambda d: d.update(version=True),
        lambda d: d["body"].update(tail="text"),
        lambda d: d["body"].update(kind="foreign"),
        lambda d: d["body"].update(value=True),
        lambda d: d["body"].update(children=[]),
    ],
)
def test_unknown_fields_wrong_types_fail_closed(change):
    value = document()
    change(value)
    with pytest.raises(TypedOpenMathASTError):
        decode(value)


@pytest.mark.parametrize(
    "raw",
    [
        "<OMOBJ/>",
        "{}",
        '{"version":"2.0","version":"2.0","body":null}',
        '{"body":NaN}',
        '{"root":null}',
        '{"body":Infinity}',
    ],
)
def test_no_xml_or_v1_fallback_duplicate_json_nonjson_constants(raw):
    with pytest.raises(TypedOpenMathASTError):
        to_openmath_xml(raw, PROFILE)


@pytest.mark.parametrize("text", ["\x00", "\x01", "\ud800", "\ufffe"])
def test_invalid_xml_unicode_is_rejected(text):
    with pytest.raises(TypedOpenMathASTError):
        decode(document({"kind": "integer", "value": text}))


def test_bytes_nodes_depth_and_strings_are_bounded():
    deep = {"kind": "variable", "name": "A"}
    for _ in range(65):
        deep = {"kind": "unary", "operator": operator(), "argument": deep}
    many = {
        "kind": "variadic2",
        "operator": operator("logic1", "and", "http://www.openmath.org/cd"),
        "arguments": [{"kind": "integer", "value": "1"}] * 4097,
    }
    for raw in (
        " " * 262145,
        json.dumps(document(deep)),
        json.dumps(document(many)),
        json.dumps(document({"kind": "integer", "value": "x" * 20001})),
        "[" * 1200 + "]" * 1200,
    ):
        with pytest.raises(TypedOpenMathASTError):
            to_openmath_xml(raw, PROFILE)


def test_transport_does_not_make_wrong_math_valid():
    # Well-shaped equality still compares incompatible mathematical sorts.
    body = {
        "kind": "relation",
        "operator": operator("relation1", "eq", "http://www.openmath.org/cd"),
        "lhs": {"kind": "integer", "value": "1"},
        "rhs": {"kind": "variable", "name": "K"},
    }
    declaration = {
        "name": "K",
        "type_key": operator("typed1", "type"),
        "sort": {"kind": "symbol", "operator": operator("algebra1", "Field")},
    }
    xml = decode(
        document(
            {
                "kind": "binder",
                "operator": operator("typed1", "forall"),
                "declarations": [declaration],
                "body": body,
            }
        )
    )
    spec, _ = profile_contract(PROFILE)
    with pytest.raises(ValueError):
        spec.canonicalize(xml)


@pytest.mark.parametrize("profile", sorted(_GROUPS))
def test_every_registry_symbol_classified_and_fixed_arity_cannot_escape(profile):
    mapping = signatures(profile)
    schema = response_schema(profile)
    variants = schema["$defs"]["expression"]["anyOf"]

    def allowed_symbols(operator_schema):
        variants = operator_schema.get("anyOf", [operator_schema])
        return {
            (p["cdbase"]["enum"][0], p["cd"]["enum"][0], name)
            for variant in variants
            for p in [variant["properties"]]
            for name in p["name"]["enum"]
        }

    for symbol, kinds in mapping.items():
        assert len(kinds) == 1 or (
            symbol == ("http://www.openmath.org/cd", "nums1", "i") and kinds == {"atom", "0"}
        )
        for signature in kinds:
            if symbol in sort_signatures(profile):
                continue
            if signature not in _FIELDS:
                continue
            kind = _KINDS[signature]
            matching = (
                [
                    v
                    for v in variants
                    if "operator" in v["properties"]
                    and symbol in allowed_symbols(v["properties"]["operator"])
                ]
                if signature != "type"
                else []
            )
            assert {v["properties"]["kind"]["enum"][0] for v in matching} == (
                {_KINDS[s] for s in kinds}
            )
            variant = next(v for v in matching if v["properties"]["kind"]["enum"] == [kind])
            assert set(variant["required"]) == {"kind", "operator", *_FIELDS[signature]}
            assert variant["additionalProperties"] is False
            valid = {
                "kind": kind,
                "operator": dict(zip(("cdbase", "cd", "name"), symbol, strict=True)),
                **{field: {"kind": "integer", "value": "1"} for field in _FIELDS[signature]},
            }
            # Test serialization shape only. Full validators still own types/contexts.
            xml = ET.fromstring(decode(document(valid), profile))
            assert len(xml[0]) == len(_FIELDS[signature]) + 1
            for field in _FIELDS[signature]:
                missing = deepcopy(valid)
                del missing[field]
                with pytest.raises(TypedOpenMathASTError):
                    decode(document(missing), profile)
            wrong = deepcopy(valid)
            wrong["extra_argument"] = {"kind": "integer", "value": "1"}
            with pytest.raises(TypedOpenMathASTError):
                decode(document(wrong), profile)
            for escape in ("variadic2", "variadic3"):
                wrong = {
                    "kind": escape,
                    "operator": valid["operator"],
                    "arguments": [{"kind": "integer", "value": "1"}] * 3,
                }
                with pytest.raises(TypedOpenMathASTError):
                    decode(document(wrong), profile)
            if signature != "0":
                with pytest.raises(TypedOpenMathASTError):
                    decode(document({"kind": "symbol", "operator": valid["operator"]}), profile)


def test_observed_transpose_two_arguments_and_eq_one_argument_unrepresentable():
    # Exact observed structural defect, with symbolic operands instead of catalog answers.
    unary = {
        "kind": "unary",
        "operator": operator(),
        "argument": {"kind": "variable", "name": "A"},
        "rhs": {"kind": "variable", "name": "B"},
    }
    eq = {
        "kind": "relation",
        "operator": operator("relation1", "eq", "http://www.openmath.org/cd"),
        "lhs": unary,
    }
    with pytest.raises(TypedOpenMathASTError):
        decode(document(eq))
    with pytest.raises(TypedOpenMathASTError):
        decode(document(unary))
    for kind in ("binary", "variadic2", "symbol"):
        value = {"kind": kind, "operator": operator()}
        if kind == "binary":
            value.update(
                left={"kind": "variable", "name": "A"}, right={"kind": "variable", "name": "B"}
            )
        if kind == "variadic2":
            value["arguments"] = [
                {"kind": "variable", "name": "A"},
                {"kind": "variable", "name": "B"},
            ]
        with pytest.raises(TypedOpenMathASTError):
            decode(document(value))


def test_schema_closed_and_profile_bound_no_unknown_profile_fallback():
    schema = response_schema(PROFILE)
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["expression"]["anyOf"]
    for variant in schema["$defs"]["expression"]["anyOf"]:
        assert variant["additionalProperties"] is False
        assert set(variant["required"]) == set(variant["properties"])
    with pytest.raises(ValueError):
        response_schema("unknown")


def test_duplicate_operator_member_foreign_cdbase_and_annotation_escape_are_rejected():
    raw = (
        '{"version":"2.0","body":{"kind":"symbol","operator":'
        '{"cdbase":"urn:pals:openmath:typed-math:v1","cd":"algebra1",'
        '"name":"Field","name":"Field"}}}'
    )
    with pytest.raises(TypedOpenMathASTError):
        to_openmath_xml(raw, PROFILE)
    for symbol in (operator("typed1", "type"), operator("matrix1", "transpose", "foreign")):
        with pytest.raises(TypedOpenMathASTError):
            decode(document({"kind": "symbol", "operator": symbol}))


def test_generic_variadic_literal_escape_is_rejected():
    for kind, name in (("variadic3", "literal"), ("variadic2", "column_literal")):
        with pytest.raises(TypedOpenMathASTError, match="Literal requires"):
            decode(
                document(
                    {
                        "kind": kind,
                        "operator": operator("matrix1", name),
                        "arguments": [{"kind": "integer", "value": "1"}] * 4,
                    }
                )
            )


def wrap_sort(sort, profile):
    mapping = signatures(profile)
    binder = next(s for s, kinds in mapping.items() if "binder" in kinds and s[2] == "forall")
    type_key = next(s for s, kinds in mapping.items() if "type" in kinds)

    def as_dict(value):
        return dict(zip(("cdbase", "cd", "name"), value, strict=True))

    return document(
        {
            "kind": "binder",
            "operator": as_dict(binder),
            "declarations": [{"name": "x", "type_key": as_dict(type_key), "sort": sort}],
            "body": {"kind": "variable", "name": "x"},
        }
    )


def sort_expression(symbol, pattern):
    signature = str(len(pattern)) if pattern else "atom"
    result = {
        "kind": _KINDS[signature],
        "operator": dict(zip(("cdbase", "cd", "name"), symbol, strict=True)),
    }
    for field, slot in zip(_FIELDS.get(signature, ()), pattern, strict=True):
        result[field] = (
            {"kind": "variable", "name": "K"} if slot == "v" else {"kind": "integer", "value": "2"}
        )
    return result


@pytest.mark.parametrize("profile", sorted(_GROUPS))
def test_all_sort_constructors_only_allowed_in_annotation_context(profile):
    mapping = sort_signatures(profile)
    schema = response_schema(profile)
    if profile == "typed-geometry-complex-v1":
        assert not mapping and "sort" not in schema["$defs"]
        assert set(schema["$defs"]["declaration"]["properties"]) == {"name"}
        return
    assert schema["$defs"]["declaration"]["properties"]["sort"] == {"$ref": "#/$defs/sort"}
    for symbol, pattern in mapping.items():
        expr = sort_expression(symbol, pattern)
        xml = ET.fromstring(decode(wrap_sort(expr, profile), profile))
        actual_sort = xml[0][1][0][0][1]
        assert actual_sort.tag.split("}")[-1] == ("OMA" if pattern else "OMS")
        assert len(actual_sort) == (1 + len(pattern) if pattern else 0)
        with pytest.raises(TypedOpenMathASTError, match="context"):
            decode(document(expr), profile)
        for escape in ("symbol", "variadic2", "variadic3"):
            bad = {"kind": escape, "operator": expr["operator"]}
            if escape.startswith("variadic"):
                bad["arguments"] = [{"kind": "variable", "name": "K"}] * 3
            with pytest.raises(TypedOpenMathASTError):
                decode(document(bad), profile)
        for field, slot in zip(_FIELDS.get(str(len(pattern)), ()), pattern, strict=True):
            for replacement in (
                {"kind": "integer", "value": "2"}
                if slot == "v"
                else {"kind": "variable", "name": "n"},
                {"kind": "symbol", "operator": expr["operator"]},
            ):
                bad = deepcopy(expr)
                bad[field] = replacement
                with pytest.raises(TypedOpenMathASTError):
                    decode(wrap_sort(bad, profile), profile)
        for field in _FIELDS.get(str(len(pattern)), ()):
            missing = deepcopy(expr)
            del missing[field]
            with pytest.raises(TypedOpenMathASTError):
                decode(wrap_sort(missing, profile), profile)
        bad = deepcopy(expr)
        bad["extra_argument"] = {"kind": "variable", "name": "K"}
        with pytest.raises(TypedOpenMathASTError):
            decode(wrap_sort(bad, profile), profile)


def test_observed_matrix_type_as_transpose_operand_fails_before_full_validator():
    matrix_sort = sort_expression(("urn:pals:openmath:typed-math:v1", "matrix1", "Matrix"), "vii")
    term = {"kind": "unary", "operator": operator(), "argument": matrix_sort}
    equality = {
        "kind": "relation",
        "operator": operator("relation1", "eq", "http://www.openmath.org/cd"),
        "lhs": term,
        "rhs": deepcopy(matrix_sort),
    }
    with pytest.raises(TypedOpenMathASTError, match="context"):
        decode(document(equality))
    # The exact same constructor remains available as a declaration annotation.
    assert "<OMA>" in decode(wrap_sort(matrix_sort, PROFILE))


@pytest.mark.parametrize("dimension", ["0", "9", "-1", "2.0", "02"])
def test_matrix_sort_dimensions_are_exact_direct_omi_one_to_eight(dimension):
    sort = sort_expression(("urn:pals:openmath:typed-math:v1", "matrix1", "Matrix"), "vii")
    sort["argument2"]["value"] = dimension
    with pytest.raises(TypedOpenMathASTError, match="dimension"):
        decode(wrap_sort(sort, PROFILE))


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "variable", "name": "K"},
        {"kind": "integer", "value": "2"},
        {"kind": "unary", "operator": operator(), "argument": {"kind": "variable", "name": "A"}},
    ],
)
def test_values_cannot_be_used_as_whole_sort_annotations(value):
    with pytest.raises(TypedOpenMathASTError):
        decode(wrap_sort(value, PROFILE))


def test_geometry_i_is_term_only_and_no_annotation_is_added():
    profile = "typed-geometry-complex-v1"
    i = {"kind": "symbol", "operator": operator("nums1", "i", "http://www.openmath.org/cd")}
    assert 'name="i"' in decode(document(i), profile)
    assert not sort_signatures(profile)
    g, doc, _ = example(profile)
    value = ast_from_xml(g.document(doc), profile)
    declaration = value["body"]["declarations"][0]
    declaration["sort"] = i
    with pytest.raises(TypedOpenMathASTError):
        decode(value, profile)


def test_every_sort_symbol_is_absent_from_expression_schema_operator_enums():
    def operators(node):
        result = set()
        for variant in node.get("anyOf", [node]):
            props = variant["properties"]
            if "operator" not in props:
                continue
            for symbol in props["operator"].get("anyOf", [props["operator"]]):
                p = symbol["properties"]
                result.update(
                    (p["cdbase"]["enum"][0], p["cd"]["enum"][0], name) for name in p["name"]["enum"]
                )
        return result

    count = 0
    for profile in _GROUPS:
        sorts = sort_signatures(profile)
        defs = response_schema(profile)["$defs"]
        assert not (set(sorts) & operators(defs["expression"]))
        if sorts:
            assert set(sorts) == operators(defs["sort"])
        count += len(sorts)
    assert count == 58


def matrix_literal_ast(rows, columns=None):
    count = rows * columns if columns is not None else rows
    # Non-corpus values expose dropped/reordered entries for every legal shape.
    entries = [
        {
            "kind": "binary",
            "operator": operator("matrix1", "field_nat_cast"),
            "left": {"kind": "variable", "name": "K"},
            "right": {"kind": "integer", "value": str(17 + i)},
        }
        for i in range(count)
    ]
    result = {
        "kind": "matrix_literal" if columns is not None else "column_literal",
        "operator": operator("matrix1", "literal" if columns is not None else "column_literal"),
        "carrier": {"kind": "variable", "name": "K"},
        "rows": {"kind": "integer", "value": str(rows)},
        "entries": entries,
    }
    if columns is not None:
        result["columns"] = {"kind": "integer", "value": str(columns)}
    return result


def literal_proposition(value):
    return document(
        {
            "kind": "binder",
            "operator": operator("typed1", "forall"),
            "declarations": [
                {
                    "name": "K",
                    "type_key": operator("typed1", "type"),
                    "sort": {"kind": "symbol", "operator": operator("algebra1", "Field")},
                }
            ],
            "body": {
                "kind": "relation",
                "operator": operator("relation1", "eq", "http://www.openmath.org/cd"),
                "lhs": value,
                "rhs": deepcopy(value),
            },
        }
    )


@pytest.mark.parametrize("rows", range(1, 9))
@pytest.mark.parametrize("columns", [None, *range(1, 9)])
def test_explicit_literal_all_legal_shapes_preserve_every_entry(rows, columns):
    value = matrix_literal_ast(rows, columns)
    xml = decode(literal_proposition(value))
    spec, _ = profile_contract(PROFILE)
    canonical = spec.validate_canonical(spec.canonicalize(xml))
    assert spec.canonicalize(decode(ast_from_xml(canonical))) == canonical
    node = ET.fromstring(xml)[0][2][1]
    offset = 4 if columns is not None else 3
    assert [int(entry[2].text) for entry in list(node)[offset:]] == [
        17 + i for i in range(rows * (columns or 1))
    ]


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x["entries"].pop(),
        lambda x: x["entries"].append(deepcopy(x["entries"][0])),
        lambda x: x.update(rows={"kind": "integer", "value": "0"}),
        lambda x: x.update(columns={"kind": "integer", "value": "9"}),
        lambda x: x.update(carrier={"kind": "integer", "value": "1"}),
        lambda x: x.update(operator=operator("matrix1", "zero")),
        lambda x: x.update(arguments=[]),
    ],
)
def test_explicit_literal_rejects_missing_slots_shape_mismatch_and_operator_swap(change):
    value = matrix_literal_ast(3, 1)
    change(value)
    with pytest.raises(TypedOpenMathASTError):
        decode(literal_proposition(value))


def test_literal_schema_has_named_required_slots_without_variadic_escape():
    def allowed_symbols(value):
        if "anyOf" in value:
            return set().union(*(allowed_symbols(branch) for branch in value["anyOf"]))
        props = value["properties"]
        return {
            (base, cd, name)
            for base in props["cdbase"]["enum"]
            for cd in props["cd"]["enum"]
            for name in props["name"]["enum"]
        }

    variants = response_schema(PROFILE)["$defs"]["expression"]["anyOf"]
    for kind, fields, name in [
        ("matrix_literal", {"columns"}, "literal"),
        ("column_literal", set(), "column_literal"),
    ]:
        matches = [
            v
            for v in variants
            if "operator" in v["properties"]
            and tuple(operator("matrix1", name).values())
            in allowed_symbols(v["properties"]["operator"])
        ]
        assert len(matches) == 1
        variant = matches[0]
        assert variant["properties"]["kind"]["enum"] == [kind]
        assert (
            set(variant["required"]) == {"kind", "operator", "carrier", "rows", "entries"} | fields
        )
        assert variant["additionalProperties"] is False


def test_literal_does_not_silently_cast_entry_or_change_false_equation():
    value = matrix_literal_ast(1, 3)
    doc = literal_proposition(value)
    doc["body"]["body"]["rhs"]["entries"][1]["right"]["value"] = "99"
    spec, _ = profile_contract(PROFILE)
    canonical = spec.validate_canonical(spec.canonicalize(decode(doc)))
    assert ast_from_xml(canonical)["body"]["body"]["rhs"]["entries"][1]["right"]["value"] == "99"
    value["entries"][0] = {"kind": "integer", "value": "17"}
    with pytest.raises(ValueError):
        spec.canonicalize(decode(literal_proposition(value)))


def test_literal_preserves_symbolic_entries_and_explicit_zero_still_has_its_own_operator():
    value = matrix_literal_ast(2, 1)
    value["entries"] = [{"kind": "variable", "name": "x"}] * 2
    doc = literal_proposition(value)
    doc["body"]["declarations"].append(
        {
            "name": "x",
            "type_key": operator("typed1", "type"),
            "sort": {
                "kind": "unary",
                "operator": operator("typed1", "Elem"),
                "argument": {"kind": "variable", "name": "K"},
            },
        }
    )
    spec, _ = profile_contract(PROFILE)
    canonical = spec.validate_canonical(spec.canonicalize(decode(doc)))
    assert ast_from_xml(canonical)["body"]["body"]["lhs"]["entries"][0]["kind"] == "variable"
    zero = {
        "kind": "application3",
        "operator": operator("matrix1", "zero"),
        "argument1": {"kind": "variable", "name": "K"},
        "argument2": {"kind": "integer", "value": "2"},
        "argument3": {"kind": "integer", "value": "1"},
    }
    canonical_zero = spec.validate_canonical(spec.canonicalize(decode(literal_proposition(zero))))
    assert 'name="zero"' in canonical_zero
    assert 'name="literal"' not in canonical_zero


def test_v4_observed_zero_entry_is_rejected_before_xml_validation():
    # Exact first entry from v4 first-observations.json's preserved private JSON.
    # Both attempts used this Matrix(K,1,1) where Elem(K) was required.
    observed_entry = {
        "kind": "application3",
        "operator": {"cdbase": "urn:pals:openmath:typed-math:v1", "cd": "matrix1", "name": "zero"},
        "argument1": {"kind": "variable", "name": "K"},
        "argument2": {"kind": "integer", "value": "1"},
        "argument3": {"kind": "integer", "value": "1"},
    }
    value = matrix_literal_ast(1, 1)
    value["entries"] = [observed_entry]
    with pytest.raises(TypedOpenMathASTError, match="scalar expression"):
        decode(literal_proposition(value))


@pytest.mark.parametrize("column", [False, True])
def test_scalar_entry_accepts_determinant_and_preserves_its_matrix_operand(column):
    value = matrix_literal_ast(1, None if column else 1)
    argument = matrix_literal_ast(3, 3)
    value["entries"] = [
        {"kind": "unary", "operator": operator("matrix1", "determinant"), "argument": argument}
    ]
    spec, _ = profile_contract(PROFILE)
    canonical = spec.validate_canonical(spec.canonicalize(decode(literal_proposition(value))))
    restored = ast_from_xml(canonical)
    determinant = restored["body"]["body"]["lhs"]["entries"][0]
    assert determinant["operator"]["name"] == "determinant"
    assert [e["right"]["value"] for e in determinant["argument"]["entries"]] == [
        str(17 + i) for i in range(9)
    ]


@pytest.mark.parametrize(
    "entry",
    [
        {"kind": "integer", "value": "7"},
        {
            "kind": "unary",
            "operator": operator("matrix1", "rank"),
            "argument": {"kind": "variable", "name": "A"},
        },
        {
            "kind": "unary",
            "operator": operator("matrix1", "neg"),
            "argument": {"kind": "variable", "name": "A"},
        },
        {
            "kind": "binary",
            "operator": operator("matrix1", "field_nat_cast"),
            "left": {"kind": "variable", "name": "K"},
            "right": {
                "kind": "unary",
                "operator": operator("matrix1", "rank"),
                "argument": {"kind": "variable", "name": "A"},
            },
        },
    ],
)
def test_scalar_entry_rejects_matrix_operations_bare_integer_and_nondirect_cast(entry):
    value = matrix_literal_ast(1, 1)
    value["entries"] = [entry]
    with pytest.raises(TypedOpenMathASTError):
        decode(literal_proposition(value))


def test_scalar_entry_fullvalidator_still_rejects_wrong_carrier_or_nonsquare_determinant():
    value = matrix_literal_ast(1, 1)
    value["entries"] = [
        {
            "kind": "unary",
            "operator": operator("matrix1", "determinant"),
            "argument": matrix_literal_ast(2, 3),
        }
    ]
    spec, _ = profile_contract(PROFILE)
    with pytest.raises(ValueError, match="square"):
        spec.canonicalize(decode(literal_proposition(value)))
    value = matrix_literal_ast(1, 1)
    value["entries"][0]["left"]["name"] = "L"
    doc = literal_proposition(value)
    doc["body"]["declarations"].insert(
        0,
        {
            "name": "L",
            "type_key": operator("typed1", "type"),
            "sort": {"kind": "symbol", "operator": operator("algebra1", "Field")},
        },
    )
    with pytest.raises(ValueError, match="Elem"):
        spec.canonicalize(decode(doc))


def test_scalar_schema_closes_entry_types_without_narrowing_other_profiles():
    schema = response_schema(PROFILE)
    allowed = schema["$defs"]["matrix_scalar"]["anyOf"]
    assert {v["properties"]["kind"]["enum"][0] for v in allowed} == {"variable", "binary", "unary"}
    names = {
        v["properties"]["operator"]["properties"]["name"]["enum"][0]
        for v in allowed
        if "operator" in v["properties"]
    }
    assert names == {"field_nat_cast", "determinant"}
    for variant in schema["$defs"]["expression"]["anyOf"]:
        if variant["properties"]["kind"]["enum"][0] in {"matrix_literal", "column_literal"}:
            assert variant["properties"]["entries"]["items"] == {"$ref": "#/$defs/matrix_scalar"}
    for profile in _GROUPS:
        if profile != PROFILE:
            assert "matrix_scalar" not in response_schema(profile)["$defs"]
