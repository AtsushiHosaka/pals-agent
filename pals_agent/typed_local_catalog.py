"""Fail-closed preparation for the local, profile-separated typed Draft catalog.

This module has no dependency on the generic ``dsp_drafts`` catalog.  It
validates proposal manifests with their real, isolated OpenMath validators and
then prepares a SQL transaction for the dedicated local typed catalog schema.
The transaction is intentionally not executed here.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import rfc8785

from .typed_commutative_algebra import (
    TYPED_COMMUTATIVE_ALGEBRA_PROFILE,
    canonicalize_typed_commutative_algebra_openmath_xml,
    validate_canonical_typed_commutative_algebra_openmath_xml,
)
from .typed_commutative_algebra_chain_dimension import (
    TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE,
    canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml,
    validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml,
)
from .typed_commutative_algebra_chain_dimension_manifest import (
    TypedCommutativeAlgebraChainDimensionManifestError,
    validate_typed_commutative_algebra_chain_dimension_manifest,
)
from .typed_commutative_algebra_decomposition import (
    TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE,
    canonicalize_typed_commutative_algebra_decomposition_openmath_xml,
    validate_canonical_typed_commutative_algebra_decomposition_openmath_xml,
)
from .typed_commutative_algebra_decomposition_manifest import (
    TypedCommutativeAlgebraDecompositionManifestError,
    validate_typed_commutative_algebra_decomposition_manifest,
)
from .typed_commutative_algebra_integral import (
    TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE,
    canonicalize_typed_commutative_algebra_integral_openmath_xml,
    validate_canonical_typed_commutative_algebra_integral_openmath_xml,
)
from .typed_commutative_algebra_integral_manifest import (
    TypedCommutativeAlgebraIntegralManifestError,
    validate_typed_commutative_algebra_integral_manifest,
)
from .typed_commutative_algebra_localization import (
    TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_PROFILE,
    canonicalize_typed_commutative_algebra_localization_openmath_xml,
    validate_canonical_typed_commutative_algebra_localization_openmath_xml,
)
from .typed_commutative_algebra_localization_manifest import (
    TypedCommutativeAlgebraLocalizationManifestError,
    validate_typed_commutative_algebra_localization_manifest,
)
from .typed_commutative_algebra_manifest import (
    TypedCommutativeAlgebraManifestError,
    validate_typed_commutative_algebra_manifest,
)
from .typed_commutative_algebra_modules import (
    TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE,
    canonicalize_typed_commutative_algebra_modules_openmath_xml,
    validate_canonical_typed_commutative_algebra_modules_openmath_xml,
)
from .typed_commutative_algebra_modules_manifest import (
    TypedCommutativeAlgebraModulesManifestError,
    validate_typed_commutative_algebra_modules_manifest,
)
from .typed_draft_catalog import (
    TypedAuthoringManifestError,
    validate_typed_authoring_manifest,
)
from .typed_finite_graph import (
    TYPED_FINITE_GRAPH_PROFILE,
    canonicalize_typed_finite_graph_openmath_xml,
    validate_canonical_typed_finite_graph_openmath_xml,
)
from .typed_geometry_complex import (
    TYPED_GEOMETRY_COMPLEX_PROFILE,
    canonicalize_typed_geometry_complex_openmath_xml,
    validate_canonical_typed_geometry_complex_openmath_xml,
)
from .typed_geometry_complex_manifest import (
    TypedGeometryComplexManifestError,
    validate_typed_geometry_complex_manifest,
)
from .typed_math import (
    TYPED_MATH_PROFILE,
    canonicalize_typed_math_openmath_xml,
    validate_canonical_typed_math_openmath_xml,
)
from .typed_matrix_profile import (
    TYPED_MATRIX_PROFILE,
    canonicalize_typed_matrix_openmath_xml,
    validate_canonical_typed_matrix_openmath_xml,
)
from .typed_multivariable_calculus import (
    TYPED_MULTIVARIABLE_CALCULUS_PROFILE,
    canonicalize_typed_multivariable_calculus_openmath_xml,
    validate_canonical_typed_multivariable_calculus_openmath_xml,
)
from .typed_number_theory import (
    TYPED_NUMBER_THEORY_PROFILE,
    canonicalize_typed_number_theory_openmath_xml,
    validate_canonical_typed_number_theory_openmath_xml,
)
from .typed_number_theory_manifest import (
    TypedNumberTheoryManifestError,
    validate_typed_number_theory_manifest,
)
from .typed_ode import (
    TYPED_ODE_PROFILE,
    canonicalize_typed_ode_openmath_xml,
    validate_canonical_typed_ode_openmath_xml,
)
from .typed_ode_manifest import TypedOdeManifestError, validate_typed_ode_manifest
from .typed_plane_geometry import (
    TYPED_PLANE_GEOMETRY_PROFILE,
    canonicalize_typed_plane_geometry_openmath_xml,
    validate_canonical_typed_plane_geometry_openmath_xml,
)
from .typed_plane_geometry_manifest import (
    TypedPlaneGeometryManifestError,
    validate_typed_plane_geometry_manifest,
)
from .typed_probability_profile import (
    TYPED_PROBABILITY_PROFILE,
    canonicalize_typed_probability_openmath_xml,
    validate_canonical_typed_probability_openmath_xml,
)
from .typed_real_analysis import (
    TYPED_REAL_ANALYSIS_PROFILE,
    canonicalize_typed_real_analysis_openmath_xml,
    validate_canonical_typed_real_analysis_openmath_xml,
)

TYPED_CATALOG_SCHEMA = "pals_local_typed_catalog"
TYPED_OPENMATH_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v4"
TYPED_EMBEDDING_INPUT_VERSION = "pals-typed-catalog-embedding-v1"
_SHA256_PREFIX = "sha256:"
_EXPECTED_EMBEDDING_DIMENSION = 384
_PINNED_EMBEDDING_BINDING = {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "dimension": 384,
    "endpoint": "https://api.openai.com/v1",
    "deployment": "text-embedding-3-small",
    "revision": "openai-release-2024-01-25",
    "input_version": TYPED_EMBEDDING_INPUT_VERSION,
}


class TypedLocalCatalogError(ValueError):
    """Raised when a typed proposal cannot be safely placed in the local catalog."""


@dataclass(frozen=True, slots=True)
class TypedProfileBinding:
    """The exact validator and registry bytes admitted for one typed profile."""

    profile_id: str
    validator_import: str
    validator_module_path: str
    validator_module_sha256: str
    registry_path: str
    registry_sha256: str
    openmath_canonicalizer_version: str
    binding_sha256: str


@dataclass(frozen=True, slots=True)
class TypedCatalogCard:
    """One verified typed Draft ready for an isolated local catalog transaction."""

    profile_id: str
    manifest_digest: str
    card_id: str
    canonical_statement: str
    canonical_openmath_xml: str
    canonical_openmath_xml_sha256: str
    proof_strategy: str
    sketch_steps: tuple[str, ...]
    openmath_canonicalizer_version: str


@dataclass(frozen=True, slots=True)
class TypedCatalogManifest:
    """A proposal manifest that passed all admission checks available locally."""

    profile: TypedProfileBinding
    manifest_digest: str
    manifest_schema_version: str
    authoring_status: str
    cards: tuple[TypedCatalogCard, ...]


@dataclass(frozen=True, slots=True)
class TypedEmbeddingBinding:
    """Pinned model and input construction metadata for typed catalog embeddings."""

    provider: str
    model: str
    dimension: int
    endpoint: str
    deployment: str
    revision: str
    input_version: str = TYPED_EMBEDDING_INPUT_VERSION

    def __post_init__(self) -> None:
        if self.dimension != _EXPECTED_EMBEDDING_DIMENSION:
            raise TypedLocalCatalogError(
                "typed local catalog requires the pinned 384-dimensional embedding binding"
            )
        for label, value in (
            ("provider", self.provider),
            ("model", self.model),
            ("endpoint", self.endpoint),
            ("deployment", self.deployment),
            ("revision", self.revision),
            ("input_version", self.input_version),
        ):
            if not value.strip():
                raise TypedLocalCatalogError(f"embedding {label} must not be blank")
        actual = {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "revision": self.revision,
            "input_version": self.input_version,
        }
        if actual != _PINNED_EMBEDDING_BINDING:
            raise TypedLocalCatalogError(
                "typed local catalog requires the pinned embedding binding"
            )

    @property
    def binding_sha256(self) -> str:
        return _sha256(
            rfc8785.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "dimension": self.dimension,
                    "endpoint": self.endpoint,
                    "deployment": self.deployment,
                    "revision": self.revision,
                    "input_version": self.input_version,
                }
            )
        )


@dataclass(frozen=True, slots=True)
class _ProfileSpec:
    profile_id: str
    schema_version: str
    cards_key: str
    validator_import: str
    validator_module_path: str
    registry_path: str
    canonicalize: Callable[[str], str]
    validate_canonical: Callable[[str], str]


_MATRIX_SPEC = _ProfileSpec(
    profile_id=TYPED_MATRIX_PROFILE,
    schema_version="pals.typed-math-matrix-v1-authoring-manifest.proposal.v1",
    cards_key="admitted_candidate_cards",
    validator_import=(
        "pals_agent.typed_matrix_profile.validate_canonical_typed_matrix_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_matrix_profile.py",
    registry_path="pals-agent/pals_agent/content_dictionaries/typed-math-matrix-v1-registry.json",
    canonicalize=canonicalize_typed_matrix_openmath_xml,
    validate_canonical=validate_canonical_typed_matrix_openmath_xml,
)
_REAL_ANALYSIS_SPEC = _ProfileSpec(
    profile_id=TYPED_REAL_ANALYSIS_PROFILE,
    schema_version="pals.typed-real-analysis-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_real_analysis.validate_canonical_typed_real_analysis_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_real_analysis.py",
    registry_path="pals-agent/pals_agent/content_dictionaries/typed-real-analysis-v1-registry.json",
    canonicalize=canonicalize_typed_real_analysis_openmath_xml,
    validate_canonical=validate_canonical_typed_real_analysis_openmath_xml,
)
_REAL_ANALYSIS_EXPANSION_SPEC = _ProfileSpec(
    profile_id=TYPED_REAL_ANALYSIS_PROFILE,
    schema_version="pals.typed-real-analysis-v1-expansion-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_real_analysis.validate_canonical_typed_real_analysis_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_real_analysis.py",
    registry_path="pals-agent/pals_agent/content_dictionaries/typed-real-analysis-v1-registry.json",
    canonicalize=canonicalize_typed_real_analysis_openmath_xml,
    validate_canonical=validate_canonical_typed_real_analysis_openmath_xml,
)
_MULTIVARIABLE_CALCULUS_SPEC = _ProfileSpec(
    profile_id=TYPED_MULTIVARIABLE_CALCULUS_PROFILE,
    schema_version="pals.typed-multivariable-calculus-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_multivariable_calculus."
        "validate_canonical_typed_multivariable_calculus_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_multivariable_calculus.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/typed-multivariable-calculus-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_multivariable_calculus_openmath_xml,
    validate_canonical=validate_canonical_typed_multivariable_calculus_openmath_xml,
)
_FINITE_GRAPH_SPEC = _ProfileSpec(
    profile_id=TYPED_FINITE_GRAPH_PROFILE,
    schema_version="pals.typed-finite-graph-v1-sealed-manifest.v1",
    cards_key="admitted_candidate_cards",
    validator_import=(
        "pals_agent.typed_finite_graph.validate_canonical_typed_finite_graph_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_finite_graph.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/typed-finite-graph-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_finite_graph_openmath_xml,
    validate_canonical=validate_canonical_typed_finite_graph_openmath_xml,
)
_GEOMETRY_COMPLEX_SPEC = _ProfileSpec(
    profile_id=TYPED_GEOMETRY_COMPLEX_PROFILE,
    schema_version="pals.typed-geometry-complex-v1-sealed-manifest.v1",
    cards_key="admitted_candidate_cards",
    validator_import=(
        "pals_agent.typed_geometry_complex.validate_canonical_typed_geometry_complex_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_geometry_complex.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/typed-geometry-complex-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_geometry_complex_openmath_xml,
    validate_canonical=validate_canonical_typed_geometry_complex_openmath_xml,
)
_PLANE_GEOMETRY_SPEC = _ProfileSpec(
    profile_id=TYPED_PLANE_GEOMETRY_PROFILE,
    schema_version="pals.typed-plane-geometry-v1-sealed-manifest.v1",
    cards_key="admitted_candidate_cards",
    validator_import=(
        "pals_agent.typed_plane_geometry.validate_canonical_typed_plane_geometry_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_plane_geometry.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/typed-plane-geometry-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_plane_geometry_openmath_xml,
    validate_canonical=validate_canonical_typed_plane_geometry_openmath_xml,
)
_PROBABILITY_SPEC = _ProfileSpec(
    profile_id=TYPED_PROBABILITY_PROFILE,
    schema_version="pals.typed-probability-v1.sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_probability_profile.validate_canonical_typed_probability_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_probability_profile.py",
    registry_path=("pals-agent/pals_agent/content_dictionaries/typed-probability-v1-registry.json"),
    canonicalize=canonicalize_typed_probability_openmath_xml,
    validate_canonical=validate_canonical_typed_probability_openmath_xml,
)
_TYPED_MATH_SPEC = _ProfileSpec(
    profile_id=TYPED_MATH_PROFILE,
    schema_version="pals.typed-math-v1-authoring-manifest.v1",
    cards_key="cards",
    validator_import="pals_agent.typed_math.validate_canonical_typed_math_openmath_xml",
    validator_module_path="pals-agent/pals_agent/typed_math.py",
    registry_path="pals-agent/pals_agent/content_dictionaries/typed-math-v1-registry.json",
    canonicalize=canonicalize_typed_math_openmath_xml,
    validate_canonical=validate_canonical_typed_math_openmath_xml,
)
_NUMBER_THEORY_SPEC = _ProfileSpec(
    profile_id=TYPED_NUMBER_THEORY_PROFILE,
    schema_version="pals.typed-number-theory-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_number_theory.validate_canonical_typed_number_theory_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_number_theory.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/typed-number-theory-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_number_theory_openmath_xml,
    validate_canonical=validate_canonical_typed_number_theory_openmath_xml,
)
_COMMUTATIVE_ALGEBRA_SPEC = _ProfileSpec(
    profile_id=TYPED_COMMUTATIVE_ALGEBRA_PROFILE,
    schema_version="pals.typed-commutative-algebra-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_commutative_algebra."
        "validate_canonical_typed_commutative_algebra_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_commutative_algebra.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/typed-commutative-algebra-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_commutative_algebra_openmath_xml,
    validate_canonical=validate_canonical_typed_commutative_algebra_openmath_xml,
)
_COMMUTATIVE_ALGEBRA_MODULES_SPEC = _ProfileSpec(
    profile_id=TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE,
    schema_version="pals.typed-commutative-algebra-modules-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_commutative_algebra_modules."
        "validate_canonical_typed_commutative_algebra_modules_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_commutative_algebra_modules.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/"
        "typed-commutative-algebra-modules-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_commutative_algebra_modules_openmath_xml,
    validate_canonical=validate_canonical_typed_commutative_algebra_modules_openmath_xml,
)
_COMMUTATIVE_ALGEBRA_LOCALIZATION_SPEC = _ProfileSpec(
    profile_id=TYPED_COMMUTATIVE_ALGEBRA_LOCALIZATION_PROFILE,
    schema_version="pals.typed-commutative-algebra-localization-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_commutative_algebra_localization."
        "validate_canonical_typed_commutative_algebra_localization_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_commutative_algebra_localization.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/"
        "typed-commutative-algebra-localization-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_commutative_algebra_localization_openmath_xml,
    validate_canonical=validate_canonical_typed_commutative_algebra_localization_openmath_xml,
)
_COMMUTATIVE_ALGEBRA_INTEGRAL_SPEC = _ProfileSpec(
    profile_id=TYPED_COMMUTATIVE_ALGEBRA_INTEGRAL_PROFILE,
    schema_version="pals.typed-commutative-algebra-integral-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_commutative_algebra_integral."
        "validate_canonical_typed_commutative_algebra_integral_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_commutative_algebra_integral.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/"
        "typed-commutative-algebra-integral-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_commutative_algebra_integral_openmath_xml,
    validate_canonical=validate_canonical_typed_commutative_algebra_integral_openmath_xml,
)
_COMMUTATIVE_ALGEBRA_DECOMPOSITION_SPEC = _ProfileSpec(
    profile_id=TYPED_COMMUTATIVE_ALGEBRA_DECOMPOSITION_PROFILE,
    schema_version="pals.typed-commutative-algebra-decomposition-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_commutative_algebra_decomposition."
        "validate_canonical_typed_commutative_algebra_decomposition_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_commutative_algebra_decomposition.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/"
        "typed-commutative-algebra-decomposition-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_commutative_algebra_decomposition_openmath_xml,
    validate_canonical=validate_canonical_typed_commutative_algebra_decomposition_openmath_xml,
)
_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_SPEC = _ProfileSpec(
    profile_id=TYPED_COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_PROFILE,
    schema_version="pals.typed-commutative-algebra-chain-dimension-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import=(
        "pals_agent.typed_commutative_algebra_chain_dimension."
        "validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml"
    ),
    validator_module_path="pals-agent/pals_agent/typed_commutative_algebra_chain_dimension.py",
    registry_path=(
        "pals-agent/pals_agent/content_dictionaries/"
        "typed-commutative-algebra-chain-dimension-v1-registry.json"
    ),
    canonicalize=canonicalize_typed_commutative_algebra_chain_dimension_openmath_xml,
    validate_canonical=validate_canonical_typed_commutative_algebra_chain_dimension_openmath_xml,
)
_ODE_SPEC = _ProfileSpec(
    profile_id=TYPED_ODE_PROFILE,
    schema_version="pals.typed-ode-v1-sealed-manifest.v1",
    cards_key="cards",
    validator_import="pals_agent.typed_ode.validate_canonical_typed_ode_openmath_xml",
    validator_module_path="pals-agent/pals_agent/typed_ode.py",
    registry_path="pals-agent/pals_agent/content_dictionaries/typed-ode-v1-registry.json",
    canonicalize=canonicalize_typed_ode_openmath_xml,
    validate_canonical=validate_canonical_typed_ode_openmath_xml,
)
_TYPED_MATH_CORE_MANIFEST = (
    "pals-agent/testdata/typed-math-v1/group-ring-core-authoring-manifest.proposal.json"
)
_TYPED_MATH_TYPICAL_CARD_COUNT = 22
_REAL_ANALYSIS_BASE_MANIFEST = "docs/typed-real-analysis-v1-authoring-manifest-proposal.json"
_REAL_ANALYSIS_BASE_MANIFEST_DIGEST = (
    "sha256:eb7e2e6715678fd45efa30a01e583f4274969e90fca8b2164ad83154a25cb6a8"
)
_MULTIVARIABLE_CALCULUS_HARD_REJECTS = (
    "gradient",
    "hessian",
    "local_extremum",
    "partial_xy_at",
    "double_integral",
    "iterated_integral",
    "fubini",
    "change_of_variables",
)


def load_typed_local_catalog_manifest(
    path: Path,
    *,
    repository_root: Path,
) -> TypedCatalogManifest:
    """Read and fully revalidate one supported, immutable typed proposal manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TypedLocalCatalogError("typed catalog manifest cannot be read") from exc
    if not isinstance(payload, dict):
        raise TypedLocalCatalogError("typed catalog manifest root must be an object")
    return validate_typed_local_catalog_manifest(payload, repository_root=repository_root)


def validate_typed_local_catalog_manifest(
    payload: Mapping[str, object],
    *,
    repository_root: Path,
) -> TypedCatalogManifest:
    """Validate a manifest without accessing Postgres or an embedding provider."""
    if payload.get("schema_version") == "pals.typed-catalog-expansion-batch.v1":
        from .typed_catalog_expansion import validate_expansion_batch

        return validate_expansion_batch(payload, repository_root=repository_root)
    profile_raw = _mapping(payload.get("profile"), "profile")
    profile_id = _required_string(profile_raw.get("id"), "profile.id")
    schema_version = _required_string(payload.get("schema_version"), "schema_version")
    spec = _profile_spec(profile_id, schema_version)

    if spec is _MATRIX_SPEC:
        manifest_digest = _validate_matrix_manifest(payload, repository_root=repository_root)
        authoring_status = _required_string(payload["proposal_status"], "proposal_status")
    elif spec is _TYPED_MATH_SPEC:
        manifest_digest = _validate_typed_math_manifest(payload, repository_root=repository_root)
        authoring_status = _required_string(payload["proposal_status"], "proposal_status")
    elif spec in {_REAL_ANALYSIS_SPEC, _REAL_ANALYSIS_EXPANSION_SPEC}:
        manifest_digest = _validate_real_analysis_manifest(
            payload, spec=spec, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _MULTIVARIABLE_CALCULUS_SPEC:
        manifest_digest = _validate_multivariable_calculus_manifest(
            payload, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _FINITE_GRAPH_SPEC:
        manifest_digest = _validate_finite_graph_manifest(payload, repository_root=repository_root)
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _GEOMETRY_COMPLEX_SPEC:
        manifest_digest = _validate_geometry_complex_manifest(
            payload, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _PLANE_GEOMETRY_SPEC:
        manifest_digest = _validate_plane_geometry_manifest(
            payload, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _PROBABILITY_SPEC:
        manifest_digest = _validate_probability_manifest(payload, repository_root=repository_root)
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _ODE_SPEC:
        manifest_digest = _validate_ode_manifest(payload, repository_root=repository_root)
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _COMMUTATIVE_ALGEBRA_SPEC:
        manifest_digest = _validate_commutative_algebra_manifest(
            payload, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _COMMUTATIVE_ALGEBRA_MODULES_SPEC:
        manifest_digest = _validate_commutative_algebra_modules_manifest(
            payload, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _COMMUTATIVE_ALGEBRA_LOCALIZATION_SPEC:
        manifest_digest = _validate_commutative_algebra_localization_manifest(
            payload, repository_root=repository_root
        )
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _COMMUTATIVE_ALGEBRA_INTEGRAL_SPEC:
        try:
            validate_typed_commutative_algebra_integral_manifest(
                payload, repository_root=repository_root
            )
        except TypedCommutativeAlgebraIntegralManifestError as exc:
            raise TypedLocalCatalogError("typed integral sealed manifest is invalid") from exc
        manifest_digest = _required_string(payload["manifest_payload_sha256"], "manifest digest")
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _COMMUTATIVE_ALGEBRA_DECOMPOSITION_SPEC:
        try:
            validate_typed_commutative_algebra_decomposition_manifest(
                payload, repository_root=repository_root
            )
        except TypedCommutativeAlgebraDecompositionManifestError as exc:
            raise TypedLocalCatalogError("typed decomposition sealed manifest is invalid") from exc
        manifest_digest = _required_string(payload["manifest_payload_sha256"], "manifest digest")
        authoring_status = _required_string(payload["status"], "status")
    elif spec is _COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_SPEC:
        try:
            validate_typed_commutative_algebra_chain_dimension_manifest(
                payload, repository_root=repository_root
            )
        except TypedCommutativeAlgebraChainDimensionManifestError as exc:
            raise TypedLocalCatalogError(
                "typed chain-dimension sealed manifest is invalid"
            ) from exc
        manifest_digest = _required_string(payload["manifest_payload_sha256"], "manifest digest")
        authoring_status = _required_string(payload["status"], "status")
    else:
        manifest_digest = _validate_number_theory_manifest(payload, repository_root=repository_root)
        authoring_status = _required_string(payload["status"], "status")

    profile = _profile_binding(spec, repository_root=repository_root)
    cards_raw = payload.get(spec.cards_key)
    if not isinstance(cards_raw, list) or not cards_raw:
        raise TypedLocalCatalogError("typed catalog manifest has no admitted card list")

    cards: list[TypedCatalogCard] = []
    seen_ids: set[str] = set()
    seen_canonical_xml: set[str] = set()
    for index, raw_card in enumerate(cards_raw, start=1):
        card = _mapping(raw_card, f"{spec.cards_key}[{index}]")
        if spec is _MATRIX_SPEC:
            normalized = _validate_matrix_card(card, spec=spec, index=index)
        elif spec is _TYPED_MATH_SPEC:
            normalized = _validate_typed_math_card(card, spec=spec, index=index)
        elif spec in {_REAL_ANALYSIS_SPEC, _REAL_ANALYSIS_EXPANSION_SPEC}:
            normalized = _validate_real_analysis_card(card, spec=spec, index=index)
        elif spec is _MULTIVARIABLE_CALCULUS_SPEC:
            normalized = _validate_multivariable_calculus_card(
                card, spec=spec, index=index, repository_root=repository_root
            )
        elif spec is _FINITE_GRAPH_SPEC:
            normalized = _validate_finite_graph_card(
                card, spec=spec, index=index, repository_root=repository_root
            )
        elif spec is _GEOMETRY_COMPLEX_SPEC:
            normalized = _validate_geometry_complex_card(
                card, spec=spec, index=index, repository_root=repository_root
            )
        elif spec is _PLANE_GEOMETRY_SPEC:
            normalized = _validate_plane_geometry_card(
                card, spec=spec, index=index, repository_root=repository_root
            )
        elif spec is _PROBABILITY_SPEC:
            normalized = _validate_probability_card(
                card, spec=spec, index=index, repository_root=repository_root
            )
        elif spec is _ODE_SPEC:
            normalized = _validate_ode_card(
                card, spec=spec, index=index, repository_root=repository_root
            )
        elif spec is _COMMUTATIVE_ALGEBRA_SPEC:
            normalized = _validate_commutative_algebra_card(card, spec=spec, index=index)
        elif spec is _COMMUTATIVE_ALGEBRA_MODULES_SPEC:
            normalized = _validate_commutative_algebra_modules_card(card, spec=spec, index=index)
        elif spec is _COMMUTATIVE_ALGEBRA_LOCALIZATION_SPEC:
            normalized = _validate_commutative_algebra_localization_card(
                card, spec=spec, index=index
            )
        elif spec in {
            _COMMUTATIVE_ALGEBRA_INTEGRAL_SPEC,
            _COMMUTATIVE_ALGEBRA_DECOMPOSITION_SPEC,
            _COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_SPEC,
        }:
            # The full sealed manifest validator above binds every card and its
            # evidence. Normalize the retrieval fields without promoting its status.
            normalized = _validate_common_card_fields(card, spec=spec, index=index)
        else:
            normalized = _validate_number_theory_card(card, spec=spec, index=index)
        if normalized.card_id in seen_ids:
            raise TypedLocalCatalogError("typed catalog manifest repeats a card id")
        if normalized.canonical_openmath_xml in seen_canonical_xml:
            raise TypedLocalCatalogError("typed catalog manifest repeats canonical typed OpenMath")
        seen_ids.add(normalized.card_id)
        seen_canonical_xml.add(normalized.canonical_openmath_xml)
        cards.append(
            TypedCatalogCard(
                profile_id=profile.profile_id,
                manifest_digest=manifest_digest,
                card_id=normalized.card_id,
                canonical_statement=normalized.canonical_statement,
                canonical_openmath_xml=normalized.canonical_openmath_xml,
                canonical_openmath_xml_sha256=normalized.canonical_openmath_xml_sha256,
                proof_strategy=normalized.proof_strategy,
                sketch_steps=normalized.sketch_steps,
                openmath_canonicalizer_version=TYPED_OPENMATH_CANONICALIZER_VERSION,
            )
        )
    if spec is _REAL_ANALYSIS_EXPANSION_SPEC:
        _reject_real_analysis_base_collisions(cards, repository_root=repository_root)
    return TypedCatalogManifest(
        profile=profile,
        manifest_digest=manifest_digest,
        manifest_schema_version=spec.schema_version,
        authoring_status=authoring_status,
        cards=tuple(cards),
    )


def typed_catalog_embedding_text(card: TypedCatalogCard) -> str:
    """Return the profile-separated, unambiguous embedding preimage for one card."""
    return (
        f"{TYPED_EMBEDDING_INPUT_VERSION}\n"
        f"profile_id={card.profile_id}\n"
        f"canonical_openmath_xml={card.canonical_openmath_xml}"
    )


def prepare_typed_local_catalog_sql(
    manifest: TypedCatalogManifest,
    *,
    embedding_binding: TypedEmbeddingBinding,
    embeddings: Sequence[Sequence[float]],
) -> str:
    """Create one atomic SQL transaction; it never executes that transaction."""
    if len(embeddings) != len(manifest.cards):
        raise TypedLocalCatalogError("typed catalog embedding count does not match card count")
    normalized_embeddings = tuple(
        _normalize_embedding(vector, index=index)
        for index, vector in enumerate(embeddings, start=1)
    )
    profile = manifest.profile
    binding = embedding_binding
    card_rows = [
        (
            card.profile_id,
            card.manifest_digest,
            card.card_id,
            card.canonical_statement,
            card.canonical_openmath_xml,
            card.canonical_openmath_xml_sha256,
            card.proof_strategy,
            json.dumps(list(card.sketch_steps), ensure_ascii=False, separators=(",", ":")),
            card.openmath_canonicalizer_version,
        )
        for card in manifest.cards
    ]
    embedding_rows = [
        (
            card.profile_id,
            card.manifest_digest,
            card.card_id,
            binding.binding_sha256,
            _pgvector_literal(vector),
        )
        for card, vector in zip(manifest.cards, normalized_embeddings, strict=True)
    ]
    card_copy = _csv_rows(card_rows)
    embedding_copy = _csv_rows(embedding_rows)
    embedding_binding_values = (
        f"{_sql_literal(binding.binding_sha256)}, {_sql_literal(binding.provider)},\n"
        f"  {_sql_literal(binding.model)}, {binding.dimension}, "
        f"{_sql_literal(binding.endpoint)},\n"
        f"  {_sql_literal(binding.deployment)}, {_sql_literal(binding.revision)}, "
        f"{_sql_literal(binding.input_version)}"
    )
    card_ids = ", ".join(_sql_literal(card.card_id) for card in manifest.cards)
    canonical_xml = ", ".join(_sql_literal(card.canonical_openmath_xml) for card in manifest.cards)
    schema = TYPED_CATALOG_SCHEMA
    return f"""BEGIN;
SELECT pg_advisory_xact_lock(hashtext('pals-local-typed-catalog-batch'));
DO $$
BEGIN
  IF to_regclass('{schema}.catalog_profiles') IS NULL
     OR to_regclass('{schema}.catalog_manifests') IS NULL
     OR to_regclass('{schema}.catalog_cards') IS NULL
     OR to_regclass('{schema}.embedding_bindings') IS NULL
     OR to_regclass('{schema}.card_embeddings') IS NULL THEN
    RAISE EXCEPTION 'typed local catalog DDL has not been installed';
  END IF;
  IF EXISTS (
    SELECT 1 FROM {schema}.catalog_profiles
    WHERE profile_id = {_sql_literal(profile.profile_id)}
      AND (validator_import <> {_sql_literal(profile.validator_import)}
        OR validator_module_path <> {_sql_literal(profile.validator_module_path)}
        OR validator_module_sha256 <> {_sql_literal(profile.validator_module_sha256)}
        OR registry_path <> {_sql_literal(profile.registry_path)}
        OR registry_sha256 <> {_sql_literal(profile.registry_sha256)}
        OR openmath_canonicalizer_version <> {_sql_literal(profile.openmath_canonicalizer_version)}
        OR binding_sha256 <> {_sql_literal(profile.binding_sha256)}
        OR embedding_binding_sha256 <> {_sql_literal(binding.binding_sha256)})
  ) THEN
    RAISE EXCEPTION 'typed profile binding is stale or mismatched';
  END IF;
  IF EXISTS (
    SELECT 1 FROM {schema}.catalog_manifests
    WHERE profile_id = {_sql_literal(profile.profile_id)}
      AND manifest_digest = {_sql_literal(manifest.manifest_digest)}
      AND (manifest_schema_version <> {_sql_literal(manifest.manifest_schema_version)}
        OR authoring_status <> {_sql_literal(manifest.authoring_status)})
  ) THEN
    RAISE EXCEPTION 'typed manifest digest is stale or mismatched';
  END IF;
  IF EXISTS (
    SELECT 1 FROM {schema}.embedding_bindings
    WHERE binding_sha256 = {_sql_literal(binding.binding_sha256)}
      AND (provider <> {_sql_literal(binding.provider)}
        OR model <> {_sql_literal(binding.model)}
        OR dimension <> {binding.dimension}
        OR endpoint <> {_sql_literal(binding.endpoint)}
        OR deployment <> {_sql_literal(binding.deployment)}
        OR revision <> {_sql_literal(binding.revision)}
        OR input_version <> {_sql_literal(binding.input_version)})
  ) THEN
    RAISE EXCEPTION 'typed embedding binding is stale or mismatched';
  END IF;
  IF EXISTS (
    SELECT 1 FROM {schema}.catalog_cards
    WHERE profile_id = {_sql_literal(profile.profile_id)}
      AND card_id IN ({card_ids})
  ) THEN
    RAISE EXCEPTION 'typed card id collision';
  END IF;
  IF EXISTS (
    SELECT 1 FROM {schema}.catalog_cards
    WHERE profile_id = {_sql_literal(profile.profile_id)}
      AND canonical_openmath_xml IN ({canonical_xml})
  ) THEN
    RAISE EXCEPTION 'typed canonical OpenMath collision';
  END IF;
END $$;
INSERT INTO {schema}.embedding_bindings (
  binding_sha256, provider, model, dimension, endpoint, deployment, revision, input_version
) VALUES (
  {embedding_binding_values}
) ON CONFLICT (binding_sha256) DO NOTHING;
INSERT INTO {schema}.catalog_profiles (
  profile_id, validator_import, validator_module_path, validator_module_sha256,
  registry_path, registry_sha256, openmath_canonicalizer_version, binding_sha256,
  embedding_binding_sha256
) VALUES (
  {_sql_literal(profile.profile_id)}, {_sql_literal(profile.validator_import)},
  {_sql_literal(profile.validator_module_path)}, {_sql_literal(profile.validator_module_sha256)},
  {_sql_literal(profile.registry_path)}, {_sql_literal(profile.registry_sha256)},
  {_sql_literal(profile.openmath_canonicalizer_version)}, {_sql_literal(profile.binding_sha256)},
  {_sql_literal(binding.binding_sha256)}
) ON CONFLICT (profile_id) DO NOTHING;
INSERT INTO {schema}.catalog_manifests (
  profile_id, manifest_digest, manifest_schema_version, authoring_status
) VALUES (
  {_sql_literal(profile.profile_id)}, {_sql_literal(manifest.manifest_digest)},
  {_sql_literal(manifest.manifest_schema_version)}, {_sql_literal(manifest.authoring_status)}
) ON CONFLICT (profile_id, manifest_digest) DO NOTHING;
COPY {schema}.catalog_cards (
  profile_id, manifest_digest, card_id, canonical_statement, canonical_openmath_xml,
  canonical_openmath_xml_sha256, proof_strategy, sketch_steps,
  openmath_canonicalizer_version
) FROM STDIN WITH (FORMAT csv);
{card_copy}\\.
COPY {schema}.card_embeddings (
  profile_id, manifest_digest, card_id, binding_sha256, embedding
) FROM STDIN WITH (FORMAT csv);
{embedding_copy}\\.
DO $$
BEGIN
  IF (SELECT count(*) FROM {schema}.catalog_cards
      WHERE profile_id = {_sql_literal(profile.profile_id)}
        AND manifest_digest = {_sql_literal(manifest.manifest_digest)}
        AND card_id IN ({card_ids})) <> {len(manifest.cards)} THEN
    RAISE EXCEPTION 'typed card insert count mismatch';
  END IF;
  IF (SELECT count(*) FROM {schema}.card_embeddings
      WHERE profile_id = {_sql_literal(profile.profile_id)}
        AND manifest_digest = {_sql_literal(manifest.manifest_digest)}
        AND card_id IN ({card_ids})
        AND binding_sha256 = {_sql_literal(binding.binding_sha256)}) <> {len(manifest.cards)} THEN
    RAISE EXCEPTION 'typed embedding insert count mismatch';
  END IF;
  IF EXISTS (
    SELECT 1 FROM {schema}.card_embeddings
    WHERE profile_id = {_sql_literal(profile.profile_id)}
      AND manifest_digest = {_sql_literal(manifest.manifest_digest)}
      AND card_id IN ({card_ids})
      AND (vector_dims(embedding) <> {binding.dimension} OR embedding <#> embedding >= 0)
  ) THEN
    RAISE EXCEPTION 'typed embedding dimension or norm mismatch';
  END IF;
END $$;
COMMIT;
"""


def _validate_matrix_manifest(payload: Mapping[str, object], *, repository_root: Path) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "proposal_status",
            "profile",
            "lean_witness_bundle",
            "admitted_candidate_cards",
            "excluded_witnesses",
            "manifest_digest",
        },
        "matrix manifest",
    )
    if payload["proposal_status"] != "not_admitted_requires_independent_project_review":
        raise TypedLocalCatalogError("matrix manifest proposal status is invalid")
    profile = _mapping(payload["profile"], "profile")
    _require_exact_keys(
        profile,
        {
            "id",
            "validator",
            "validator_status",
            "canonicalizer",
            "canonicalization_scope",
            "admission_openmath_field",
            "signature_contract",
            "signature_contract_sha256",
            "content_dictionary_bundle",
            "lean_toolchain",
        },
        "matrix profile",
    )
    if (
        profile["id"] != _MATRIX_SPEC.profile_id
        or profile["validator"] != _MATRIX_SPEC.validator_import
        or profile["validator_status"] != "implemented_local_evidence_not_independently_reviewed"
        or profile["canonicalizer"] != TYPED_OPENMATH_CANONICALIZER_VERSION
        or profile["admission_openmath_field"] != "canonical_openmath_xml"
        or not isinstance(profile["canonicalization_scope"], str)
        or not profile["canonicalization_scope"].strip()
    ):
        raise TypedLocalCatalogError("matrix manifest profile is invalid")
    contract = _mapping(profile["signature_contract"], "profile.signature_contract")
    _require_digest(
        rfc8785.dumps(cast(Any, contract)),
        _required_string(profile["signature_contract_sha256"], "profile.signature_contract_sha256"),
    )
    cd_bundle = _mapping(profile["content_dictionary_bundle"], "profile.content_dictionary_bundle")
    _require_exact_keys(
        cd_bundle,
        {"relative_path", "sha256", "digest_input"},
        "profile.content_dictionary_bundle",
    )
    if (
        cd_bundle["relative_path"] != _MATRIX_SPEC.registry_path
        or cd_bundle["digest_input"] != "exact UTF-8 bytes of the named registry/CD bundle"
    ):
        raise TypedLocalCatalogError("matrix manifest content dictionary binding is invalid")
    _require_digest(
        _read_relative(repository_root, _MATRIX_SPEC.registry_path),
        _required_string(cd_bundle["sha256"], "profile.content_dictionary_bundle.sha256"),
    )
    _validate_lean_toolchain(
        _mapping(profile["lean_toolchain"], "profile.lean_toolchain"),
        repository_root=repository_root,
    )
    _validate_matrix_witness_bundle(
        _mapping(payload["lean_witness_bundle"], "lean_witness_bundle"),
        repository_root=repository_root,
    )
    digest = _mapping(payload["manifest_digest"], "manifest_digest")
    _require_exact_keys(digest, {"algorithm", "input", "sha256"}, "manifest_digest")
    if digest["algorithm"] != "sha256" or digest["input"] != (
        "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
    ):
        raise TypedLocalCatalogError("matrix manifest digest metadata is invalid")
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    actual = _sha256(rfc8785.dumps(cast(Any, unsigned)))
    if digest["sha256"] != actual:
        raise TypedLocalCatalogError("matrix manifest digest does not match")
    return actual


def _validate_geometry_complex_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Adapt the sealed phase-A vector/complex proposal without publishing it."""
    try:
        validate_typed_geometry_complex_manifest(payload, repository_root=repository_root)
    except TypedGeometryComplexManifestError as exc:
        raise TypedLocalCatalogError("vector/complex authoring manifest is invalid") from exc

    cards = payload["admitted_candidate_cards"]
    if not isinstance(cards, list) or len(cards) != 8:
        raise TypedLocalCatalogError(
            "vector/complex manifest must seal exactly eight phase-A cards"
        )
    deferred = payload["deferred_backlog_cards"]
    if not isinstance(deferred, list) or len(deferred) != 4:
        raise TypedLocalCatalogError(
            "vector/complex manifest must defer exactly four phase-B cards"
        )
    digest = _mapping(payload["manifest_digest"], "vector/complex manifest_digest")
    _require_exact_keys(digest, {"algorithm", "input", "sha256"}, "vector/complex manifest_digest")
    return _required_string(digest["sha256"], "vector/complex manifest_digest.sha256")


def _validate_plane_geometry_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Adapt the isolated five-card plane-geometry proposal without publishing it."""
    try:
        validate_typed_plane_geometry_manifest(payload, repository_root=repository_root)
    except TypedPlaneGeometryManifestError as exc:
        raise TypedLocalCatalogError("plane-geometry authoring manifest is invalid") from exc

    cards = payload["admitted_candidate_cards"]
    if not isinstance(cards, list) or len(cards) != 5:
        raise TypedLocalCatalogError("plane-geometry manifest must seal exactly five cards")
    digest = _mapping(payload["manifest_digest"], "plane-geometry manifest_digest")
    _require_exact_keys(digest, {"algorithm", "input", "sha256"}, "plane-geometry manifest_digest")
    return _required_string(digest["sha256"], "plane-geometry manifest_digest.sha256")


def _validate_real_analysis_manifest(
    payload: Mapping[str, object], *, spec: _ProfileSpec, repository_root: Path
) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "immutability_contract",
            "profile",
            "lean_receipt",
            "adopted_card_count",
            "excluded_witness_count",
            "witness_audit_count",
            "cards",
            "witness_audit",
            "excluded_witnesses",
            "manifest_payload_sha256",
        },
        "real-analysis manifest",
    )
    if payload["status"] != "sealed_local_authoring_revision_not_admitted":
        raise TypedLocalCatalogError("real-analysis manifest status is invalid")
    seal = _mapping(payload["seal"], "seal")
    _require_exact_keys(seal, {"scope", "admission", "revision"}, "seal")
    if spec is _REAL_ANALYSIS_SPEC:
        expected_scope = "local typed-real-analysis authoring evidence only"
        expected_revision = "typed-real-analysis-v1-local-r1"
        expected_card_count = 4
    else:
        expected_scope = "local typed-real-analysis-v1 r2 expansion authoring evidence only"
        expected_revision = "typed-real-analysis-v1-expansion-r2"
        expected_card_count = 15
    if (
        seal["scope"] != expected_scope
        or seal["admission"]
        != "not admitted to the generic DB, seed, embedding index, or PFI package"
        or seal["revision"] != expected_revision
    ):
        raise TypedLocalCatalogError("real-analysis manifest seal is invalid")
    profile = _mapping(payload["profile"], "profile")
    _require_exact_keys(
        profile,
        {
            "id",
            "typed_cdbase",
            "profile_design_path",
            "profile_design_sha256",
            "registry_path",
            "registry_digest",
            "registry_status",
        },
        "real-analysis profile",
    )
    if (
        profile["id"] != spec.profile_id
        or profile["typed_cdbase"] != "urn:pals:openmath:typed-math:v1"
        or profile["registry_path"]
        != "pals_agent/content_dictionaries/typed-real-analysis-v1-registry.json"
        or not isinstance(profile["registry_status"], str)
        or not profile["registry_status"].strip()
    ):
        raise TypedLocalCatalogError("real-analysis manifest profile is invalid")
    _require_digest(
        _read_relative(
            repository_root,
            _required_string(profile["profile_design_path"], "profile.profile_design_path"),
        ),
        _required_string(profile["profile_design_sha256"], "profile.profile_design_sha256"),
    )
    _require_digest(
        _read_relative(
            repository_root / "pals-agent",
            _required_string(profile["registry_path"], "profile.registry_path"),
        ),
        _required_string(profile["registry_digest"], "profile.registry_digest"),
    )
    receipt = _mapping(payload["lean_receipt"], "lean_receipt")
    _require_exact_keys(
        receipt, {"witness_path", "witness_file_sha256", "verification_status"}, "lean_receipt"
    )
    if (
        not isinstance(receipt["verification_status"], str)
        or not receipt["verification_status"].strip()
    ):
        raise TypedLocalCatalogError("real-analysis Lean receipt status is invalid")
    _require_digest(
        _read_relative(
            repository_root, _required_string(receipt["witness_path"], "lean_receipt.witness_path")
        ),
        _required_string(receipt["witness_file_sha256"], "lean_receipt.witness_file_sha256"),
    )
    cards = payload["cards"]
    audits = payload["witness_audit"]
    excluded = payload["excluded_witnesses"]
    if (
        not isinstance(cards, list)
        or not isinstance(audits, list)
        or not isinstance(excluded, list)
        or payload["adopted_card_count"] != len(cards)
        or len(cards) != expected_card_count
        or payload["excluded_witness_count"] != len(excluded)
        or payload["witness_audit_count"] != len(audits)
    ):
        raise TypedLocalCatalogError("real-analysis manifest counts are invalid")
    immutable = _mapping(payload["immutability_contract"], "immutability_contract")
    _require_exact_keys(
        immutable,
        {"digest_algorithm", "structural_openmath_c14n", "profile_c14n", "mutation_rule"},
        "immutability_contract",
    )
    if any(not isinstance(value, str) or not value.strip() for value in immutable.values()):
        raise TypedLocalCatalogError("real-analysis immutability contract is invalid")
    unsigned = dict(payload)
    expected = _required_string(unsigned.pop("manifest_payload_sha256"), "manifest_payload_sha256")
    actual = _sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    if expected != actual:
        raise TypedLocalCatalogError("real-analysis manifest digest does not match")
    if spec is _REAL_ANALYSIS_SPEC and actual != _REAL_ANALYSIS_BASE_MANIFEST_DIGEST:
        raise TypedLocalCatalogError("real-analysis base snapshot digest is not immutable")
    return actual


def _validate_multivariable_calculus_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Admit only the six-card, first-derivative multivariable sealed revision."""
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "profile",
            "lean_receipt",
            "hard_rejects",
            "cards",
            "manifest_payload_sha256",
        },
        "multivariable-calculus manifest",
    )
    if payload["status"] != "sealed_local_authoring_revision_not_admitted":
        raise TypedLocalCatalogError("multivariable-calculus manifest status is invalid")
    _validate_sealed_local_status(
        payload,
        scope="local typed multivariable-calculus authoring evidence only",
        revision="typed-multivariable-calculus-v1-local-r1",
        label="multivariable-calculus",
    )
    hard_rejects = payload["hard_rejects"]
    if (
        not isinstance(hard_rejects, list)
        or tuple(hard_rejects) != _MULTIVARIABLE_CALCULUS_HARD_REJECTS
    ):
        raise TypedLocalCatalogError("multivariable-calculus hard reject boundary is invalid")
    profile = _mapping(payload["profile"], "profile")
    _require_exact_keys(
        profile,
        {
            "id",
            "validator",
            "canonicalizer",
            "profile_design_path",
            "profile_design_sha256",
            "registry_path",
            "registry_digest",
            "lean_toolchain",
        },
        "multivariable-calculus profile",
    )
    if (
        profile["id"] != _MULTIVARIABLE_CALCULUS_SPEC.profile_id
        or profile["validator"] != _MULTIVARIABLE_CALCULUS_SPEC.validator_import
        or profile["canonicalizer"] != TYPED_OPENMATH_CANONICALIZER_VERSION
        or profile["profile_design_path"] != "docs/typed-multivariable-calculus-v1-design.md"
        or profile["registry_path"]
        != "pals_agent/content_dictionaries/typed-multivariable-calculus-v1-registry.json"
    ):
        raise TypedLocalCatalogError("multivariable-calculus manifest profile is invalid")
    _require_digest(
        _read_relative(
            repository_root,
            _required_string(profile["profile_design_path"], "profile.profile_design_path"),
        ),
        _required_string(profile["profile_design_sha256"], "profile.profile_design_sha256"),
    )
    _require_digest(
        _read_relative(
            repository_root / "pals-agent",
            _required_string(profile["registry_path"], "profile.registry_path"),
        ),
        _required_string(profile["registry_digest"], "profile.registry_digest"),
    )
    _validate_lean_toolchain(
        _mapping(profile["lean_toolchain"], "profile.lean_toolchain"),
        repository_root=repository_root,
    )
    receipt = _mapping(payload["lean_receipt"], "lean_receipt")
    _require_exact_keys(
        receipt,
        {
            "witness_path",
            "witness_file_sha256",
            "verification_command",
            "verification_status",
            "scope",
        },
        "multivariable-calculus lean_receipt",
    )
    if (
        receipt["witness_path"] != "docs/typed-multivariable-calculus-v1-authoring-witnesses.lean"
        or receipt["verification_command"]
        != "cd pals-agent/lean-workspace && lake env lean "
        "../../docs/typed-multivariable-calculus-v1-authoring-witnesses.lean"
        or receipt["verification_status"] != "verified_local_pinned_workspace"
        or receipt["scope"]
        != "manual statement-to-OpenMath-to-Lean alignment; no automatic translator claim"
    ):
        raise TypedLocalCatalogError("multivariable-calculus Lean receipt is invalid")
    _require_digest(
        _read_relative(
            repository_root,
            _required_string(receipt["witness_path"], "lean_receipt.witness_path"),
        ),
        _required_string(receipt["witness_file_sha256"], "lean_receipt.witness_file_sha256"),
    )
    cards = payload["cards"]
    if not isinstance(cards, list) or len(cards) != 6:
        raise TypedLocalCatalogError("multivariable-calculus manifest must seal exactly six cards")
    unsigned = dict(payload)
    expected = _required_string(unsigned.pop("manifest_payload_sha256"), "manifest_payload_sha256")
    actual = _sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    if expected != actual:
        raise TypedLocalCatalogError("multivariable-calculus manifest digest does not match")
    return actual


def _reject_real_analysis_base_collisions(
    expansion_cards: Sequence[TypedCatalogCard], *, repository_root: Path
) -> None:
    """Reject r2 cards that would mutate the r1 profile namespace in place."""
    base_manifest = load_typed_local_catalog_manifest(
        repository_root / _REAL_ANALYSIS_BASE_MANIFEST,
        repository_root=repository_root,
    )
    base_ids = {card.card_id for card in base_manifest.cards}
    base_canonical = {card.canonical_openmath_xml for card in base_manifest.cards}
    for card in expansion_cards:
        if card.card_id in base_ids:
            raise TypedLocalCatalogError(
                "real-analysis expansion card id collides with base snapshot"
            )
        if card.canonical_openmath_xml in base_canonical:
            raise TypedLocalCatalogError(
                "real-analysis expansion canonical OpenMath collides with base snapshot"
            )


def _validate_typed_math_manifest(payload: Mapping[str, object], *, repository_root: Path) -> str:
    """Adapt the sealed typed-math authoring format into the local catalog contract."""
    package_root = repository_root / "pals-agent"
    try:
        validate_typed_authoring_manifest(payload, root=package_root)
    except TypedAuthoringManifestError as exc:
        raise TypedLocalCatalogError("typed-math authoring manifest is invalid") from exc

    cards = payload["cards"]
    if not isinstance(cards, list) or len(cards) != _TYPED_MATH_TYPICAL_CARD_COUNT:
        raise TypedLocalCatalogError(
            "typed local catalog accepts only the sealed 22-card typed-math "
            "typical-theorems revision"
        )
    baseline = _load_typed_math_core_manifest(repository_root)
    baseline_cards = baseline["cards"]
    assert isinstance(baseline_cards, list)  # Validated above.
    if len(baseline_cards) != 3:
        raise TypedLocalCatalogError(
            "typed-math core baseline must contain exactly three sealed cards"
        )
    _reject_typed_math_core_collisions(cards, baseline_cards)

    digest = _mapping(payload["manifest_digest"], "manifest_digest")
    return _required_string(digest["sha256"], "typed-math manifest_digest.sha256")


def _load_typed_math_core_manifest(repository_root: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(
            _read_relative(repository_root, _TYPED_MATH_CORE_MANIFEST).decode("utf-8")
        )
    except json.JSONDecodeError as exc:
        raise TypedLocalCatalogError("typed-math core baseline cannot be read") from exc
    if not isinstance(payload, Mapping):
        raise TypedLocalCatalogError("typed-math core baseline must be an object")
    try:
        validate_typed_authoring_manifest(payload, root=repository_root / "pals-agent")
    except TypedAuthoringManifestError as exc:
        raise TypedLocalCatalogError("typed-math core baseline is invalid") from exc
    return cast(Mapping[str, object], payload)


def _reject_typed_math_core_collisions(
    typical_cards: list[object], core_cards: list[object]
) -> None:
    typical_ids: set[str] = set()
    typical_canonical: set[str] = set()
    for index, raw in enumerate(typical_cards, start=1):
        card = _mapping(raw, f"typed-math cards[{index}]")
        typical_ids.add(_required_string(card.get("id"), f"typed-math cards[{index}].id"))
        typical_canonical.add(
            _required_string(
                card.get("canonical_openmath_xml"),
                f"typed-math cards[{index}].canonical_openmath_xml",
            )
        )
    core_ids: set[str] = set()
    core_canonical: set[str] = set()
    for index, raw in enumerate(core_cards, start=1):
        card = _mapping(raw, f"typed-math core cards[{index}]")
        core_ids.add(_required_string(card.get("id"), f"typed-math core cards[{index}].id"))
        core_canonical.add(
            _required_string(
                card.get("canonical_openmath_xml"),
                f"typed-math core cards[{index}].canonical_openmath_xml",
            )
        )
    if typical_ids & core_ids:
        raise TypedLocalCatalogError("typed-math typical-theorems card id collides with core")
    if typical_canonical & core_canonical:
        raise TypedLocalCatalogError(
            "typed-math typical-theorems canonical OpenMath collides with core"
        )


def _validate_finite_graph_manifest(payload: Mapping[str, object], *, repository_root: Path) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "immutability_contract",
            "profile",
            "lean_witness_bundle",
            "admitted_candidate_cards",
            "excluded_witnesses",
            "manifest_digest",
        },
        "finite-graph manifest",
    )
    _validate_sealed_local_status(
        payload,
        scope="local typed-finite-graph authoring evidence only",
        revision="typed-finite-graph-v1-local-r1",
        label="finite-graph",
    )
    immutable = _mapping(payload["immutability_contract"], "immutability_contract")
    _require_exact_keys(
        immutable,
        {"digest_algorithm", "canonical_json", "profile_c14n", "mutation_rule"},
        "finite-graph immutability contract",
    )
    if immutable["canonical_json"] != (
        "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
    ):
        raise TypedLocalCatalogError("finite-graph immutability contract is invalid")
    _require_nonempty_strings(immutable, "finite-graph immutability contract")

    profile = _mapping(payload["profile"], "profile")
    _require_exact_keys(
        profile,
        {
            "id",
            "typed_cdbase",
            "validator",
            "validator_status",
            "registry_status",
            "canonicalization_scope",
            "content_dictionary_bundle",
            "profile_design",
            "signature_contract",
            "signature_contract_sha256",
            "lean_bridge",
        },
        "finite-graph profile",
    )
    if (
        profile["id"] != _FINITE_GRAPH_SPEC.profile_id
        or profile["typed_cdbase"] != "urn:pals:openmath:typed-finite-graph:v1"
        or profile["validator"] != _FINITE_GRAPH_SPEC.validator_import
        or profile["validator_status"] != "implemented_isolated_profile"
        or profile["registry_status"] != "implemented_isolated_profile"
        or profile["canonicalization_scope"]
        != "typed-finite-graph-v1 validation followed by profile-separated XML C14N"
    ):
        raise TypedLocalCatalogError("finite-graph manifest profile is invalid")
    cd_bundle = _mapping(profile["content_dictionary_bundle"], "content_dictionary_bundle")
    _require_exact_keys(
        cd_bundle,
        {"relative_path", "sha256", "digest_input"},
        "finite-graph content dictionary bundle",
    )
    if (
        cd_bundle["relative_path"] != _FINITE_GRAPH_SPEC.registry_path
        or cd_bundle["digest_input"] != "exact UTF-8 bytes of the named registry/CD bundle"
    ):
        raise TypedLocalCatalogError("finite-graph registry binding is invalid")
    _require_digest(
        _read_relative(repository_root, _FINITE_GRAPH_SPEC.registry_path),
        _required_string(cd_bundle["sha256"], "finite-graph registry digest"),
    )
    design = _mapping(profile["profile_design"], "profile_design")
    _require_exact_keys(design, {"path", "sha256"}, "finite-graph profile design")
    _require_digest(
        _read_relative(repository_root, _required_string(design["path"], "profile_design.path")),
        _required_string(design["sha256"], "profile_design.sha256"),
    )
    contract = _mapping(profile["signature_contract"], "signature_contract")
    _require_exact_keys(
        contract,
        {
            "source",
            "status",
            "sorts",
            "symbols_used_by_admitted_candidates",
            "intentional_absences",
        },
        "finite-graph signature contract",
    )
    _required_string(contract["source"], "signature_contract.source")
    _required_string(contract["status"], "signature_contract.status")
    _require_nonempty_string_mapping(
        _mapping(contract["sorts"], "signature_contract.sorts"), "signature_contract.sorts"
    )
    _require_nonempty_string_mapping(
        _mapping(
            contract["symbols_used_by_admitted_candidates"],
            "signature_contract.symbols_used_by_admitted_candidates",
        ),
        "signature_contract.symbols_used_by_admitted_candidates",
    )
    _require_nonempty_string_list(
        contract["intentional_absences"], "signature_contract.intentional_absences"
    )
    _require_digest(
        rfc8785.dumps(cast(Any, contract)),
        _required_string(profile["signature_contract_sha256"], "signature_contract_sha256"),
    )
    bridge = _mapping(profile["lean_bridge"], "lean_bridge")
    _require_exact_keys(
        bridge,
        {"FinSimpleGraph", "Vertex(G)", "Trail(G)", "is_euler_trail(G,t)"},
        "finite-graph Lean bridge",
    )
    _require_nonempty_strings(bridge, "finite-graph Lean bridge")
    bundle = _mapping(payload["lean_witness_bundle"], "lean_witness_bundle")
    _require_exact_keys(
        bundle,
        {"path", "sha256", "digest_input", "verification_command", "verification_status", "scope"},
        "finite-graph Lean witness bundle",
    )
    if bundle[
        "digest_input"
    ] != "exact UTF-8 bytes of the named Lean file, including import and final newline" or bundle[
        "verification_status"
    ] != (
        "compiled when generator is run with --verify-lean; sealed evidence only, "
        "not an OpenMath-to-Lean translation receipt"
    ):
        raise TypedLocalCatalogError("finite-graph Lean witness bundle is invalid")
    _require_nonempty_strings(bundle, "finite-graph Lean witness bundle")
    bundle_path = _required_string(bundle["path"], "lean_witness_bundle.path")
    _require_digest(
        _read_relative(repository_root, bundle_path),
        _required_string(bundle["sha256"], "lean_witness_bundle.sha256"),
    )
    cards = payload["admitted_candidate_cards"]
    excluded = payload["excluded_witnesses"]
    if not isinstance(cards, list) or len(cards) != 5:
        raise TypedLocalCatalogError("finite-graph manifest must seal exactly five cards")
    if not isinstance(excluded, list) or len(excluded) != 2:
        raise TypedLocalCatalogError("finite-graph manifest must retain two exclusions")
    _validate_exclusion_records(excluded, label="finite-graph exclusions")

    digest = _mapping(payload["manifest_digest"], "manifest_digest")
    _require_exact_keys(digest, {"algorithm", "input", "sha256"}, "finite-graph manifest digest")
    if digest["algorithm"] != "sha256" or digest["input"] != (
        "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
    ):
        raise TypedLocalCatalogError("finite-graph manifest digest metadata is invalid")
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    actual = _sha256(rfc8785.dumps(cast(Any, unsigned)))
    if digest["sha256"] != actual:
        raise TypedLocalCatalogError("finite-graph manifest digest does not match")
    return actual


def _validate_probability_manifest(payload: Mapping[str, object], *, repository_root: Path) -> str:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "status",
            "seal",
            "immutability_contract",
            "profile",
            "lean_receipt",
            "admitted_card_count",
            "excluded_card_count",
            "cards",
            "excluded_cards",
            "manifest_payload_sha256",
        },
        "probability manifest",
    )
    _validate_sealed_local_status(
        payload,
        scope="local typed-probability authoring evidence only",
        revision="typed-probability-v1-local-r1",
        label="probability",
    )
    immutable = _mapping(payload["immutability_contract"], "immutability_contract")
    _require_exact_keys(
        immutable,
        {"digest_algorithm", "structural_openmath_c14n", "mutation_rule", "profile_separation"},
        "probability immutability contract",
    )
    _require_nonempty_strings(immutable, "probability immutability contract")

    profile = _mapping(payload["profile"], "profile")
    _require_exact_keys(
        profile,
        {
            "id",
            "typed_cdbase",
            "design_path",
            "design_sha256",
            "registry_path",
            "probability1_cd_bundle_sha256",
            "validator",
            "validator_version",
            "canonicalizer_version",
        },
        "probability profile",
    )
    if (
        profile["id"] != _PROBABILITY_SPEC.profile_id
        or profile["typed_cdbase"] != "urn:pals:openmath:typed-math:v1"
        or profile["registry_path"]
        != "pals_agent/content_dictionaries/typed-probability-v1-registry.json"
        or profile["validator"] != _PROBABILITY_SPEC.validator_import
        or profile["validator_version"] != "typed-probability-v1-local-r1"
        or profile["canonicalizer_version"] != "openmath-v4-profile-c14n"
    ):
        raise TypedLocalCatalogError("probability manifest profile is invalid")
    _require_digest(
        _read_relative(
            repository_root, _required_string(profile["design_path"], "profile.design_path")
        ),
        _required_string(profile["design_sha256"], "profile.design_sha256"),
    )
    registry_path = _PROBABILITY_SPEC.registry_path.removeprefix("pals-agent/")
    _require_digest(
        _read_relative(repository_root / "pals-agent", registry_path),
        _required_string(
            profile["probability1_cd_bundle_sha256"], "profile.probability1_cd_bundle_sha256"
        ),
    )
    receipt = _mapping(payload["lean_receipt"], "lean_receipt")
    _require_exact_keys(
        receipt,
        {"witness_path", "witness_file_sha256", "toolchain", "verification_status"},
        "probability Lean receipt",
    )
    if receipt["verification_status"] != (
        "compiled when generator is run with --verify-lean; sealed evidence only, "
        "not an OpenMath-to-Lean translation receipt"
    ):
        raise TypedLocalCatalogError("probability Lean receipt status is invalid")
    _require_nonempty_strings(receipt, "probability Lean receipt")
    witness_path = _required_string(receipt["witness_path"], "lean_receipt.witness_path")
    _require_digest(
        _read_relative(repository_root, witness_path),
        _required_string(receipt["witness_file_sha256"], "lean_receipt.witness_file_sha256"),
    )
    toolchain = _read_relative(repository_root / "pals-agent", "lean-workspace/lean-toolchain")
    if receipt["toolchain"] != toolchain.decode("utf-8").rstrip("\n"):
        raise TypedLocalCatalogError(
            "probability Lean toolchain does not match the pinned workspace"
        )
    cards = payload["cards"]
    excluded = payload["excluded_cards"]
    if (
        not isinstance(cards, list)
        or len(cards) != 10
        or payload["admitted_card_count"] != len(cards)
        or not isinstance(excluded, list)
        or len(excluded) != 7
        or payload["excluded_card_count"] != len(excluded)
    ):
        raise TypedLocalCatalogError("probability manifest card counts are invalid")
    _validate_exclusion_records(excluded, label="probability exclusions")
    unsigned = dict(payload)
    expected = _required_string(unsigned.pop("manifest_payload_sha256"), "manifest_payload_sha256")
    unsigned_json = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual = _sha256(unsigned_json.encode("utf-8"))
    if expected != actual:
        raise TypedLocalCatalogError("probability manifest digest does not match")
    return actual


def _validate_number_theory_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Adapt the sealed number-theory proposal only after full evidence revalidation."""
    try:
        validate_typed_number_theory_manifest(payload, repository_root=repository_root)
    except TypedNumberTheoryManifestError as exc:
        raise TypedLocalCatalogError("number-theory manifest is invalid") from exc
    digest = _required_string(
        payload.get("manifest_payload_sha256"), "number-theory manifest_payload_sha256"
    )
    return digest


def _validate_commutative_algebra_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Admit the isolated 13-card ideal-lattice revision only after revalidation."""
    try:
        validate_typed_commutative_algebra_manifest(payload, repository_root=repository_root)
    except TypedCommutativeAlgebraManifestError as exc:
        raise TypedLocalCatalogError("commutative-algebra manifest is invalid") from exc
    if (
        payload.get("status") != "sealed_local_authoring_revision_not_admitted"
        or payload.get("admitted_card_count") != 13
        or payload.get("excluded_card_count") != 4
    ):
        raise TypedLocalCatalogError("commutative-algebra manifest sealed status is invalid")
    return _required_string(
        payload.get("manifest_payload_sha256"),
        "commutative-algebra manifest_payload_sha256",
    )


def _validate_commutative_algebra_modules_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Admit the sealed CA-2 module core only after full evidence revalidation."""
    try:
        validate_typed_commutative_algebra_modules_manifest(
            payload, repository_root=repository_root
        )
    except TypedCommutativeAlgebraModulesManifestError as exc:
        raise TypedLocalCatalogError("commutative-algebra modules manifest is invalid") from exc
    if (
        payload.get("status") != "sealed_local_authoring_revision_not_admitted"
        or payload.get("admitted_card_count") != 24
        or payload.get("excluded_card_count") != 4
    ):
        raise TypedLocalCatalogError(
            "commutative-algebra modules manifest sealed status is invalid"
        )
    return _required_string(
        payload.get("manifest_payload_sha256"),
        "commutative-algebra modules manifest_payload_sha256",
    )


def _validate_commutative_algebra_localization_manifest(
    payload: Mapping[str, object], *, repository_root: Path
) -> str:
    """Admit only the sealed 23-card localization core after full revalidation."""
    try:
        validate_typed_commutative_algebra_localization_manifest(
            payload, repository_root=repository_root
        )
    except TypedCommutativeAlgebraLocalizationManifestError as exc:
        raise TypedLocalCatalogError(
            "commutative-algebra localization manifest is invalid"
        ) from exc
    if (
        payload.get("status") != "sealed_local_authoring_revision_not_admitted"
        or payload.get("admitted_card_count") != 23
        or payload.get("hard_reject_count") != 6
    ):
        raise TypedLocalCatalogError(
            "commutative-algebra localization manifest sealed status is invalid"
        )
    return _required_string(
        payload.get("manifest_payload_sha256"),
        "commutative-algebra localization manifest_payload_sha256",
    )


def _validate_ode_manifest(payload: Mapping[str, object], *, repository_root: Path) -> str:
    """Admit only the fully sealed, profile-validated ten-card ODE revision."""
    try:
        validate_typed_ode_manifest(payload, repository_root=repository_root)
    except TypedOdeManifestError as exc:
        raise TypedLocalCatalogError("typed ODE manifest is invalid") from exc
    if (
        payload.get("status") != "sealed_local_authoring_revision_not_admitted"
        or payload.get("admitted_card_count") != 10
        or payload.get("excluded_source_card_count") != 0
    ):
        raise TypedLocalCatalogError("typed ODE manifest sealed status is invalid")
    digest = _mapping(payload.get("manifest_digest"), "typed ODE manifest_digest")
    _require_exact_keys(digest, {"algorithm", "input", "sha256"}, "typed ODE manifest_digest")
    return _required_string(digest.get("sha256"), "typed ODE manifest_digest.sha256")


def _validate_sealed_local_status(
    payload: Mapping[str, object], *, scope: str, revision: str, label: str
) -> None:
    if payload["status"] != "sealed_local_authoring_revision_not_admitted":
        raise TypedLocalCatalogError(f"{label} manifest status is invalid")
    seal = _mapping(payload["seal"], "seal")
    _require_exact_keys(seal, {"scope", "admission", "revision"}, f"{label} seal")
    if (
        seal["scope"] != scope
        or seal["admission"]
        != "not admitted to the generic DB, seed, embedding index, or PFI package"
        or seal["revision"] != revision
    ):
        raise TypedLocalCatalogError(f"{label} manifest seal is invalid")


def _validate_exclusion_records(records: list[object], *, label: str) -> None:
    identifiers: set[str] = set()
    for index, raw in enumerate(records, start=1):
        record = _mapping(raw, f"{label}[{index}]")
        identifier = _required_string(record.get("id"), f"{label}[{index}].id")
        if identifier in identifiers:
            raise TypedLocalCatalogError(f"{label} repeat an id")
        identifiers.add(identifier)
        _require_nonempty_strings(record, f"{label}[{index}]")


def _profile_binding(spec: _ProfileSpec, *, repository_root: Path) -> TypedProfileBinding:
    registry_bytes = _read_relative(repository_root, spec.registry_path)
    validator_bytes = _read_relative(repository_root, spec.validator_module_path)
    values = {
        "profile_id": spec.profile_id,
        "validator_import": spec.validator_import,
        "validator_module_path": spec.validator_module_path,
        "validator_module_sha256": _sha256(validator_bytes),
        "registry_path": spec.registry_path,
        "registry_sha256": _sha256(registry_bytes),
        "openmath_canonicalizer_version": TYPED_OPENMATH_CANONICALIZER_VERSION,
    }
    return TypedProfileBinding(
        **values,
        binding_sha256=_sha256(rfc8785.dumps(values)),
    )


@dataclass(frozen=True, slots=True)
class _NormalizedCard:
    card_id: str
    canonical_statement: str
    canonical_openmath_xml: str
    canonical_openmath_xml_sha256: str
    proof_strategy: str
    sketch_steps: tuple[str, ...]


def _validate_matrix_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "authoring_status",
            "canonical_statement",
            "openmath_xml",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "proof_strategy",
            "sketch_steps",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        f"matrix card {index}",
    )
    if card["authoring_status"] != "complete_xml_profile_semantics_verified_locally_not_admitted":
        raise TypedLocalCatalogError("matrix card authoring status is invalid")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)
    lean = _mapping(card["lean"], f"matrix card {index}.lean")
    _require_exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "lean")
    for value_key, digest_key in (("target", "target_sha256"), ("witness", "witness_sha256")):
        value = _required_string(lean[value_key], f"lean.{value_key}")
        _require_digest(
            value.encode("utf-8"), _required_string(lean[digest_key], f"lean.{digest_key}")
        )
    alignment = _mapping(
        card["statement_openmath_lean_alignment_review"],
        f"matrix card {index}.statement_openmath_lean_alignment_review",
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "matrix alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedLocalCatalogError("matrix card alignment status is invalid")
    for name, alignment_value in alignment.items():
        _required_string(alignment_value, f"matrix alignment.{name}")
    return normalized


def _validate_typed_math_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "canonical_statement",
            "openmath_xml",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "proof_strategy",
            "sketch_steps",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        f"typed-math card {index}",
    )
    _required_string(card["domain"], f"typed-math card {index}.domain")
    _required_string(card["difficulty"], f"typed-math card {index}.difficulty")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)
    lean = _mapping(card["lean"], f"typed-math card {index}.lean")
    _require_exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "lean")
    for value_key, digest_key in (("target", "target_sha256"), ("witness", "witness_sha256")):
        value = _required_string(lean[value_key], f"lean.{value_key}")
        _require_digest(
            value.encode("utf-8"), _required_string(lean[digest_key], f"lean.{digest_key}")
        )
    alignment = _mapping(
        card["statement_openmath_lean_alignment_review"],
        f"typed-math card {index}.statement_openmath_lean_alignment_review",
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "typed-math alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedLocalCatalogError("typed-math card alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "typed-math alignment")
    return normalized


def _validate_real_analysis_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    expected = {
        "id",
        "canonical_statement",
        "openmath_xml",
        "signature_trace",
        "lean_target",
        "lean_witness",
        "source_witness_ids",
        "alignment",
        "openmath_xml_sha256",
        "canonical_openmath_xml",
        "canonical_openmath_xml_sha256",
        "canonical_statement_sha256",
        "lean_target_sha256",
        "lean_witness_sha256",
        "source_witness_sha256",
        "profile_validation_status",
        "admission_status",
        "proof_strategy",
        "sketch_steps",
    }
    missing = expected - set(card)
    extra = set(card) - expected
    if missing == {"proof_strategy", "sketch_steps"} and not extra:
        # The current proposal deliberately remains non-loadable until its
        # authoring revision includes explicit explanatory material.  Do this
        # after the enclosing manifest and its XML have been rechecked.
        _validate_real_analysis_card_evidence(card, spec=spec, index=index)
        raise TypedLocalCatalogError(
            "real-analysis proposal requires explicit proof_strategy and 4..10 sketch_steps"
        )
    if missing or extra:
        raise TypedLocalCatalogError("real-analysis card fields are invalid")
    _validate_real_analysis_card_evidence(card, spec=spec, index=index)
    if card["profile_validation_status"] != "validated_local_typed_real_analysis_v1_sealed":
        raise TypedLocalCatalogError("real-analysis card validation status is invalid")
    if (
        card["admission_status"]
        != "sealed-local-authoring-revision: not a DB Draft or a translation receipt"
    ):
        raise TypedLocalCatalogError("real-analysis card admission status is invalid")
    return _validate_common_card_fields(card, spec=spec, index=index)


def _validate_real_analysis_card_evidence(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> None:
    required = {
        "id",
        "canonical_statement",
        "openmath_xml",
        "signature_trace",
        "lean_target",
        "lean_witness",
        "source_witness_ids",
        "alignment",
        "openmath_xml_sha256",
        "canonical_openmath_xml",
        "canonical_openmath_xml_sha256",
        "canonical_statement_sha256",
        "lean_target_sha256",
        "lean_witness_sha256",
        "source_witness_sha256",
        "profile_validation_status",
        "admission_status",
    }
    if set(card) != required and set(card) != required | {"proof_strategy", "sketch_steps"}:
        raise TypedLocalCatalogError("real-analysis card evidence fields are invalid")
    for key in (
        "id",
        "canonical_statement",
        "openmath_xml",
        "lean_target",
        "lean_witness",
        "alignment",
    ):
        _required_string(card[key], f"real-analysis card {index}.{key}")
    trace = card["signature_trace"]
    witnesses = card["source_witness_ids"]
    if (
        not isinstance(trace, list)
        or not trace
        or not all(isinstance(value, str) and value.strip() for value in trace)
        or not isinstance(witnesses, list)
        or not witnesses
        or not all(isinstance(value, str) and value.strip() for value in witnesses)
    ):
        raise TypedLocalCatalogError("real-analysis card trace evidence is invalid")
    for value_key, digest_key in (
        ("openmath_xml", "openmath_xml_sha256"),
        ("canonical_statement", "canonical_statement_sha256"),
        ("lean_target", "lean_target_sha256"),
        ("lean_witness", "lean_witness_sha256"),
    ):
        value = _required_string(card[value_key], f"real-analysis card {index}.{value_key}")
        _require_digest(
            value.encode("utf-8"),
            _required_string(card[digest_key], f"real-analysis card {index}.{digest_key}"),
        )
    if card["source_witness_sha256"] != card["lean_witness_sha256"]:
        raise TypedLocalCatalogError(
            "real-analysis source witness digest is not bound to Lean witness"
        )
    _validate_common_xml_fields(card, spec=spec, index=index)


def _validate_multivariable_calculus_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int, repository_root: Path
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "canonical_statement",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "signature_trace",
            "lean_target",
            "lean_witness",
            "alignment",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "canonical_statement_sha256",
            "lean_target_sha256",
            "lean_witness_sha256",
            "source_witness_sha256",
            "profile_validation_status",
            "statement_openmath_lean_alignment_review",
        },
        f"multivariable-calculus card {index}",
    )
    if (
        card["profile_validation_status"]
        != "validated_local_typed_multivariable_calculus_v1_sealed"
    ):
        raise TypedLocalCatalogError("multivariable-calculus card sealed status is invalid")
    trace = _require_nonempty_string_list(
        card["signature_trace"], "multivariable-calculus signature trace"
    )
    if len(trace) < 2:
        raise TypedLocalCatalogError("multivariable-calculus signature trace is incomplete")
    for value_key, digest_key in (
        ("openmath_xml", "openmath_xml_sha256"),
        ("canonical_statement", "canonical_statement_sha256"),
        ("lean_target", "lean_target_sha256"),
        ("lean_witness", "lean_witness_sha256"),
    ):
        value = _required_string(
            card[value_key], f"multivariable-calculus card {index}.{value_key}"
        )
        _require_digest(
            value.encode("utf-8"),
            _required_string(card[digest_key], f"multivariable-calculus card {index}.{digest_key}"),
        )
    if card["source_witness_sha256"] != card["lean_witness_sha256"]:
        raise TypedLocalCatalogError(
            "multivariable-calculus source witness digest is not bound to Lean witness"
        )
    alignment = _mapping(
        card["statement_openmath_lean_alignment_review"],
        f"multivariable-calculus card {index}.statement_openmath_lean_alignment_review",
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "multivariable-calculus alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedLocalCatalogError("multivariable-calculus card alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "multivariable-calculus alignment")
    _required_string(card["alignment"], f"multivariable-calculus card {index}.alignment")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)
    witness = _required_string(card["lean_witness"], "multivariable-calculus Lean witness")
    bundle = _read_relative(
        repository_root, "docs/typed-multivariable-calculus-v1-authoring-witnesses.lean"
    ).decode("utf-8")
    if f"-- manifest card: {normalized.card_id}\n{witness}" not in bundle:
        raise TypedLocalCatalogError(
            "multivariable-calculus Lean witness is not bound to its sealed bundle"
        )
    return normalized


def _validate_finite_graph_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int, repository_root: Path
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "authoring_status",
            "canonical_statement",
            "canonical_statement_sha256",
            "openmath_xml",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "profile_c14n",
            "signature_trace",
            "signature_trace_sha256",
            "proof_strategy",
            "proof_strategy_sha256",
            "sketch_steps",
            "sketch_steps_sha256",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        f"finite-graph card {index}",
    )
    if card["authoring_status"] != "sealed_local_profile_validated_not_admitted":
        raise TypedLocalCatalogError("finite-graph card authoring status is invalid")
    _required_string(card["domain"], f"finite-graph card {index}.domain")
    _required_string(card["difficulty"], f"finite-graph card {index}.difficulty")
    statement = _required_string(
        card["canonical_statement"], f"finite-graph card {index}.statement"
    )
    _require_digest(
        statement.encode("utf-8"),
        _required_string(
            card["canonical_statement_sha256"], f"finite-graph card {index}.statement digest"
        ),
    )
    _validate_raw_xml_digest(card, index=index, label="finite-graph")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)
    profile_c14n = _mapping(card["profile_c14n"], f"finite-graph card {index}.profile_c14n")
    _require_exact_keys(
        profile_c14n, {"algorithm", "scope", "xml", "sha256"}, "finite-graph profile C14N"
    )
    if (
        profile_c14n["algorithm"] != TYPED_OPENMATH_CANONICALIZER_VERSION
        or profile_c14n["scope"]
        != "typed-finite-graph-v1 validation followed by profile-separated canonicalization"
        or profile_c14n["xml"] != normalized.canonical_openmath_xml
        or profile_c14n["sha256"] != normalized.canonical_openmath_xml_sha256
    ):
        raise TypedLocalCatalogError("finite-graph card profile C14N evidence is invalid")
    trace = _require_nonempty_string_list(card["signature_trace"], "finite-graph signature trace")
    _require_digest(
        rfc8785.dumps(cast(Any, trace)),
        _required_string(card["signature_trace_sha256"], "finite-graph signature trace digest"),
    )
    _require_digest(
        normalized.proof_strategy.encode("utf-8"),
        _required_string(card["proof_strategy_sha256"], "finite-graph strategy digest"),
    )
    _require_digest(
        rfc8785.dumps(cast(Any, list(normalized.sketch_steps))),
        _required_string(card["sketch_steps_sha256"], "finite-graph sketch digest"),
    )
    lean = _mapping(card["lean"], f"finite-graph card {index}.lean")
    _require_exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "lean")
    target = _required_string(lean["target"], "finite-graph Lean target")
    witness = _required_string(lean["witness"], "finite-graph Lean witness")
    _require_digest(
        target.encode("utf-8"), _required_string(lean["target_sha256"], "Lean target digest")
    )
    _require_digest(
        witness.encode("utf-8"), _required_string(lean["witness_sha256"], "Lean witness digest")
    )
    _require_witness_membership(
        card_id=normalized.card_id,
        target=target,
        witness=witness,
        bundle_path="docs/typed-finite-graph-v1-authoring-witnesses.proposal.lean",
        repository_root=repository_root,
        label="finite-graph",
        witness_includes_target=True,
    )
    alignment = _mapping(
        card["statement_openmath_lean_alignment_review"],
        f"finite-graph card {index}.alignment",
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "finite-graph alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedLocalCatalogError("finite-graph alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "finite-graph alignment")
    return normalized


def _validate_geometry_complex_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int, repository_root: Path
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "canonical_statement",
            "openmath_xml",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "signature_trace",
            "signature_trace_sha256",
            "proof_strategy",
            "proof_strategy_sha256",
            "sketch_steps",
            "sketch_steps_sha256",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        f"vector/complex card {index}",
    )
    _required_string(card["domain"], f"vector/complex card {index}.domain")
    _required_string(card["difficulty"], f"vector/complex card {index}.difficulty")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)

    trace = _mapping(card["signature_trace"], f"vector/complex card {index}.signature_trace")
    _require_exact_keys(trace, {"result_sort", "symbols"}, "vector/complex signature trace")
    if trace["result_sort"] != "Prop":
        raise TypedLocalCatalogError("vector/complex signature trace result sort is invalid")
    _require_nonempty_string_list(trace["symbols"], "vector/complex signature trace symbols")
    _require_digest(
        rfc8785.dumps(cast(Any, trace)),
        _required_string(card["signature_trace_sha256"], "vector/complex signature trace digest"),
    )
    _require_digest(
        normalized.proof_strategy.encode("utf-8"),
        _required_string(card["proof_strategy_sha256"], "vector/complex strategy digest"),
    )
    _require_digest(
        rfc8785.dumps(cast(Any, list(normalized.sketch_steps))),
        _required_string(card["sketch_steps_sha256"], "vector/complex sketch digest"),
    )

    lean = _mapping(card["lean"], f"vector/complex card {index}.lean")
    _require_exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "lean")
    target = _required_string(lean["target"], "vector/complex Lean target")
    witness = _required_string(lean["witness"], "vector/complex Lean witness")
    _require_digest(
        target.encode("utf-8"), _required_string(lean["target_sha256"], "Lean target digest")
    )
    _require_digest(
        witness.encode("utf-8"), _required_string(lean["witness_sha256"], "Lean witness digest")
    )
    _require_witness_membership(
        card_id=normalized.card_id,
        target=target,
        witness=witness,
        bundle_path=(
            "pals-agent/testdata/typed-geometry-complex-v1/vector-complex-phase-a-witnesses.lean"
        ),
        repository_root=repository_root,
        label="vector/complex",
        witness_includes_target=True,
    )
    alignment = _mapping(
        card["statement_openmath_lean_alignment_review"],
        f"vector/complex card {index}.alignment",
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "vector/complex alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedLocalCatalogError("vector/complex alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "vector/complex alignment")
    return normalized


def _validate_plane_geometry_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int, repository_root: Path
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "canonical_statement",
            "openmath_xml",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "signature_trace",
            "signature_trace_sha256",
            "proof_strategy",
            "proof_strategy_sha256",
            "sketch_steps",
            "sketch_steps_sha256",
            "lean",
            "statement_openmath_lean_alignment_review",
        },
        f"plane-geometry card {index}",
    )
    _required_string(card["domain"], f"plane-geometry card {index}.domain")
    _required_string(card["difficulty"], f"plane-geometry card {index}.difficulty")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)

    trace = _mapping(card["signature_trace"], f"plane-geometry card {index}.signature_trace")
    _require_exact_keys(trace, {"result_sort", "symbols"}, "plane-geometry signature trace")
    if trace["result_sort"] != "Prop":
        raise TypedLocalCatalogError("plane-geometry signature trace result sort is invalid")
    _require_nonempty_string_list(trace["symbols"], "plane-geometry signature trace symbols")
    _require_digest(
        rfc8785.dumps(cast(Any, trace)),
        _required_string(card["signature_trace_sha256"], "plane-geometry signature trace digest"),
    )
    _require_digest(
        normalized.proof_strategy.encode("utf-8"),
        _required_string(card["proof_strategy_sha256"], "plane-geometry strategy digest"),
    )
    _require_digest(
        rfc8785.dumps(cast(Any, list(normalized.sketch_steps))),
        _required_string(card["sketch_steps_sha256"], "plane-geometry sketch digest"),
    )

    lean = _mapping(card["lean"], f"plane-geometry card {index}.lean")
    _require_exact_keys(lean, {"target", "target_sha256", "witness", "witness_sha256"}, "lean")
    target = _required_string(lean["target"], "plane-geometry Lean target")
    witness = _required_string(lean["witness"], "plane-geometry Lean witness")
    _require_digest(
        target.encode("utf-8"), _required_string(lean["target_sha256"], "Lean target digest")
    )
    _require_digest(
        witness.encode("utf-8"), _required_string(lean["witness_sha256"], "Lean witness digest")
    )
    _require_witness_membership(
        card_id=normalized.card_id,
        target=target,
        witness=witness,
        bundle_path="pals-agent/testdata/typed-plane-geometry-v1/plane-geometry-witnesses.lean",
        repository_root=repository_root,
        label="plane-geometry",
        witness_includes_target=True,
    )
    alignment = _mapping(
        card["statement_openmath_lean_alignment_review"],
        f"plane-geometry card {index}.alignment",
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "plane-geometry alignment",
    )
    if alignment["status"] != "reviewed_by_local_authoring_agent_not_admitted":
        raise TypedLocalCatalogError("plane-geometry alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "plane-geometry alignment")
    return normalized


def _validate_probability_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int, repository_root: Path
) -> _NormalizedCard:
    _require_exact_keys(
        card,
        {
            "id",
            "canonical_statement",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "signature_trace",
            "lean_target",
            "lean_witness",
            "alignment",
            "conventions",
            "source_candidate_id",
            "openmath_profile",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "canonical_statement_sha256",
            "lean_target_sha256",
            "lean_witness_sha256",
            "compiler_receipt_status",
            "profile_validation_status",
            "admission_status",
            "embedding_namespace_preimage",
        },
        f"probability card {index}",
    )
    if (
        card["source_candidate_id"] != card["id"]
        or card["openmath_profile"] != _PROBABILITY_SPEC.profile_id
        or card["compiler_receipt_status"] != "verified"
        or card["profile_validation_status"] != "validated_local_typed_probability_v1_sealed"
        or card["admission_status"]
        != "sealed-local-authoring-revision: not a DB Draft or a translation receipt"
    ):
        raise TypedLocalCatalogError("probability card sealed status is invalid")
    _require_digest(
        _required_string(card["canonical_statement"], f"probability card {index}.statement").encode(
            "utf-8"
        ),
        _required_string(
            card["canonical_statement_sha256"], f"probability card {index}.statement digest"
        ),
    )
    _validate_raw_xml_digest(card, index=index, label="probability")
    normalized = _validate_common_card_fields(card, spec=spec, index=index)
    trace = _require_nonempty_string_list(card["signature_trace"], "probability signature trace")
    del trace  # The sealed manifest digest binds the exact trace bytes.
    _required_string(card["alignment"], f"probability card {index}.alignment")
    _require_nonempty_string_mapping(
        _mapping(card["conventions"], f"probability card {index}.conventions"),
        "probability conventions",
    )
    target = _required_string(card["lean_target"], f"probability card {index}.Lean target")
    witness = _required_string(card["lean_witness"], f"probability card {index}.Lean witness")
    _require_digest(
        target.encode("utf-8"), _required_string(card["lean_target_sha256"], "Lean target digest")
    )
    _require_digest(
        witness.encode("utf-8"),
        _required_string(card["lean_witness_sha256"], "Lean witness digest"),
    )
    _require_witness_membership(
        card_id=normalized.card_id,
        target=target,
        witness=witness,
        bundle_path="docs/typed-probability-v1-authoring-witnesses.lean",
        repository_root=repository_root,
        label="probability",
        witness_includes_target=False,
    )
    if card["embedding_namespace_preimage"] != (
        f"{_PROBABILITY_SPEC.profile_id}||{normalized.canonical_openmath_xml}"
    ):
        raise TypedLocalCatalogError("probability embedding namespace preimage is invalid")
    return normalized


def _validate_number_theory_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    """Keep the catalog-facing fields aligned with the sealed profile evidence."""
    _require_exact_keys(
        card,
        {
            "id",
            "canonical_statement",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "canonical_statement_sha256",
            "lean_target",
            "lean_target_sha256",
            "lean_witness",
            "lean_witness_sha256",
            "openmath_profile",
            "profile_validation_status",
            "compiler_receipt_status",
            "admission_status",
            "alignment",
        },
        f"number-theory card {index}",
    )
    if (
        card["openmath_profile"] != _NUMBER_THEORY_SPEC.profile_id
        or card["profile_validation_status"] != "validated_local_typed_number_theory_v1_sealed"
        or card["compiler_receipt_status"] != "verified"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedLocalCatalogError("number-theory card sealed status is invalid")
    _validate_raw_xml_digest(card, index=index, label="number-theory")
    statement = _required_string(
        card["canonical_statement"], f"number-theory card {index}.statement"
    )
    _require_digest(
        statement.encode("utf-8"),
        _required_string(
            card["canonical_statement_sha256"],
            f"number-theory card {index}.statement digest",
        ),
    )
    target = _required_string(card["lean_target"], f"number-theory card {index}.Lean target")
    witness = _required_string(card["lean_witness"], f"number-theory card {index}.Lean witness")
    _require_digest(
        target.encode("utf-8"),
        _required_string(card["lean_target_sha256"], "number-theory Lean target digest"),
    )
    _require_digest(
        witness.encode("utf-8"),
        _required_string(card["lean_witness_sha256"], "number-theory Lean witness digest"),
    )
    alignment = _mapping(card["alignment"], f"number-theory card {index}.alignment")
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "number-theory alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedLocalCatalogError("number-theory card alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "number-theory alignment")
    return _validate_common_card_fields(card, spec=spec, index=index)


def _validate_commutative_algebra_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    """Keep local catalog fields bound to the sealed ideal-lattice evidence."""
    _require_exact_keys(
        card,
        {
            "id",
            "canonical_statement",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "canonical_statement_sha256",
            "lean_target",
            "lean_target_sha256",
            "lean_witness",
            "lean_witness_sha256",
            "openmath_profile",
            "profile_validation_status",
            "compiler_receipt_status",
            "admission_status",
            "alignment",
        },
        f"commutative-algebra card {index}",
    )
    if (
        card["openmath_profile"] != _COMMUTATIVE_ALGEBRA_SPEC.profile_id
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_v1_sealed"
        or card["compiler_receipt_status"] != "verified"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedLocalCatalogError("commutative-algebra card sealed status is invalid")
    _validate_raw_xml_digest(card, index=index, label="commutative-algebra")
    statement = _required_string(
        card["canonical_statement"], f"commutative-algebra card {index}.statement"
    )
    _require_digest(
        statement.encode("utf-8"),
        _required_string(
            card["canonical_statement_sha256"],
            f"commutative-algebra card {index}.statement digest",
        ),
    )
    target = _required_string(card["lean_target"], f"commutative-algebra card {index}.Lean target")
    witness = _required_string(
        card["lean_witness"], f"commutative-algebra card {index}.Lean witness"
    )
    _require_digest(
        target.encode("utf-8"),
        _required_string(card["lean_target_sha256"], "commutative-algebra Lean target digest"),
    )
    _require_digest(
        witness.encode("utf-8"),
        _required_string(card["lean_witness_sha256"], "commutative-algebra Lean witness digest"),
    )
    alignment = _mapping(card["alignment"], f"commutative-algebra card {index}.alignment")
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "commutative-algebra alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedLocalCatalogError("commutative-algebra card alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "commutative-algebra alignment")
    return _validate_common_card_fields(card, spec=spec, index=index)


def _validate_commutative_algebra_modules_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    """Rebind CA-2 cards to actual validator, C14N, strategy, and Lean evidence."""
    _require_exact_keys(
        card,
        {
            "id",
            "canonical_statement",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "canonical_statement_sha256",
            "lean_target",
            "lean_target_sha256",
            "lean_witness",
            "lean_witness_sha256",
            "openmath_profile",
            "profile_validation_status",
            "compiler_receipt_status",
            "admission_status",
            "alignment",
        },
        f"commutative-algebra modules card {index}",
    )
    if (
        card["openmath_profile"] != _COMMUTATIVE_ALGEBRA_MODULES_SPEC.profile_id
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_modules_v1_sealed"
        or card["compiler_receipt_status"] != "verified"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedLocalCatalogError("commutative-algebra modules card status is invalid")
    _validate_raw_xml_digest(card, index=index, label="commutative-algebra modules")
    statement = _required_string(
        card["canonical_statement"], f"commutative-algebra modules card {index}.statement"
    )
    _require_digest(
        statement.encode("utf-8"),
        _required_string(
            card["canonical_statement_sha256"],
            f"commutative-algebra modules card {index}.statement digest",
        ),
    )
    target = _required_string(
        card["lean_target"], f"commutative-algebra modules card {index}.Lean target"
    )
    witness = _required_string(
        card["lean_witness"], f"commutative-algebra modules card {index}.Lean witness"
    )
    _require_digest(
        target.encode("utf-8"),
        _required_string(
            card["lean_target_sha256"], "commutative-algebra modules Lean target digest"
        ),
    )
    _require_digest(
        witness.encode("utf-8"),
        _required_string(
            card["lean_witness_sha256"], "commutative-algebra modules Lean witness digest"
        ),
    )
    alignment = _mapping(card["alignment"], f"commutative-algebra modules card {index}.alignment")
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "commutative-algebra modules alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedLocalCatalogError("commutative-algebra modules alignment status is invalid")
    _require_nonempty_string_mapping(alignment, "commutative-algebra modules alignment")
    return _validate_common_card_fields(card, spec=spec, index=index)


def _validate_commutative_algebra_localization_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    """Keep catalog rows bound to the carrier-safe localization evidence."""
    _require_exact_keys(
        card,
        {
            "id",
            "domain",
            "difficulty",
            "canonical_statement",
            "canonical_statement_sha256",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "lean_target",
            "lean_target_sha256",
            "lean_witness",
            "lean_witness_sha256",
            "openmath_profile",
            "profile_validation_status",
            "compiler_receipt_status",
            "admission_status",
            "alignment",
        },
        f"commutative-algebra localization card {index}",
    )
    if (
        card["domain"] != "commutative_algebra.localization"
        or card["difficulty"] != "undergraduate_year_2"
        or card["openmath_profile"] != _COMMUTATIVE_ALGEBRA_LOCALIZATION_SPEC.profile_id
        or card["profile_validation_status"]
        != "validated_local_typed_commutative_algebra_localization_v1_sealed"
        or card["compiler_receipt_status"] != "verified_local_pinned_workspace"
        or card["admission_status"]
        != (
            "sealed-local-authoring-revision: not a DB Draft or an OpenMath-to-Lean "
            "translation receipt"
        )
    ):
        raise TypedLocalCatalogError("commutative-algebra localization card status is invalid")
    _validate_raw_xml_digest(card, index=index, label="commutative-algebra localization")
    statement = _required_string(
        card["canonical_statement"], f"commutative-algebra localization card {index}.statement"
    )
    _require_digest(
        statement.encode("utf-8"),
        _required_string(
            card["canonical_statement_sha256"],
            f"commutative-algebra localization card {index}.statement digest",
        ),
    )
    target = _required_string(
        card["lean_target"], f"commutative-algebra localization card {index}.Lean target"
    )
    witness = _required_string(
        card["lean_witness"],
        f"commutative-algebra localization card {index}.Lean witness",
    )
    _require_digest(
        target.encode("utf-8"),
        _required_string(
            card["lean_target_sha256"],
            "commutative-algebra localization Lean target digest",
        ),
    )
    _require_digest(
        witness.encode("utf-8"),
        _required_string(
            card["lean_witness_sha256"],
            "commutative-algebra localization Lean witness digest",
        ),
    )
    alignment = _mapping(
        card["alignment"], f"commutative-algebra localization card {index}.alignment"
    )
    _require_exact_keys(
        alignment,
        {"status", "statement_to_openmath", "openmath_to_lean", "admission_gate"},
        "commutative-algebra localization alignment",
    )
    if alignment["status"] != "sealed_local_authoring_review_not_admitted":
        raise TypedLocalCatalogError("commutative-algebra localization alignment is invalid")
    _require_nonempty_string_mapping(alignment, "commutative-algebra localization alignment")
    return _validate_common_card_fields(card, spec=spec, index=index)


def _validate_ode_card(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int, repository_root: Path
) -> _NormalizedCard:
    """Recheck catalog-facing ODE evidence after the sealed manifest validation."""
    _require_exact_keys(
        card,
        {
            "id",
            "source_candidate_id",
            "source_candidate_statement_sha256",
            "openmath_profile",
            "domain",
            "level",
            "topic",
            "difficulty",
            "canonical_statement",
            "proof_strategy",
            "sketch_steps",
            "openmath_xml",
            "openmath_xml_sha256",
            "canonical_openmath_xml",
            "canonical_openmath_xml_sha256",
            "lean_target",
            "lean_target_sha256",
            "lean_witness",
            "lean_witness_sha256",
            "openmath_to_lean_alignment",
            "profile_validation_status",
            "compiler_receipt_status",
        },
        f"typed ODE card {index}",
    )
    if (
        card["source_candidate_id"] != card["id"]
        or card["openmath_profile"] != _ODE_SPEC.profile_id
        or card["domain"] != "ordinary_differential_equations"
        or card["level"] != "undergraduate_year_2"
        or card["profile_validation_status"] != "validated_local_typed_ode_v1_sealed"
        or card["compiler_receipt_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedLocalCatalogError("typed ODE card sealed status is invalid")
    _validate_raw_xml_digest(card, index=index, label="typed ODE")
    target = _required_string(card["lean_target"], f"typed ODE card {index}.Lean target")
    witness = _required_string(card["lean_witness"], f"typed ODE card {index}.Lean witness")
    _require_digest(
        target.encode("utf-8"),
        _required_string(card["lean_target_sha256"], "typed ODE Lean target digest"),
    )
    _require_digest(
        witness.encode("utf-8"),
        _required_string(card["lean_witness_sha256"], "typed ODE Lean witness digest"),
    )
    _required_string(
        card["source_candidate_statement_sha256"],
        f"typed ODE card {index}.source candidate statement digest",
    )
    _required_string(
        card["openmath_to_lean_alignment"],
        f"typed ODE card {index}.OpenMath-to-Lean alignment",
    )
    normalized = _validate_common_card_fields(card, spec=spec, index=index)
    _validate_ode_witness_membership(
        card_id=normalized.card_id,
        target=target,
        witness=witness,
        repository_root=repository_root,
    )
    return normalized


def _validate_common_card_fields(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> _NormalizedCard:
    card_id = _required_string(card["id"], f"typed card {index}.id")
    statement = _required_string(
        card["canonical_statement"], f"typed card {index}.canonical_statement"
    )
    canonical_xml, canonical_xml_digest = _validate_common_xml_fields(card, spec=spec, index=index)
    strategy = _required_string(card["proof_strategy"], f"typed card {index}.proof_strategy")
    steps = card["sketch_steps"]
    if (
        not isinstance(steps, list)
        or not 4 <= len(steps) <= 10
        or any(not isinstance(step, str) or not step.strip() for step in steps)
    ):
        raise TypedLocalCatalogError("typed card sketch_steps must contain 4..10 non-empty steps")
    return _NormalizedCard(
        card_id=card_id,
        canonical_statement=statement,
        canonical_openmath_xml=canonical_xml,
        canonical_openmath_xml_sha256=canonical_xml_digest,
        proof_strategy=strategy,
        sketch_steps=tuple(steps),
    )


def _validate_common_xml_fields(
    card: Mapping[str, object], *, spec: _ProfileSpec, index: int
) -> tuple[str, str]:
    raw_xml = _required_string(card["openmath_xml"], f"typed card {index}.openmath_xml")
    canonical_xml = _required_string(
        card["canonical_openmath_xml"], f"typed card {index}.canonical_openmath_xml"
    )
    try:
        recomputed = spec.canonicalize(raw_xml)
        spec.validate_canonical(canonical_xml)
    except ValueError as exc:
        raise TypedLocalCatalogError(
            "typed card does not pass its actual profile validator"
        ) from exc
    if recomputed != canonical_xml:
        raise TypedLocalCatalogError("typed card canonical OpenMath does not match source XML")
    digest = _required_string(
        card["canonical_openmath_xml_sha256"],
        f"typed card {index}.canonical_openmath_xml_sha256",
    )
    _require_digest(canonical_xml.encode("utf-8"), digest)
    return canonical_xml, digest


def _validate_lean_toolchain(toolchain: Mapping[str, object], *, repository_root: Path) -> None:
    _require_exact_keys(toolchain, {"path", "value", "sha256", "digest_input"}, "lean_toolchain")
    if toolchain["digest_input"] != "exact UTF-8 bytes of the named lean-toolchain file":
        raise TypedLocalCatalogError("Lean toolchain digest input is invalid")
    source = _read_relative(
        repository_root, _required_string(toolchain["path"], "lean_toolchain.path")
    )
    if _required_string(toolchain["value"], "lean_toolchain.value") != source.decode(
        "utf-8"
    ).rstrip("\n"):
        raise TypedLocalCatalogError("Lean toolchain value is invalid")
    _require_digest(source, _required_string(toolchain["sha256"], "lean_toolchain.sha256"))


def _validate_matrix_witness_bundle(bundle: Mapping[str, object], *, repository_root: Path) -> None:
    _require_exact_keys(
        bundle,
        {"path", "sha256", "digest_input", "verification_command", "verification_status", "scope"},
        "lean_witness_bundle",
    )
    if (
        bundle["digest_input"]
        != "exact UTF-8 bytes of the named Lean file, including import and final newline"
        or bundle["verification_status"] != "verified_local_pinned_workspace"
    ):
        raise TypedLocalCatalogError("matrix Lean witness bundle status is invalid")
    for key in ("verification_command", "scope"):
        _required_string(bundle[key], f"lean_witness_bundle.{key}")
    _require_digest(
        _read_relative(
            repository_root, _required_string(bundle["path"], "lean_witness_bundle.path")
        ),
        _required_string(bundle["sha256"], "lean_witness_bundle.sha256"),
    )


def _normalize_embedding(vector: Sequence[float], *, index: int) -> tuple[float, ...]:
    if len(vector) != _EXPECTED_EMBEDDING_DIMENSION:
        raise TypedLocalCatalogError(f"typed embedding {index} has the wrong dimension")
    normalized: list[float] = []
    for value in vector:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            raise TypedLocalCatalogError(f"typed embedding {index} contains a non-finite value")
        normalized.append(float(value))
    if not any(value != 0.0 for value in normalized):
        raise TypedLocalCatalogError(f"typed embedding {index} has zero norm")
    return tuple(normalized)


def _read_relative(root: Path, relative_path: str) -> bytes:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TypedLocalCatalogError(
            "typed catalog artifact path escapes the repository root"
        ) from exc
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise TypedLocalCatalogError("typed catalog artifact cannot be read") from exc


def _profile_spec(profile_id: str, schema_version: str) -> _ProfileSpec:
    if profile_id == _TYPED_MATH_SPEC.profile_id:
        spec = _TYPED_MATH_SPEC
    elif profile_id == _MATRIX_SPEC.profile_id:
        spec = _MATRIX_SPEC
    elif profile_id == _REAL_ANALYSIS_SPEC.profile_id:
        if schema_version == _REAL_ANALYSIS_SPEC.schema_version:
            return _REAL_ANALYSIS_SPEC
        if schema_version == _REAL_ANALYSIS_EXPANSION_SPEC.schema_version:
            return _REAL_ANALYSIS_EXPANSION_SPEC
        raise TypedLocalCatalogError(
            "typed catalog manifest schema/profile combination is unsupported"
        )
    elif profile_id == _MULTIVARIABLE_CALCULUS_SPEC.profile_id:
        spec = _MULTIVARIABLE_CALCULUS_SPEC
    elif profile_id == _FINITE_GRAPH_SPEC.profile_id:
        spec = _FINITE_GRAPH_SPEC
    elif profile_id == _GEOMETRY_COMPLEX_SPEC.profile_id:
        spec = _GEOMETRY_COMPLEX_SPEC
    elif profile_id == _PLANE_GEOMETRY_SPEC.profile_id:
        spec = _PLANE_GEOMETRY_SPEC
    elif profile_id == _PROBABILITY_SPEC.profile_id:
        spec = _PROBABILITY_SPEC
    elif profile_id == _NUMBER_THEORY_SPEC.profile_id:
        spec = _NUMBER_THEORY_SPEC
    elif profile_id == _COMMUTATIVE_ALGEBRA_SPEC.profile_id:
        spec = _COMMUTATIVE_ALGEBRA_SPEC
    elif profile_id == _COMMUTATIVE_ALGEBRA_MODULES_SPEC.profile_id:
        spec = _COMMUTATIVE_ALGEBRA_MODULES_SPEC
    elif profile_id == _COMMUTATIVE_ALGEBRA_LOCALIZATION_SPEC.profile_id:
        spec = _COMMUTATIVE_ALGEBRA_LOCALIZATION_SPEC
    elif profile_id == _COMMUTATIVE_ALGEBRA_INTEGRAL_SPEC.profile_id:
        spec = _COMMUTATIVE_ALGEBRA_INTEGRAL_SPEC
    elif profile_id == _COMMUTATIVE_ALGEBRA_DECOMPOSITION_SPEC.profile_id:
        spec = _COMMUTATIVE_ALGEBRA_DECOMPOSITION_SPEC
    elif profile_id == _COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_SPEC.profile_id:
        spec = _COMMUTATIVE_ALGEBRA_CHAIN_DIMENSION_SPEC
    elif profile_id == _ODE_SPEC.profile_id:
        spec = _ODE_SPEC
    else:
        raise TypedLocalCatalogError("typed catalog profile is unsupported")
    if schema_version != spec.schema_version:
        raise TypedLocalCatalogError(
            "typed catalog manifest schema/profile combination is unsupported"
        )
    return spec


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypedLocalCatalogError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TypedLocalCatalogError(f"{label} has unexpected fields")


def _require_nonempty_strings(value: Mapping[str, object], label: str) -> None:
    if any(not isinstance(item, str) or not item.strip() for item in value.values()):
        raise TypedLocalCatalogError(f"{label} must contain only non-empty strings")


def _require_nonempty_string_mapping(value: Mapping[str, object], label: str) -> None:
    if not value:
        raise TypedLocalCatalogError(f"{label} must not be empty")
    _require_nonempty_strings(value, label)


def _require_nonempty_string_list(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise TypedLocalCatalogError(f"{label} must be a non-empty list of strings")
    return cast(list[str], value)


def _validate_raw_xml_digest(card: Mapping[str, object], *, index: int, label: str) -> None:
    raw_xml = _required_string(card["openmath_xml"], f"{label} card {index}.openmath_xml")
    _require_digest(
        raw_xml.encode("utf-8"),
        _required_string(card["openmath_xml_sha256"], f"{label} card {index}.openmath_xml_sha256"),
    )


def _require_witness_membership(
    *,
    card_id: str,
    target: str,
    witness: str,
    bundle_path: str,
    repository_root: Path,
    label: str,
    witness_includes_target: bool,
) -> None:
    bundle = _read_relative(repository_root, bundle_path).decode("utf-8")
    if witness_includes_target:
        if target not in witness:
            raise TypedLocalCatalogError(f"{label} Lean witness does not state its target")
        marker = f"-- manifest card: {card_id}\n{witness.rstrip()}"
    else:
        marker = f"-- manifest card: {card_id}\n{target} := {witness.rstrip()}"
    if marker not in bundle:
        raise TypedLocalCatalogError(f"{label} Lean witness is not bound to its sealed bundle")


def _validate_ode_witness_membership(
    *, card_id: str, target: str, witness: str, repository_root: Path
) -> None:
    """Bind a target/proof pair to exactly its marked ODE Lean example."""
    bundle = _read_relative(repository_root, "docs/typed-ode-v1-authoring-witnesses.lean").decode(
        "utf-8"
    )
    marker = f"-- manifest card: {card_id}\n"
    start = bundle.find(marker)
    if start < 0:
        raise TypedLocalCatalogError("typed ODE Lean witness marker is missing")
    next_marker = bundle.find("-- manifest card: ", start + len(marker))
    section = bundle[start : len(bundle) if next_marker < 0 else next_marker]
    if f"{target} := {witness.rstrip()}" not in section:
        raise TypedLocalCatalogError("typed ODE Lean witness is not bound to its sealed bundle")


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypedLocalCatalogError(f"{label} must be a non-empty string")
    return value


def _require_digest(data: bytes, expected: str) -> None:
    if expected != _sha256(data):
        raise TypedLocalCatalogError("typed catalog digest does not match")


def _sha256(data: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _csv_rows(rows: Sequence[Sequence[str]]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def _pgvector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(format(value, ".8f") for value in values) + "]"
