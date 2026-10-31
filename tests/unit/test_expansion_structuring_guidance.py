"""Observed expansion AST regressions; no provider/DB/compiler evidence."""

import hashlib
import json
import re
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from pals_agent import typed_expansion_runtime as expansion
from pals_agent import typed_linear_algebra_v2 as linear
from pals_agent.openmath import MathXMLValidationError
from pals_agent.private_typed_candidates import TypedCandidateResult
from pals_agent.typed_openmath_ast import TypedOpenMathASTError, to_openmath_xml
from pals_agent.typed_profile_guidance import profile_guidance
from pals_agent.typed_runtime import TypedProofFlowRuntime

PROFILE = "typed-linear-algebra-v2"


def operator(name, cd="la2"):
    return {
        "cdbase": linear.STANDARD if cd in {"arith1", "relation1"} else linear.CDBASE,
        "cd": cd,
        "name": name,
    }


def symbol(name):
    return {"kind": "symbol", "operator": operator(name)}


def variable(name):
    return {"kind": "variable", "name": name}


def apply(name, *arguments, cd="la2"):
    return {"kind": "application", "operator": operator(name, cd), "arguments": list(arguments)}


def rank_nullity():
    """The actual failure's target, expressed with explicit dependent carriers."""
    k, v, w, f = map(variable, ("K", "V", "W", "f"))
    declarations = [
        ("K", symbol("Field")),
        ("V", apply("FiniteDimensionalSpace", k)),
        ("W", apply("FiniteDimensionalSpace", k)),
        ("f", apply("LinearMap", k, v, w)),
    ]
    return {
        "version": "2.0",
        "body": {
            "kind": "binder",
            "operator": operator("forall", "typed1"),
            "declarations": [
                {"name": name, "type_key": operator("type", "typed1"), "sort": sort}
                for name, sort in declarations
            ],
            "body": apply(
                "eq",
                apply(
                    "plus",
                    apply("sub_dim", k, w, apply("range", k, v, w, f)),
                    apply("sub_dim", k, v, apply("kernel", k, v, w, f)),
                    cd="arith1",
                ),
                apply("dim", k, v),
                cd="relation1",
            ),
        },
    }


def test_full_rank_target_passes_original_validator_without_coercion():
    ast = rank_nullity()
    xml = to_openmath_xml(json.dumps(ast), PROFILE)
    assert linear.validate_canonical_typed_linear_algebra_v2_openmath_xml(xml) == xml
    assert expansion.to_openmath_xml(json.dumps(ast), PROFILE) == xml
    # Exact canonical target used by the independently frozen real positive corpus.
    assert hashlib.sha256(xml.encode()).hexdigest() == (
        "dc56cda03a9786316a8cbf1ccf9185a66a4bb82c3107362f7d821884a123ecf0"
    )
    assert (
        expansion.from_openmath_xml(xml, PROFILE)["body"]["declarations"][0]["sort"]["kind"]
        == "symbol"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "field_application",
        "range_arity",
        "kernel_arity",
        "subspace_as_space",
        "wrong_ambient",
        "scope",
        "carrier",
    ],
)
def test_real_failure_and_carrier_scope_variants_remain_rejected(mutation):
    ast = rank_nullity()
    body = ast["body"]["body"]
    image_dim, kernel_dim = body["arguments"][0]["arguments"]
    if mutation == "field_application":
        ast["body"]["declarations"][0]["sort"] = apply("Field")
    elif mutation == "range_arity":
        image_dim["arguments"][2] = apply("range", variable("f"))
    elif mutation == "kernel_arity":
        kernel_dim["arguments"][2] = apply("kernel", variable("f"))
    elif mutation == "subspace_as_space":
        body["arguments"][0]["arguments"][0] = apply(
            "dim", variable("K"), image_dim["arguments"][2]
        )
    elif mutation == "wrong_ambient":
        image_dim["arguments"][1] = variable("V")
    elif mutation == "scope":
        ast["body"]["declarations"].reverse()
    else:
        ast["body"]["declarations"][1]["sort"]["arguments"][0] = variable("missing_K")
    with pytest.raises(TypedOpenMathASTError, match="selected-profile validation failed"):
        to_openmath_xml(json.dumps(ast), PROFILE)


def test_wrong_but_well_typed_target_is_never_replaced_by_the_right_one():
    ast = rank_nullity()
    original = to_openmath_xml(json.dumps(ast), PROFILE)
    ast["body"]["body"]["arguments"][1] = apply("dim", variable("K"), variable("W"))
    changed = to_openmath_xml(json.dumps(ast), PROFILE)
    assert changed != original
    assert expansion.to_openmath_xml(json.dumps(ast), PROFILE) == changed


def test_bound_names_normalize_but_domains_and_argument_positions_do_not():
    ast = rank_nullity()
    renamed = json.dumps(ast)
    for before, after in [("K", "F"), ("V", "A"), ("W", "B"), ("f", "g")]:
        renamed = renamed.replace('"' + before + '"', '"' + after + '"')
    assert to_openmath_xml(renamed, PROFILE) == to_openmath_xml(json.dumps(ast), PROFILE)


@pytest.mark.parametrize("profile", sorted(expansion.EXPANSION_PROFILES))
def test_all_expansion_prompts_distinguish_atomic_sorts_and_dependent_applications(profile):
    guidance = profile_guidance(profile)
    assert "Atomic sorts are kind=symbol" in guidance
    assert "never as a generic spelling of a sort" in guidance
    assert "signature order" in guidance and "Bind carriers before" in guidance


def test_linear_signature_guidance_covers_every_existing_value_operator_arity():
    guidance = profile_guidance(PROFILE)
    signatures = re.findall(r"\b([a-z_]+)\(([^()]*)\)", guidance)
    arities = {(name, len(args.split(","))) for name, args in signatures}
    assert set(linear._LA_ARITIES.items()) <= arities
    for sort in linear._TYPE_NAMES:
        assert sort in guidance
    assert "kernel(K,V,W,f)" in guidance
    assert "range(K,V,W,f)" in guidance
    assert "sub_dim(K,W,range(K,V,W,f))" in guidance


def test_profile_error_is_specific_bounded_and_generic_errors_stay_closed(monkeypatch):
    invalid = rank_nullity()
    invalid["body"]["declarations"][0]["sort"] = apply("Field")
    with pytest.raises(TypedOpenMathASTError, match="OMA must contain at least 2 child"):
        to_openmath_xml(json.dumps(invalid), PROFILE)

    def local_error(*args):
        raise MathXMLValidationError("local-validator-" + "界" * 1000)

    monkeypatch.setattr(expansion, "to_openmath_xml", local_error)
    with pytest.raises(TypedOpenMathASTError) as caught:
        to_openmath_xml("unused", PROFILE)
    assert len(str(caught.value).encode()) <= 432

    def other_error(*args):
        raise ValueError("provider-exception-prose-must-stay-private")

    monkeypatch.setattr(expansion, "to_openmath_xml", other_error)
    with pytest.raises(TypedOpenMathASTError) as caught:
        to_openmath_xml("unused", PROFILE)
    assert "provider-exception-prose" not in str(caught.value)


def test_existing_one_repair_receives_local_error_and_retains_original_target():
    valid = rank_nullity()
    invalid = deepcopy(valid)
    invalid["body"]["declarations"][0]["sort"] = apply("Field")
    model = Mock()
    model.generate.side_effect = [json.dumps(invalid), json.dumps(valid)]
    embeddings = SimpleNamespace(
        model="text-embedding-3-small",
        dimension=384,
        revision="openai-release-2024-01-25",
        endpoint_identity="https://api.openai.com/v1",
        deployment_identity="text-embedding-3-small",
        embed=Mock(return_value=[1.0] * 384),
    )
    candidates, reranker = Mock(), Mock()
    candidates.find_candidates.return_value = TypedCandidateResult(
        str(uuid4()), "a" * 64, PROFILE, 1, ()
    )
    reranker.rerank.return_value = ()
    runtime = TypedProofFlowRuntime(model, embeddings, candidates, reranker)
    statement = "For a finite-dimensional K-linear map, prove the rank-nullity theorem."
    result = runtime.retrieve_for_profile(PROFILE, statement)
    assert model.generate.call_count == 2
    repair_prompt = model.generate.call_args.kwargs["prompt"]
    assert "OMA must contain at least 2 child" in repair_prompt
    assert statement in repair_prompt and "sub_dim(K,W,range(K,V,W,f))" in repair_prompt
    assert result.query_openmath == to_openmath_xml(json.dumps(valid), PROFILE)
    assert result.private_diagnostics["structuring_attempts"] == 2
    assert result.private_diagnostics["structuring_repair_used"] is True
    embeddings.embed.assert_called_once()
    candidates.find_candidates.assert_called_once()
