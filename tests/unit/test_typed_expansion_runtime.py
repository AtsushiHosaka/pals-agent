"""Real canonical source fixtures, no provider/compiler/publication evidence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from pals_agent.private_typed_candidates import profile_contract
from pals_agent.profile_routing import SUPPORTED_TYPED_PROFILES
from pals_agent.typed_expansion_runtime import (
    EXPANSION_PROFILES,
    from_openmath_xml,
    runtime_profile_specs,
)
from pals_agent.typed_openmath_ast import TypedOpenMathASTError, response_schema, to_openmath_xml
from pals_agent.typed_profile_guidance import profile_guidance
from pals_agent.typed_release import profile_bindings

FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures/typed_expansion_runtime_cards.json").read_text()
)


@pytest.mark.parametrize("profile", sorted(EXPANSION_PROFILES))
def test_real_profile_source_roundtrip_and_publication_binding(profile):
    source = FIXTURES[profile]["openmath_xml"]
    spec, binding = profile_contract(profile)
    ast = from_openmath_xml(source, profile)
    assert to_openmath_xml(json.dumps(ast), profile) == source
    assert spec.validate_canonical(source) == source
    assert profile in SUPPORTED_TYPED_PROFILES
    assert profile_guidance(profile)
    assert response_schema(profile)["additionalProperties"] is False
    assert binding == profile_bindings(Path(__file__).resolve().parents[3])[profile]


def test_all_thirty_profiles_have_one_explicit_contract():
    assert len(runtime_profile_specs()) == len(SUPPORTED_TYPED_PROFILES) == 30
    assert set(FIXTURES) == EXPANSION_PROFILES
    with pytest.raises(ValueError):
        from_openmath_xml("<OMOBJ/>", "typed-calculus-v999")


def first_ast(profile="typed-linear-algebra-v2"):
    return from_openmath_xml(FIXTURES[profile]["openmath_xml"], profile)


@pytest.mark.parametrize(
    "change",
    ["extra", "foreign_symbol", "free_variable", "dependent_carrier", "arity", "binder_scope"],
)
def test_original_validator_still_rejects_invalid_type_scope_and_arity(change):
    ast = first_ast()
    if change == "extra":
        ast["evidence_valid"] = True
    elif change == "foreign_symbol":
        ast["body"]["operator"]["cdbase"] = "urn:foreign"
    elif change == "free_variable":
        ast["body"]["body"] = {"kind": "variable", "name": "unbound"}
    elif change == "dependent_carrier":
        ast["body"]["declarations"][1]["sort"]["arguments"][0]["name"] = "unbound_carrier"
    elif change == "arity":
        ast["body"]["declarations"][1]["sort"]["arguments"].append(
            {"kind": "integer", "value": "1"}
        )
    elif change == "binder_scope":
        ast["body"]["declarations"].reverse()
    with pytest.raises(TypedOpenMathASTError):
        to_openmath_xml(json.dumps(ast), "typed-linear-algebra-v2")


def test_no_silent_premise_deletion_or_quantifier_change():
    ast = first_ast()
    changed = deepcopy(ast)
    changed["body"]["operator"]["name"] = "exists"
    # A well-typed but different theorem remains different, never coerced back.
    assert (
        to_openmath_xml(json.dumps(changed), "typed-linear-algebra-v2")
        != FIXTURES["typed-linear-algebra-v2"]["openmath_xml"]
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"version":"2.0","version":"2.0","body":{}}',
        '{"version":"2.0","body":NaN}',
        '{"version":"2.0","body":null}',
        '"not-an-object"',
    ],
)
def test_closed_duplicate_and_non_json_values_rejected(raw):
    with pytest.raises(TypedOpenMathASTError):
        to_openmath_xml(raw, "typed-calculus-v2")


def test_resource_bounds_are_enforced_before_profile_inference():
    with pytest.raises(TypedOpenMathASTError):
        to_openmath_xml("x" * 262145, "typed-calculus-v2")
    ast = first_ast()
    for _ in range(66):
        ast["body"] = {
            "kind": "application",
            "operator": ast["body"]["operator"],
            "arguments": [ast["body"]],
        }
    with pytest.raises(TypedOpenMathASTError):
        to_openmath_xml(json.dumps(ast), "typed-linear-algebra-v2")


@pytest.mark.parametrize("profile", sorted(EXPANSION_PROFILES))
def test_expansion_schema_defines_operator_once_and_bounds_public_body(profile):
    schema = response_schema(profile)
    operators = schema["$defs"]["operator"]["anyOf"]
    assert len(operators) == len({json.dumps(x, sort_keys=True) for x in operators})
    encoded = json.dumps(schema, sort_keys=True)
    assert len(encoded.encode()) < 65536  # Project offline bound; not provider acceptance.
    assert encoded.count('"$ref": "#/$defs/operator"') == 4
    assert encoded.count('"cdbase":') == len(operators)


def test_future_unreviewed_legacy_profile_is_not_auto_enabled(monkeypatch):
    from dataclasses import replace

    from pals_agent import typed_local_catalog as local

    original = next(v for v in vars(local).values() if isinstance(v, local._ProfileSpec))
    monkeypatch.setattr(
        local, "unreviewed_profile", replace(original, profile_id="typed-future-v1"), raising=False
    )
    with pytest.raises(ValueError, match="Legacy runtime profile population changed"):
        runtime_profile_specs()
