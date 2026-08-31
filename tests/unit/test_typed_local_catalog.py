from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
import rfc8785

from pals_agent.typed_local_catalog import (
    TYPED_CATALOG_SCHEMA,
    TypedEmbeddingBinding,
    TypedLocalCatalogError,
    load_typed_local_catalog_manifest,
    prepare_typed_local_catalog_sql,
    typed_catalog_embedding_text,
    validate_typed_local_catalog_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MATRIX_MANIFEST = REPOSITORY_ROOT / "docs/typed-math-matrix-v1-authoring-manifest.proposal.json"
REAL_ANALYSIS_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-real-analysis-v1-authoring-manifest-proposal.json"
)
REAL_ANALYSIS_EXPANSION_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-real-analysis-v1-expansion-r2-sealed-manifest.proposal.json"
)
MULTIVARIABLE_CALCULUS_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-multivariable-calculus-v1-sealed-manifest.proposal.json"
)
FINITE_GRAPH_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-finite-graph-v1-authoring-manifest.proposal.json"
)
GEOMETRY_COMPLEX_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-geometry-complex-v1-authoring-manifest.proposal.json"
)
PLANE_GEOMETRY_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-plane-geometry-v1-authoring-manifest.proposal.json"
)
PROBABILITY_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-probability-v1-authoring-manifest.proposal.json"
)
NUMBER_THEORY_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-number-theory-v1-authoring-manifest.proposal.json"
)
COMMUTATIVE_ALGEBRA_MANIFEST = (
    REPOSITORY_ROOT / "docs/typed-commutative-algebra-v1-authoring-manifest.proposal.json"
)
COMMUTATIVE_ALGEBRA_MODULES_MANIFEST = (
    REPOSITORY_ROOT
    / "docs/typed-commutative-algebra-modules-v1-sealed-manifest.proposal.json"
)
COMMUTATIVE_ALGEBRA_LOCALIZATION_MANIFEST = (
    REPOSITORY_ROOT
    / "docs/typed-commutative-algebra-localization-v1-authoring-manifest.proposal.json"
)
ODE_MANIFEST = REPOSITORY_ROOT / "docs/typed-ode-v1-authoring-manifest.proposal.json"
GROUP_RING_MANIFEST = (
    REPOSITORY_ROOT
    / "pals-agent/testdata/typed-math-v1/group-ring-core-authoring-manifest.proposal.json"
)
TYPED_MATH_TYPICAL_MANIFEST = (
    REPOSITORY_ROOT / "pals-agent/testdata/typed-math-v1/"
    "group-ring-typical-theorems-authoring-manifest.proposal.json"
)
DDL = REPOSITORY_ROOT / "pals-scripts/typed-local-catalog-schema.sql"
PLANE_MANIFEST_ERROR = "plane-geometry authoring manifest is invalid"


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _reseal_matrix(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": (
            "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
        ),
        "sha256": _sha256(rfc8785.dumps(cast(Any, unsigned))),
    }


def _reseal_real_analysis(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = _sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _reseal_multivariable_calculus(payload: dict[str, object]) -> None:
    _reseal_real_analysis(payload)


def _reseal_graph(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": (
            "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
        ),
        "sha256": _sha256(rfc8785.dumps(cast(Any, unsigned))),
    }


def _reseal_geometry_complex(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": (
            "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
        ),
        "sha256": _sha256(rfc8785.dumps(cast(Any, unsigned))),
    }


def _reseal_probability(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = _sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _reseal_number_theory(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_payload_sha256")
    payload["manifest_payload_sha256"] = _sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _reseal_commutative_algebra(payload: dict[str, object]) -> None:
    _reseal_number_theory(payload)


def _reseal_commutative_algebra_localization(payload: dict[str, object]) -> None:
    _reseal_number_theory(payload)


def _reseal_ode(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": (
            "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
        ),
        "sha256": _sha256(rfc8785.dumps(cast(Any, unsigned))),
    }


def _vector() -> list[float]:
    return [1.0] + [0.0] * 383


def _binding() -> TypedEmbeddingBinding:
    return TypedEmbeddingBinding(
        provider="openai",
        model="text-embedding-3-small",
        dimension=384,
        endpoint="https://api.openai.com/v1",
        deployment="text-embedding-3-small",
        revision="openai-release-2024-01-25",
    )


def test_supported_manifests_revalidate_with_actual_profile_code() -> None:
    matrix = load_typed_local_catalog_manifest(MATRIX_MANIFEST, repository_root=REPOSITORY_ROOT)
    real_analysis = load_typed_local_catalog_manifest(
        REAL_ANALYSIS_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    real_analysis_expansion = load_typed_local_catalog_manifest(
        REAL_ANALYSIS_EXPANSION_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    multivariable_calculus = load_typed_local_catalog_manifest(
        MULTIVARIABLE_CALCULUS_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    graph = load_typed_local_catalog_manifest(
        FINITE_GRAPH_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    geometry_complex = load_typed_local_catalog_manifest(
        GEOMETRY_COMPLEX_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    plane_geometry = load_typed_local_catalog_manifest(
        PLANE_GEOMETRY_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    probability = load_typed_local_catalog_manifest(
        PROBABILITY_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    number_theory = load_typed_local_catalog_manifest(
        NUMBER_THEORY_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    commutative_algebra = load_typed_local_catalog_manifest(
        COMMUTATIVE_ALGEBRA_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    commutative_algebra_modules = load_typed_local_catalog_manifest(
        COMMUTATIVE_ALGEBRA_MODULES_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    commutative_algebra_localization = load_typed_local_catalog_manifest(
        COMMUTATIVE_ALGEBRA_LOCALIZATION_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    ode = load_typed_local_catalog_manifest(ODE_MANIFEST, repository_root=REPOSITORY_ROOT)
    typed_math = load_typed_local_catalog_manifest(
        TYPED_MATH_TYPICAL_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )

    assert matrix.profile.profile_id == "typed-math-matrix-v1"
    assert matrix.authoring_status == "not_admitted_requires_independent_project_review"
    assert len(matrix.cards) == 6
    assert real_analysis.profile.profile_id == "typed-real-analysis-v1"
    assert real_analysis.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(real_analysis.cards) == 4
    assert real_analysis_expansion.profile.profile_id == "typed-real-analysis-v1"
    assert (
        real_analysis_expansion.authoring_status == "sealed_local_authoring_revision_not_admitted"
    )
    assert len(real_analysis_expansion.cards) == 15
    assert real_analysis_expansion.profile == real_analysis.profile
    assert real_analysis_expansion.manifest_digest != real_analysis.manifest_digest
    assert {card.card_id for card in real_analysis.cards}.isdisjoint(
        card.card_id for card in real_analysis_expansion.cards
    )
    assert {card.canonical_openmath_xml for card in real_analysis.cards}.isdisjoint(
        card.canonical_openmath_xml for card in real_analysis_expansion.cards
    )
    assert multivariable_calculus.profile.profile_id == "typed-multivariable-calculus-v1"
    assert multivariable_calculus.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(multivariable_calculus.cards) == 6
    assert graph.profile.profile_id == "typed-finite-graph-v1"
    assert graph.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(graph.cards) == 5
    assert geometry_complex.profile.profile_id == "typed-geometry-complex-v1"
    assert geometry_complex.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(geometry_complex.cards) == 8
    assert plane_geometry.profile.profile_id == "typed-plane-geometry-v1"
    assert plane_geometry.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(plane_geometry.cards) == 5
    assert probability.profile.profile_id == "typed-probability-v1"
    assert probability.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(probability.cards) == 10
    assert number_theory.profile.profile_id == "typed-number-theory-v1"
    assert number_theory.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(number_theory.cards) == 12
    assert commutative_algebra.profile.profile_id == "typed-commutative-algebra-v1"
    assert commutative_algebra.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(commutative_algebra.cards) == 13
    assert commutative_algebra_modules.profile.profile_id == "typed-commutative-algebra-modules-v1"
    assert (
        commutative_algebra_modules.authoring_status
        == "sealed_local_authoring_revision_not_admitted"
    )
    assert len(commutative_algebra_modules.cards) == 24
    assert (
        commutative_algebra_localization.profile.profile_id
        == "typed-commutative-algebra-localization-v1"
    )
    assert (
        commutative_algebra_localization.authoring_status
        == "sealed_local_authoring_revision_not_admitted"
    )
    assert len(commutative_algebra_localization.cards) == 23
    assert ode.profile.profile_id == "typed-ode-v1"
    assert ode.authoring_status == "sealed_local_authoring_revision_not_admitted"
    assert len(ode.cards) == 10
    assert typed_math.profile.profile_id == "typed-math-v1"
    assert typed_math.authoring_status == "not_admitted_requires_independent_project_review"
    assert len(typed_math.cards) == 22
    catalogs = (
        matrix,
        real_analysis,
        real_analysis_expansion,
        multivariable_calculus,
        graph,
        geometry_complex,
        plane_geometry,
        probability,
        number_theory,
        commutative_algebra,
        commutative_algebra_modules,
        commutative_algebra_localization,
        ode,
        typed_math,
    )
    assert all(4 <= len(card.sketch_steps) <= 10 for catalog in catalogs for card in catalog.cards)
    assert all(card.proof_strategy for catalog in catalogs for card in catalog.cards)
    assert matrix.profile.registry_path.endswith("typed-math-matrix-v1-registry.json")
    assert real_analysis.profile.registry_path.endswith("typed-real-analysis-v1-registry.json")
    assert multivariable_calculus.profile.registry_path.endswith(
        "typed-multivariable-calculus-v1-registry.json"
    )
    assert graph.profile.registry_path.endswith("typed-finite-graph-v1-registry.json")
    assert geometry_complex.profile.registry_path.endswith(
        "typed-geometry-complex-v1-registry.json"
    )
    assert plane_geometry.profile.registry_path.endswith("typed-plane-geometry-v1-registry.json")
    assert probability.profile.registry_path.endswith("typed-probability-v1-registry.json")
    assert number_theory.profile.registry_path.endswith("typed-number-theory-v1-registry.json")
    assert commutative_algebra.profile.registry_path.endswith(
        "typed-commutative-algebra-v1-registry.json"
    )
    assert commutative_algebra_modules.profile.registry_path.endswith(
        "typed-commutative-algebra-modules-v1-registry.json"
    )
    assert commutative_algebra_localization.profile.registry_path.endswith(
        "typed-commutative-algebra-localization-v1-registry.json"
    )
    assert ode.profile.registry_path.endswith("typed-ode-v1-registry.json")
    assert typed_math.profile.registry_path.endswith("typed-math-v1-registry.json")


def test_manifest_digest_and_actual_canonical_xml_are_both_fail_closed() -> None:
    original = json.loads(MATRIX_MANIFEST.read_text(encoding="utf-8"))
    digest_tampered = copy.deepcopy(original)
    digest_tampered["admitted_candidate_cards"][0]["canonical_statement"] = "tampered"
    with pytest.raises(TypedLocalCatalogError, match="manifest digest"):
        validate_typed_local_catalog_manifest(digest_tampered, repository_root=REPOSITORY_ROOT)

    xml_tampered = copy.deepcopy(original)
    xml_tampered["admitted_candidate_cards"][0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal_matrix(xml_tampered)
    with pytest.raises(TypedLocalCatalogError, match="actual profile validator"):
        validate_typed_local_catalog_manifest(xml_tampered, repository_root=REPOSITORY_ROOT)


def test_real_analysis_requires_explicit_strategy_and_sketch_even_when_resealed() -> None:
    payload = json.loads(REAL_ANALYSIS_EXPANSION_MANIFEST.read_text(encoding="utf-8"))
    card = payload["cards"][0]
    card.pop("proof_strategy")
    card.pop("sketch_steps")
    _reseal_real_analysis(payload)

    with pytest.raises(TypedLocalCatalogError, match="requires explicit proof_strategy"):
        validate_typed_local_catalog_manifest(payload, repository_root=REPOSITORY_ROOT)


def test_real_analysis_base_snapshot_and_expansion_collisions_fail_closed() -> None:
    base = json.loads(REAL_ANALYSIS_MANIFEST.read_text(encoding="utf-8"))
    assert base["manifest_payload_sha256"] == (
        "sha256:eb7e2e6715678fd45efa30a01e583f4274969e90fca8b2164ad83154a25cb6a8"
    )
    tampered_base = copy.deepcopy(base)
    tampered_base["cards"][0]["canonical_statement"] = "must not reseal r1"
    _reseal_real_analysis(tampered_base)
    with pytest.raises(TypedLocalCatalogError, match="base snapshot digest is not immutable"):
        validate_typed_local_catalog_manifest(tampered_base, repository_root=REPOSITORY_ROOT)

    expansion = json.loads(REAL_ANALYSIS_EXPANSION_MANIFEST.read_text(encoding="utf-8"))
    id_collision = copy.deepcopy(expansion)
    id_collision["cards"][0]["id"] = base["cards"][0]["id"]
    _reseal_real_analysis(id_collision)
    with pytest.raises(TypedLocalCatalogError, match="card id collides with base snapshot"):
        validate_typed_local_catalog_manifest(id_collision, repository_root=REPOSITORY_ROOT)

    canonical_collision = copy.deepcopy(expansion)
    source = base["cards"][0]
    target = canonical_collision["cards"][0]
    for key in (
        "openmath_xml",
        "openmath_xml_sha256",
        "canonical_openmath_xml",
        "canonical_openmath_xml_sha256",
    ):
        target[key] = source[key]
    _reseal_real_analysis(canonical_collision)
    with pytest.raises(
        TypedLocalCatalogError, match="canonical OpenMath collides with base snapshot"
    ):
        validate_typed_local_catalog_manifest(canonical_collision, repository_root=REPOSITORY_ROOT)


def test_multivariable_calculus_rejects_resealed_binding_c14n_witness_and_collisions() -> None:
    stale_binding = json.loads(MULTIVARIABLE_CALCULUS_MANIFEST.read_text(encoding="utf-8"))
    profile = stale_binding["profile"]
    assert isinstance(profile, dict)
    profile["registry_digest"] = "sha256:" + "0" * 64
    _reseal_multivariable_calculus(stale_binding)
    with pytest.raises(TypedLocalCatalogError, match="digest does not match"):
        validate_typed_local_catalog_manifest(stale_binding, repository_root=REPOSITORY_ROOT)

    stale_c14n = json.loads(MULTIVARIABLE_CALCULUS_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_c14n["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal_multivariable_calculus(stale_c14n)
    with pytest.raises(TypedLocalCatalogError, match="actual profile validator"):
        validate_typed_local_catalog_manifest(stale_c14n, repository_root=REPOSITORY_ROOT)

    stale_witness = json.loads(MULTIVARIABLE_CALCULUS_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_witness["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["lean_witness"] = "example : True := by trivial"
    cards[0]["lean_witness_sha256"] = _sha256(cards[0]["lean_witness"].encode("utf-8"))
    cards[0]["source_witness_sha256"] = cards[0]["lean_witness_sha256"]
    _reseal_multivariable_calculus(stale_witness)
    with pytest.raises(TypedLocalCatalogError, match="Lean witness is not bound"):
        validate_typed_local_catalog_manifest(stale_witness, repository_root=REPOSITORY_ROOT)

    collision = json.loads(MULTIVARIABLE_CALCULUS_MANIFEST.read_text(encoding="utf-8"))
    cards = collision["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    cards[1] = copy.deepcopy(cards[0])
    _reseal_multivariable_calculus(collision)
    with pytest.raises(TypedLocalCatalogError, match="repeats a card id"):
        validate_typed_local_catalog_manifest(collision, repository_root=REPOSITORY_ROOT)

    canonical_collision = json.loads(MULTIVARIABLE_CALCULUS_MANIFEST.read_text(encoding="utf-8"))
    cards = canonical_collision["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    for key in (
        "openmath_xml",
        "openmath_xml_sha256",
        "canonical_openmath_xml",
        "canonical_openmath_xml_sha256",
    ):
        cards[1][key] = cards[0][key]
    _reseal_multivariable_calculus(canonical_collision)
    with pytest.raises(TypedLocalCatalogError, match="repeats canonical typed OpenMath"):
        validate_typed_local_catalog_manifest(
            canonical_collision,
            repository_root=REPOSITORY_ROOT,
        )

    boundary = json.loads(MULTIVARIABLE_CALCULUS_MANIFEST.read_text(encoding="utf-8"))
    boundary["hard_rejects"] = []
    _reseal_multivariable_calculus(boundary)
    with pytest.raises(TypedLocalCatalogError, match="hard reject boundary"):
        validate_typed_local_catalog_manifest(boundary, repository_root=REPOSITORY_ROOT)


def test_graph_and_probability_profiles_reject_resealed_evidence_mismatch() -> None:
    graph = json.loads(FINITE_GRAPH_MANIFEST.read_text(encoding="utf-8"))
    graph["admitted_candidate_cards"][0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal_graph(graph)
    with pytest.raises(TypedLocalCatalogError, match="actual profile validator"):
        validate_typed_local_catalog_manifest(graph, repository_root=REPOSITORY_ROOT)

    probability = json.loads(PROBABILITY_MANIFEST.read_text(encoding="utf-8"))
    probability["cards"][0]["embedding_namespace_preimage"] = "wrong profile namespace"
    _reseal_probability(probability)
    with pytest.raises(TypedLocalCatalogError, match="embedding namespace preimage"):
        validate_typed_local_catalog_manifest(probability, repository_root=REPOSITORY_ROOT)


def test_geometry_complex_profile_rejects_resealed_binding_and_witness_mismatch() -> None:
    stale = json.loads(GEOMETRY_COMPLEX_MANIFEST.read_text(encoding="utf-8"))
    profile = stale["profile"]
    assert isinstance(profile, dict)
    design = profile["profile_design"]
    assert isinstance(design, dict)
    design["sha256"] = "sha256:" + "0" * 64
    _reseal_geometry_complex(stale)
    with pytest.raises(
        TypedLocalCatalogError, match="vector/complex authoring manifest is invalid"
    ):
        validate_typed_local_catalog_manifest(stale, repository_root=REPOSITORY_ROOT)

    witness = json.loads(GEOMETRY_COMPLEX_MANIFEST.read_text(encoding="utf-8"))
    cards = witness["admitted_candidate_cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    lean = cards[0]["lean"]
    assert isinstance(lean, dict)
    lean["witness"] = "example : True := by trivial\n"
    lean["witness_sha256"] = _sha256(lean["witness"].encode("utf-8"))
    _reseal_geometry_complex(witness)
    with pytest.raises(
        TypedLocalCatalogError, match="vector/complex authoring manifest is invalid"
    ):
        validate_typed_local_catalog_manifest(witness, repository_root=REPOSITORY_ROOT)


def test_plane_geometry_profile_rejects_resealed_binding_c14n_witness_and_collision_mismatch() -> (
    None
):
    stale_binding = json.loads(PLANE_GEOMETRY_MANIFEST.read_text(encoding="utf-8"))
    profile = stale_binding["profile"]
    assert isinstance(profile, dict)
    bundle = profile["content_dictionary_bundle"]
    assert isinstance(bundle, dict)
    bundle["sha256"] = "sha256:" + "0" * 64
    _reseal_geometry_complex(stale_binding)
    with pytest.raises(TypedLocalCatalogError, match=PLANE_MANIFEST_ERROR):
        validate_typed_local_catalog_manifest(stale_binding, repository_root=REPOSITORY_ROOT)

    stale_c14n = json.loads(PLANE_GEOMETRY_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_c14n["admitted_candidate_cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal_geometry_complex(stale_c14n)
    with pytest.raises(TypedLocalCatalogError, match=PLANE_MANIFEST_ERROR):
        validate_typed_local_catalog_manifest(stale_c14n, repository_root=REPOSITORY_ROOT)

    stale_witness = json.loads(PLANE_GEOMETRY_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_witness["admitted_candidate_cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    lean = cards[0]["lean"]
    assert isinstance(lean, dict)
    lean["witness"] = "example : True := by trivial\n"
    lean["witness_sha256"] = _sha256(lean["witness"].encode("utf-8"))
    _reseal_geometry_complex(stale_witness)
    with pytest.raises(TypedLocalCatalogError, match=PLANE_MANIFEST_ERROR):
        validate_typed_local_catalog_manifest(stale_witness, repository_root=REPOSITORY_ROOT)

    collision = json.loads(PLANE_GEOMETRY_MANIFEST.read_text(encoding="utf-8"))
    cards = collision["admitted_candidate_cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    cards[1] = copy.deepcopy(cards[0])
    _reseal_geometry_complex(collision)
    with pytest.raises(TypedLocalCatalogError, match=PLANE_MANIFEST_ERROR):
        validate_typed_local_catalog_manifest(collision, repository_root=REPOSITORY_ROOT)


def test_plane_geometry_sql_is_profile_bound_and_never_executes_a_db_mutation() -> None:
    catalog = load_typed_local_catalog_manifest(
        PLANE_GEOMETRY_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == "typed-plane-geometry-v1"
    assert len(catalog.cards) == 5
    assert "profile_id = 'typed-plane-geometry-v1'" in sql
    assert catalog.profile.validator_module_sha256 in sql
    assert catalog.profile.registry_sha256 in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_number_theory_profile_rejects_resealed_artifact_or_c14n_mismatch() -> None:
    stale = json.loads(NUMBER_THEORY_MANIFEST.read_text(encoding="utf-8"))
    profile = stale["profile"]
    assert isinstance(profile, dict)
    profile["validator_sha256"] = "sha256:" + "0" * 64
    _reseal_number_theory(stale)
    with pytest.raises(TypedLocalCatalogError, match="number-theory manifest is invalid"):
        validate_typed_local_catalog_manifest(stale, repository_root=REPOSITORY_ROOT)

    c14n = json.loads(NUMBER_THEORY_MANIFEST.read_text(encoding="utf-8"))
    cards = c14n["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal_number_theory(c14n)
    with pytest.raises(TypedLocalCatalogError, match="number-theory manifest is invalid"):
        validate_typed_local_catalog_manifest(c14n, repository_root=REPOSITORY_ROOT)


def test_commutative_algebra_profile_rejects_resealed_binding_c14n_and_collision_mismatch() -> None:
    stale_binding = json.loads(COMMUTATIVE_ALGEBRA_MANIFEST.read_text(encoding="utf-8"))
    profile = stale_binding["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal_commutative_algebra(stale_binding)
    with pytest.raises(TypedLocalCatalogError, match="commutative-algebra manifest is invalid"):
        validate_typed_local_catalog_manifest(stale_binding, repository_root=REPOSITORY_ROOT)

    stale_c14n = json.loads(COMMUTATIVE_ALGEBRA_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_c14n["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal_commutative_algebra(stale_c14n)
    with pytest.raises(TypedLocalCatalogError, match="commutative-algebra manifest is invalid"):
        validate_typed_local_catalog_manifest(stale_c14n, repository_root=REPOSITORY_ROOT)

    collision = json.loads(COMMUTATIVE_ALGEBRA_MANIFEST.read_text(encoding="utf-8"))
    cards = collision["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    cards[1] = copy.deepcopy(cards[0])
    _reseal_commutative_algebra(collision)
    with pytest.raises(TypedLocalCatalogError, match="commutative-algebra manifest is invalid"):
        validate_typed_local_catalog_manifest(collision, repository_root=REPOSITORY_ROOT)


def test_commutative_algebra_sql_is_profile_bound_and_never_executes_a_db_mutation() -> None:
    catalog = load_typed_local_catalog_manifest(
        COMMUTATIVE_ALGEBRA_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == "typed-commutative-algebra-v1"
    assert len(catalog.cards) == 13
    assert "profile_id = 'typed-commutative-algebra-v1'" in sql
    assert catalog.profile.validator_module_sha256 in sql
    assert catalog.profile.registry_sha256 in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_commutative_algebra_modules_rejects_resealed_binding_c14n_status_and_collision() -> None:
    stale_binding = json.loads(COMMUTATIVE_ALGEBRA_MODULES_MANIFEST.read_text(encoding="utf-8"))
    profile = stale_binding["profile"]
    assert isinstance(profile, dict)
    profile["validator_sha256"] = "sha256:" + "0" * 64
    _reseal_commutative_algebra(stale_binding)
    with pytest.raises(
        TypedLocalCatalogError, match="commutative-algebra modules manifest is invalid"
    ):
        validate_typed_local_catalog_manifest(stale_binding, repository_root=REPOSITORY_ROOT)

    stale_c14n = json.loads(COMMUTATIVE_ALGEBRA_MODULES_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_c14n["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal_commutative_algebra(stale_c14n)
    with pytest.raises(
        TypedLocalCatalogError, match="commutative-algebra modules manifest is invalid"
    ):
        validate_typed_local_catalog_manifest(stale_c14n, repository_root=REPOSITORY_ROOT)

    bad_status = json.loads(COMMUTATIVE_ALGEBRA_MODULES_MANIFEST.read_text(encoding="utf-8"))
    cards = bad_status["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["admission_status"] = "generic-db-admitted"
    _reseal_commutative_algebra(bad_status)
    with pytest.raises(
        TypedLocalCatalogError, match="commutative-algebra modules manifest is invalid"
    ):
        validate_typed_local_catalog_manifest(bad_status, repository_root=REPOSITORY_ROOT)

    collision = json.loads(COMMUTATIVE_ALGEBRA_MODULES_MANIFEST.read_text(encoding="utf-8"))
    cards = collision["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    cards[1] = copy.deepcopy(cards[0])
    _reseal_commutative_algebra(collision)
    with pytest.raises(
        TypedLocalCatalogError, match="commutative-algebra modules manifest is invalid"
    ):
        validate_typed_local_catalog_manifest(collision, repository_root=REPOSITORY_ROOT)


def test_commutative_algebra_modules_sql_is_profile_bound_and_never_executes_db_mutation() -> None:
    catalog = load_typed_local_catalog_manifest(
        COMMUTATIVE_ALGEBRA_MODULES_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == "typed-commutative-algebra-modules-v1"
    assert len(catalog.cards) == 24
    assert "profile_id = 'typed-commutative-algebra-modules-v1'" in sql
    assert catalog.profile.validator_module_sha256 in sql
    assert catalog.profile.registry_sha256 in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_localization_profile_rejects_resealed_binding_c14n_and_collisions() -> None:
    stale_binding = json.loads(
        COMMUTATIVE_ALGEBRA_LOCALIZATION_MANIFEST.read_text(encoding="utf-8")
    )
    profile = stale_binding["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal_commutative_algebra_localization(stale_binding)
    with pytest.raises(
        TypedLocalCatalogError,
        match="commutative-algebra localization manifest is invalid",
    ):
        validate_typed_local_catalog_manifest(stale_binding, repository_root=REPOSITORY_ROOT)

    stale_c14n = json.loads(COMMUTATIVE_ALGEBRA_LOCALIZATION_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_c14n["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal_commutative_algebra_localization(stale_c14n)
    with pytest.raises(
        TypedLocalCatalogError,
        match="commutative-algebra localization manifest is invalid",
    ):
        validate_typed_local_catalog_manifest(stale_c14n, repository_root=REPOSITORY_ROOT)

    collision = json.loads(COMMUTATIVE_ALGEBRA_LOCALIZATION_MANIFEST.read_text(encoding="utf-8"))
    cards = collision["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    cards[1] = copy.deepcopy(cards[0])
    _reseal_commutative_algebra_localization(collision)
    with pytest.raises(
        TypedLocalCatalogError,
        match="commutative-algebra localization manifest is invalid",
    ):
        validate_typed_local_catalog_manifest(collision, repository_root=REPOSITORY_ROOT)


def test_commutative_algebra_localization_sql_is_profile_bound_and_never_mutates_db() -> None:
    catalog = load_typed_local_catalog_manifest(
        COMMUTATIVE_ALGEBRA_LOCALIZATION_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == "typed-commutative-algebra-localization-v1"
    assert len(catalog.cards) == 23
    assert "profile_id = 'typed-commutative-algebra-localization-v1'" in sql
    assert catalog.profile.validator_module_sha256 in sql
    assert catalog.profile.registry_sha256 in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_typed_ode_profile_rejects_resealed_binding_c14n_and_collision_mismatch() -> None:
    stale_binding = json.loads(ODE_MANIFEST.read_text(encoding="utf-8"))
    profile = stale_binding["profile"]
    assert isinstance(profile, dict)
    profile["registry_sha256"] = "sha256:" + "0" * 64
    _reseal_ode(stale_binding)
    with pytest.raises(TypedLocalCatalogError, match="typed ODE manifest is invalid"):
        validate_typed_local_catalog_manifest(stale_binding, repository_root=REPOSITORY_ROOT)

    stale_c14n = json.loads(ODE_MANIFEST.read_text(encoding="utf-8"))
    cards = stale_c14n["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict)
    cards[0]["canonical_openmath_xml"] = "<OMOBJ/>"
    cards[0]["canonical_openmath_xml_sha256"] = _sha256(b"<OMOBJ/>")
    _reseal_ode(stale_c14n)
    with pytest.raises(TypedLocalCatalogError, match="typed ODE manifest is invalid"):
        validate_typed_local_catalog_manifest(stale_c14n, repository_root=REPOSITORY_ROOT)

    collision = json.loads(ODE_MANIFEST.read_text(encoding="utf-8"))
    cards = collision["cards"]
    assert isinstance(cards, list) and isinstance(cards[0], dict) and isinstance(cards[1], dict)
    cards[1]["id"] = cards[0]["id"]
    cards[1]["source_candidate_id"] = cards[0]["id"]
    _reseal_ode(collision)
    with pytest.raises(TypedLocalCatalogError, match="typed ODE manifest is invalid"):
        validate_typed_local_catalog_manifest(collision, repository_root=REPOSITORY_ROOT)


def test_typed_ode_sql_is_profile_bound_and_never_executes_a_db_mutation() -> None:
    catalog = load_typed_local_catalog_manifest(ODE_MANIFEST, repository_root=REPOSITORY_ROOT)
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == "typed-ode-v1"
    assert len(catalog.cards) == 10
    assert "profile_id = 'typed-ode-v1'" in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_typed_math_core_only_revision_remains_explicitly_unloadable() -> None:
    with pytest.raises(TypedLocalCatalogError, match="sealed 22-card"):
        load_typed_local_catalog_manifest(GROUP_RING_MANIFEST, repository_root=REPOSITORY_ROOT)


def test_typed_math_typical_revision_rejects_core_id_and_canonical_collisions() -> None:
    core = json.loads(GROUP_RING_MANIFEST.read_text(encoding="utf-8"))
    id_collision = json.loads(TYPED_MATH_TYPICAL_MANIFEST.read_text(encoding="utf-8"))
    id_collision["cards"][0]["id"] = core["cards"][0]["id"]
    _reseal_matrix(id_collision)
    with pytest.raises(TypedLocalCatalogError, match="card id collides with core"):
        validate_typed_local_catalog_manifest(id_collision, repository_root=REPOSITORY_ROOT)

    canonical_collision = json.loads(TYPED_MATH_TYPICAL_MANIFEST.read_text(encoding="utf-8"))
    source = core["cards"][0]
    target = canonical_collision["cards"][0]
    for key in ("openmath_xml", "canonical_openmath_xml", "canonical_openmath_xml_sha256"):
        target[key] = source[key]
    _reseal_matrix(canonical_collision)
    with pytest.raises(TypedLocalCatalogError, match="canonical OpenMath collides with core"):
        validate_typed_local_catalog_manifest(canonical_collision, repository_root=REPOSITORY_ROOT)


def test_prepared_sql_is_profile_separated_and_has_collision_guards() -> None:
    catalog = load_typed_local_catalog_manifest(MATRIX_MANIFEST, repository_root=REPOSITORY_ROOT)
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert f"COPY {TYPED_CATALOG_SCHEMA}.catalog_cards" in sql
    assert f"COPY {TYPED_CATALOG_SCHEMA}.card_embeddings" in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "authoring_status" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()
    assert typed_catalog_embedding_text(catalog.cards[0]).startswith(
        "pals-typed-catalog-embedding-v1\nprofile_id=typed-math-matrix-v1\n"
    )


def test_real_analysis_expansion_sql_preserves_profile_and_embedding_binding() -> None:
    base = load_typed_local_catalog_manifest(
        REAL_ANALYSIS_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    expansion = load_typed_local_catalog_manifest(
        REAL_ANALYSIS_EXPANSION_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    sql = prepare_typed_local_catalog_sql(
        expansion,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in expansion.cards],
    )

    assert expansion.profile == base.profile
    assert expansion.manifest_digest != base.manifest_digest
    assert "profile_id = 'typed-real-analysis-v1'" in sql
    assert expansion.manifest_digest in sql
    assert base.manifest_digest not in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_multivariable_calculus_sql_is_profile_bound_and_never_executes_db_mutation() -> None:
    catalog = load_typed_local_catalog_manifest(
        MULTIVARIABLE_CALCULUS_MANIFEST,
        repository_root=REPOSITORY_ROOT,
    )
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == "typed-multivariable-calculus-v1"
    assert len(catalog.cards) == 6
    assert "profile_id = 'typed-multivariable-calculus-v1'" in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed manifest digest is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


@pytest.mark.parametrize(
    ("manifest_path", "profile_id", "card_count"),
    (
        (MATRIX_MANIFEST, "typed-math-matrix-v1", 6),
        (REAL_ANALYSIS_MANIFEST, "typed-real-analysis-v1", 4),
        (REAL_ANALYSIS_EXPANSION_MANIFEST, "typed-real-analysis-v1", 15),
        (MULTIVARIABLE_CALCULUS_MANIFEST, "typed-multivariable-calculus-v1", 6),
        (FINITE_GRAPH_MANIFEST, "typed-finite-graph-v1", 5),
        (GEOMETRY_COMPLEX_MANIFEST, "typed-geometry-complex-v1", 8),
        (PLANE_GEOMETRY_MANIFEST, "typed-plane-geometry-v1", 5),
        (PROBABILITY_MANIFEST, "typed-probability-v1", 10),
        (NUMBER_THEORY_MANIFEST, "typed-number-theory-v1", 12),
        (COMMUTATIVE_ALGEBRA_MANIFEST, "typed-commutative-algebra-v1", 13),
        (COMMUTATIVE_ALGEBRA_MODULES_MANIFEST, "typed-commutative-algebra-modules-v1", 24),
        (ODE_MANIFEST, "typed-ode-v1", 10),
        (TYPED_MATH_TYPICAL_MANIFEST, "typed-math-v1", 22),
    ),
)
def test_every_supported_profile_generates_profile_bound_sql(
    manifest_path: Path, profile_id: str, card_count: int
) -> None:
    catalog = load_typed_local_catalog_manifest(manifest_path, repository_root=REPOSITORY_ROOT)
    sql = prepare_typed_local_catalog_sql(
        catalog,
        embedding_binding=_binding(),
        embeddings=[_vector() for _ in catalog.cards],
    )

    assert catalog.profile.profile_id == profile_id
    assert len(catalog.cards) == card_count
    assert f"profile_id = '{profile_id}'" in sql
    assert "typed profile binding is stale or mismatched" in sql
    assert "typed card id collision" in sql
    assert "typed canonical OpenMath collision" in sql
    assert "public.dsp_drafts" not in sql
    assert "pfi_" not in sql.lower()


def test_prepared_sql_rejects_wrong_embedding_dimension_and_count() -> None:
    catalog = load_typed_local_catalog_manifest(MATRIX_MANIFEST, repository_root=REPOSITORY_ROOT)
    with pytest.raises(TypedLocalCatalogError, match="embedding count"):
        prepare_typed_local_catalog_sql(
            catalog,
            embedding_binding=_binding(),
            embeddings=[_vector()],
        )
    with pytest.raises(TypedLocalCatalogError, match="pinned 384"):
        TypedEmbeddingBinding(
            provider="openai",
            model="text-embedding-3-small",
            dimension=383,
            endpoint="https://api.openai.com/v1",
            deployment="text-embedding-3-small",
            revision="openai-release-2024-01-25",
        )
    with pytest.raises(TypedLocalCatalogError, match="pinned embedding binding"):
        TypedEmbeddingBinding(
            provider="openai",
            model="text-embedding-3-small",
            dimension=384,
            endpoint="https://example.invalid/v1",
            deployment="text-embedding-3-small",
            revision="openai-release-2024-01-25",
        )


def test_ddl_only_defines_the_immutable_typed_schema() -> None:
    ddl = DDL.read_text(encoding="utf-8")

    assert f"CREATE SCHEMA {TYPED_CATALOG_SCHEMA}" in ddl
    assert "catalog_profiles_immutable" in ddl
    assert "catalog_cards_immutable" in ddl
    assert "card_embeddings_immutable" in ddl
    assert "vector(384)" in ddl
    assert "embedding_binding_sha256" in ddl
    assert "public.dsp_drafts" not in ddl
    assert "pfi_" not in ddl.lower()
