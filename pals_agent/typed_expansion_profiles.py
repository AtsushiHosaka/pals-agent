"""Versioned, local authoring profiles separate from published runtime routing.

Each contract is imported only when requested. An unfinished future profile does
not prevent validation of already-authored batches from another profile.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import cast

from pals_agent.typed_local_catalog import _ProfileSpec

_PROFILE_MODULES = {
    "typed-calculus-v2": "typed_calculus_v2",
    "typed-linear-algebra-v2": "typed_linear_algebra_v2",
    "typed-commalg-modules-v2": "typed_commalg_modules_v2",
    "typed-calculus-v3": "typed_calculus_v3",
    "typed-linear-algebra-v3": "typed_linear_algebra_v3",
    "typed-commalg-v3": "typed_commalg_v3",
    "typed-calculus-v4": "typed_calculus_v4",
    "typed-linear-algebra-v4": "typed_linear_algebra_v4",
    "typed-commalg-v4": "typed_commalg_v4",
    "typed-calculus-v5": "typed_calculus_v5",
    "typed-linear-algebra-v5": "typed_linear_algebra_v5",
    "typed-linear-algebra-v6": "typed_linear_algebra_v6",
    "typed-multivariable-v5": "typed_multivariable_v5",
    "typed-vector-calculus-v6": "typed_vector_calculus_v6",
}


def expansion_profile_spec(profile_id: str) -> _ProfileSpec | None:
    """Return an allowlisted authoring profile without changing runtime support."""
    module_name = _PROFILE_MODULES.get(profile_id)
    if module_name is None:
        return None
    module = import_module(f"pals_agent.{module_name}")
    canonicalize = cast(
        Callable[[str], str],
        getattr(module, f"canonicalize_{module_name}_openmath_xml"),
    )
    validator = cast(
        Callable[[str], str],
        getattr(module, f"validate_canonical_{module_name}_openmath_xml"),
    )
    return _ProfileSpec(
        profile_id=profile_id,
        schema_version="pals.typed-catalog-expansion-batch.v1",
        cards_key="cards",
        validator_import=f"pals_agent.{module_name}.{validator.__name__}",
        validator_module_path=f"pals-agent/pals_agent/{module_name}.py",
        registry_path=f"pals-agent/pals_agent/content_dictionaries/{profile_id}-registry.json",
        canonicalize=canonicalize,
        validate_canonical=validator,
    )


def expansion_profile_specs() -> dict[str, _ProfileSpec]:
    """Enumerate finished profiles for cross-profile integration tests."""
    return {
        profile_id: spec
        for profile_id in _PROFILE_MODULES
        if (spec := expansion_profile_spec(profile_id)) is not None
    }
