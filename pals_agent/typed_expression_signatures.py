"""Expression-transport signatures transcribed from the sixteen typed validators.

Only serialization shape is described here: sort, carrier, dependent literal size,
allowed contexts and mathematical restrictions remain the full validator's authority.
Each registry member must be explicitly classified; there is no unknown-symbol fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

# Keys are cd:name, resolved to the exact explicit cdbase in each profile registry.
# 0..6 = fixed OMA arity; vN = variadic with minimum N; atom/binder/type are distinct.
_GROUPS: dict[str, dict[str, str]] = {
    "typed-math-matrix-v1": {
        "atom": "algebra1:Field",
        "1": "typed1:Elem matrix1:neg matrix1:transpose matrix1:determinant matrix1:rank",
        "2": (
            "matrix1:ColumnVector matrix1:field_nat_cast matrix1:identity matrix1:add "
            "matrix1:scale matrix1:mul matrix1:is_inverse matrix1:mul_vec"
        ),
        "3": "matrix1:Matrix matrix1:zero",
        "v3": "matrix1:literal",
        "v2": "matrix1:column_literal",
    },
    "typed-math-v1": {
        "atom": "algebra1:Group algebra1:CommRing algebra1:IntegralDomain",
        "1": "typed1:Elem algebra1:one algebra1:ring_zero algebra1:ring_one",
        "2": "typed1:nat_cast algebra1:inv algebra1:ring_neg",
        "3": "algebra1:mul algebra1:ring_add algebra1:ring_mul",
    },
    "typed-real-analysis-v1": {
        "atom": "typed1:Real realanalysis1:RealFunction",
        "binder": "realanalysis1:lambda",
        "1": "realanalysis1:of_int",
        "2": (
            "realanalysis1:of_rat realanalysis1:apply "
            "realanalysis1:epsilon_delta_continuous_at realanalysis1:continuous_at "
            "realanalysis1:differentiable_at"
        ),
        "3": "realanalysis1:has_deriv_at realanalysis1:interval_integrable",
    },
    "typed-multivariable-calculus-v1": {
        "atom": "typed1:Real multicalc1:Real2 multicalc1:Real2Function",
        "binder": "multicalc1:lambda2",
        "1": "multicalc1:of_int multicalc1:fst multicalc1:snd",
        "2": "multicalc1:pair multicalc1:apply multicalc1:differentiable_at",
        "3": "multicalc1:partial_x_at multicalc1:partial_y_at",
    },
    "typed-ode-v1": {
        "atom": "typed1:Real",
        "binder": "ode1:lambda",
        "1": "ode1:of_int transc1:exp transc1:sin transc1:cos",
        "2": "ode1:apply ode1:deriv_at ode1:second_deriv_at",
        "3": "ode1:initial_value",
    },
    "typed-finite-graph-v1": {
        "atom": "pals_typed_graph:FinSimpleGraph",
        "1": (
            "pals_typed_graph:Vertex pals_typed_graph:VertexClass "
            "pals_typed_graph:Trail pals_typed_graph:vertex_count "
            "pals_typed_graph:edge_count pals_typed_graph:degree_sum "
            "pals_typed_graph:odd_degree_count pals_typed_graph:connected "
            "pals_typed_graph:nonisolated_connected pals_typed_graph:acyclic "
            "pals_typed_graph:tree pals_typed_graph:bipartite "
            "pals_typed_graph:has_euler_trail pals_typed_graph:has_euler_circuit"
        ),
        "2": (
            "pals_typed_graph:nat_add pals_typed_graph:nat_mul pals_typed_graph:degree "
            "pals_typed_graph:is_euler_trail pals_typed_graph:is_euler_circuit"
        ),
        "3": "pals_typed_graph:adjacent pals_typed_graph:proper_bipartition",
    },
    "typed-geometry-complex-v1": {
        "atom": "nums1:i",
        "0": "nums1:i",
        "binder": (
            "pals2:forall_real_vector2 pals2:exists_real_vector2 pals2:forall_complex "
            "pals2:exists_complex"
        ),
        "1": (
            "complex1:conjugate complex1:real complex1:imaginary complex1:argument "
            "pals2:complex_norm_sq"
        ),
        "2": (
            "linalg2:vector linalg1:vector_selector linalg1:scalarproduct "
            "complex1:complex_cartesian pals2:vector_add pals2:vector_scale "
            "pals2:determinant2 pals2:complex_add pals2:complex_mul"
        ),
    },
    "typed-plane-geometry-v1": {
        "atom": (
            "pals_plane_geometry:Real pals_plane_geometry:Vector2 "
            "pals_plane_geometry:Point2 pals_plane_geometry:Line2 "
            "pals_plane_geometry:Circle2"
        ),
        "2": (
            "pals_plane_geometry:point2 pals_plane_geometry:vector2 "
            "pals_plane_geometry:vector_add pals_plane_geometry:incident_point_line "
            "pals_plane_geometry:incident_point_circle pals_plane_geometry:parallel "
            "pals_plane_geometry:perpendicular pals_plane_geometry:distance_sq "
            "pals_plane_geometry:midpoint pals_plane_geometry:reflect"
        ),
        "3": "pals_plane_geometry:non_collinear",
    },
    "typed-probability-v1": {
        "atom": (
            "typed1:Nat typed1:Real probability1:SampleSpace probability1:Probability "
            "probability1:DistributionNat"
        ),
        "1": (
            "probability1:Event probability1:ProbabilityMeasure "
            "probability1:RealRandomVariable probability1:nat_to_real "
            "probability1:real_of_int probability1:prob_to_real"
        ),
        "2": (
            "probability1:nat_add probability1:nat_sub probability1:nat_mul "
            "probability1:nat_div probability1:choose probability1:real_sub "
            "probability1:real_div probability1:real_pow_nat "
            "probability1:event_intersection probability1:probability "
            "probability1:constant_rv probability1:expectation "
            "probability1:binomial_distribution probability1:pmf"
        ),
        "v2": "probability1:real_add probability1:real_mul",
    },
    "typed-number-theory-v1": {
        "atom": "numbertheory1:Nat numbertheory1:Int",
        "1": (
            "numbertheory1:nat_literal numbertheory1:int_literal numbertheory1:int_neg "
            "numbertheory1:int_of_nat numbertheory1:is_prime"
        ),
        "2": (
            "numbertheory1:nat_add numbertheory1:nat_mul numbertheory1:int_add "
            "numbertheory1:int_mul numbertheory1:gcd numbertheory1:lcm "
            "numbertheory1:nat_mod numbertheory1:divides_nat numbertheory1:divides_int"
        ),
        "3": "numbertheory1:congruent_nat",
    },
}

_GROUPS.update(
    {
        "typed-commutative-algebra-v1": {
            "atom": "commalg1:CommRing",
            "1": "commalg1:Ideal typed1:Elem commalg1:ideal_bot commalg1:ideal_top",
            "2": "commalg1:ideal_radical commalg1:is_prime_ideal commalg1:is_maximal_ideal",
            "3": "commalg1:ideal_sum commalg1:ideal_inf commalg1:ideal_product commalg1:ideal_le",
        },
        "typed-commutative-algebra-modules-v1": {
            "atom": "module1:CommRing",
            "1": "module1:Module",
            "2": "module1:Submodule module1:submodule_bot module1:submodule_top module1:linear_id",
            "3": "module1:LinearMap module1:linear_zero",
            "4": (
                "module1:submodule_sup module1:submodule_inf module1:submodule_le "
                "module1:linear_kernel module1:linear_range module1:linear_injective "
                "module1:linear_surjective"
            ),
            "6": "module1:linear_comp module1:exact_at",
        },
        "typed-commutative-algebra-localization-v1": {
            "atom": "localization1:CommRing",
            "1": (
                "localization1:Submonoid typed1:Elem commalg1:Ideal "
                "localization1:ring_zero localization1:ring_one commalg1:ideal_top"
            ),
            "2": (
                "localization1:SubmonoidElem localization1:Localization "
                "localization1:is_unit commalg1:ideal_radical commalg1:is_prime_ideal"
            ),
            "3": (
                "localization1:ring_add localization1:ring_mul "
                "localization1:submonoid_value commalg1:ideal_inf commalg1:ideal_sup "
                "commalg1:ideal_le commalg1:ideal_mem commalg1:ideal_disjoint_submonoid"
            ),
            "4": "localization1:loc_map commalg1:extend commalg1:contract",
            "5": "localization1:loc_fraction",
        },
        "typed-commutative-algebra-integral-v1": {
            "atom": "integral1:CommRing integral1:Domain integral1:Field",
            "1": (
                "integral1:Extension integral1:ValuationRing typed1:Elem "
                "integral1:ring_zero integral1:ring_one"
            ),
            "2": (
                "integral1:ring_neg integral1:ring_square "
                "integral1:is_integral_extension integral1:field_inv "
                "integral1:valuation_integrally_closed"
            ),
            "3": (
                "integral1:ring_add integral1:ring_sub integral1:ring_mul "
                "integral1:extension_map integral1:is_integral integral1:valuation_mem"
            ),
        },
        "typed-commutative-algebra-decomposition-v1": {
            "atom": "decomposition1:CommRing",
            "1": (
                "decomposition1:Ideal decomposition1:PrimaryIdeal "
                "decomposition1:PrimeIdeal decomposition1:ideal_top"
            ),
            "2": (
                "decomposition1:primary_as_ideal decomposition1:prime_as_ideal "
                "decomposition1:primary_radical_prime decomposition1:ideal_radical "
                "decomposition1:is_primary_ideal decomposition1:is_prime_ideal "
                "decomposition1:is_radical_ideal"
            ),
            "3": (
                "decomposition1:ideal_inf2 decomposition1:ideal_le "
                "decomposition1:minimal_prime_over"
            ),
            "4": (
                "decomposition1:ideal_inf3 decomposition1:primary_decomposition2 "
                "decomposition1:irredundant_decomposition2"
            ),
            "5": "decomposition1:primary_decomposition3",
        },
        "typed-commutative-algebra-chain-dimension-v1": {
            "atom": "chain1:CommRing",
            "1": (
                "chain1:Ideal chain1:NoetherianRing chain1:ArtinianRing "
                "chain1:KrullDimLEZero chain1:Field chain1:HilbertNoetherian "
                "chain1:IteratedHilbertNoetherian"
            ),
            "2": "chain1:IdealFG chain1:PrimeIdeal chain1:MaximalIdeal chain1:IdealRadical",
            "3": "chain1:IdealSum chain1:IdealInf chain1:IdealProduct",
        },
    }
)

# The standard symbol signatures are shared only where the registry lists them.
_STANDARD = {
    "relation": "relation1:eq relation1:neq relation1:lt relation1:leq relation1:gt relation1:geq",
    "1": "logic1:not arith1:abs arith1:unary_minus",
    "2": "logic1:implies logic1:equivalent arith1:minus arith1:divide arith1:power",
    "v2": "logic1:and logic1:or arith1:plus arith1:times",
}


def signatures(profile_id: str) -> dict[tuple[str, str, str], frozenset[str]]:
    if profile_id not in _GROUPS:
        raise ValueError("Expression profile unsupported")
    registry = json.loads(
        (Path(__file__).parent / "content_dictionaries" / f"{profile_id}-registry.json").read_text()
    )
    groups = {kind: set(names.split()) for kind, names in _GROUPS[profile_id].items()}
    for kind, names in _STANDARD.items():
        groups.setdefault(kind, set()).update(names.split())
    if profile_id in {
        "typed-ode-v1",
        "typed-commutative-algebra-localization-v1",
        "typed-commutative-algebra-integral-v1",
        "typed-commutative-algebra-chain-dimension-v1",
    }:
        for symbol in ("logic1:and", "logic1:or"):
            groups["v2"].discard(symbol)
            groups.setdefault("2", set()).add(symbol)
    result = {}
    for symbol in registry["symbols"]:
        short = f"{symbol['cd']}:{symbol['name']}"
        kinds = {kind for kind, names in groups.items() if short in names}
        if symbol["name"] in {"forall", "exists"}:
            kinds.add("binder")
        if symbol["name"] == "type":
            kinds.add("type")
        if not kinds:
            raise ValueError(f"Unclassified expression symbol: {profile_id}/{short}")
        result[(symbol["cdbase"], symbol["cd"], symbol["name"])] = frozenset(kinds)
    listed = {f"{s['cd']}:{s['name']}" for s in registry["symbols"]}
    if any(name not in listed for names in _GROUPS[profile_id].values() for name in names.split()):
        raise ValueError("Expression signature not in registry")
    return result


# Dedicated annotation-only constructors, from each validator's _parse_sort.
# Every dependent slot is a direct bound OMV (v), except matrix dimensions (i).
# The unchanged validator still verifies binding order, carrier identity and scope.
_SORT_ARGUMENTS: dict[str, dict[str, str]] = {
    "typed-math-matrix-v1": {
        "typed1:Elem": "v",
        "matrix1:Matrix": "vii",
        "matrix1:ColumnVector": "vi",
    },
    "typed-math-v1": {"typed1:Elem": "v"},
    "typed-real-analysis-v1": {},
    "typed-multivariable-calculus-v1": {},
    "typed-ode-v1": {},
    "typed-finite-graph-v1": {
        "pals_typed_graph:Vertex": "v",
        "pals_typed_graph:VertexClass": "v",
        "pals_typed_graph:Trail": "v",
    },
    "typed-geometry-complex-v1": {},
    "typed-plane-geometry-v1": {},
    "typed-probability-v1": {
        "probability1:Event": "v",
        "probability1:ProbabilityMeasure": "v",
        "probability1:RealRandomVariable": "v",
    },
    "typed-number-theory-v1": {},
    "typed-commutative-algebra-v1": {"commalg1:Ideal": "v", "typed1:Elem": "v"},
    "typed-commutative-algebra-modules-v1": {
        "module1:Module": "v",
        "module1:Submodule": "vv",
        "module1:LinearMap": "vvv",
    },
    "typed-commutative-algebra-localization-v1": {
        "localization1:Submonoid": "v",
        "localization1:SubmonoidElem": "vv",
        "localization1:Localization": "vv",
        "commalg1:Ideal": "v",
        "typed1:Elem": "v",
    },
    "typed-commutative-algebra-integral-v1": {
        "integral1:Extension": "v",
        "integral1:ValuationRing": "v",
        "typed1:Elem": "v",
    },
    "typed-commutative-algebra-decomposition-v1": {
        "decomposition1:Ideal": "v",
        "decomposition1:PrimaryIdeal": "v",
        "decomposition1:PrimeIdeal": "v",
    },
    "typed-commutative-algebra-chain-dimension-v1": {"chain1:Ideal": "v"},
}


def sort_signatures(profile_id: str) -> dict[tuple[str, str, str], str]:
    mapping = signatures(profile_id)
    result = {}
    for symbol, kinds in mapping.items():
        short = f"{symbol[1]}:{symbol[2]}"
        if short in _SORT_ARGUMENTS[profile_id]:
            pattern = _SORT_ARGUMENTS[profile_id][short]
            if kinds != {str(len(pattern))}:
                raise ValueError("Sort signature arity mismatch")
            result[symbol] = pattern
        elif kinds == {"atom"}:
            # All exclusive atomic symbols in these sixteen validators are sorts.
            # nums1:i is the explicit atom/nullary exception and stays term-only.
            result[symbol] = ""
    if len([v for v in result.values() if v]) != len(_SORT_ARGUMENTS[profile_id]):
        raise ValueError("Sort signature missing from registry")
    return result
