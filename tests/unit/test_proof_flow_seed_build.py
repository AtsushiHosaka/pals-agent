from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import rfc8785

from pals_agent.draft_catalog import load_seed_drafts
from pals_agent.models import ProofDraft
from pals_agent.openmath import (
    MathXMLValidationError,
    canonicalize_openmath_xml_v4,
    canonicalize_retrieval_openmath_xml,
)
from pals_agent.proof_flow_seed import (
    CanonicalizerChildProperty,
    ProofDraftSeedBuilder,
    SeedBuildError,
    SeedEmbeddingFingerprint,
    host_elementtree_source_sha256,
)

PALS_ROOT = Path(__file__).parents[3]

_EXCLUDED_FUNCTION_SORT_SOURCE_IDS = frozenset(
    {
        "continuous_add",
        "continuous_mul",
        "continuous_neg",
        "continuous_sub",
        "continuous_abs_of_function",
        "continuous_square_of_function",
        "continuous_power_of_function",
        "continuous_composition",
        "compact_image",
    }
)
_EXPECTED_SOURCE_SEED_IDS = frozenset(
    {
        "continuous_square",
        "continuous_power",
        "continuous_affine",
        "continuous_absolute_value",
        "continuous_reciprocal_nonzero",
        "rank_nullity",
        "continuous_affine_three_minus_two",
        "continuous_cube",
        "continuous_fourth_power",
        "continuous_shift_plus_one",
        "continuous_shift_minus_one",
        "continuous_scale_two",
        "continuous_quadratic_plus_one",
        "continuous_quadratic_minus_one",
        "continuous_square_plus_identity",
        "continuous_cube_plus_one",
        "continuous_cube_minus_identity",
        "continuous_even_polynomial",
        "continuous_quadratic_trinomial",
        "continuous_cubic_polynomial",
        "continuous_constant_real",
        "continuous_shifted_square",
        "continuous_shifted_absolute",
        "continuous_affine_absolute",
        "continuous_x_abs",
        "continuous_identity_real",
        "continuous_abs_quadratic_minus_one",
        "continuous_rational_x_over_square_plus_one",
        "continuous_rational_one_over_square_plus_one",
        "continuous_rational_shifted_numerator",
        "continuous_rational_quadratic_ratio",
    }
)

_CANONICALIZER_PROPERTY = CanonicalizerChildProperty(
    source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
    source_sha256=host_elementtree_source_sha256(),
)


class _EmbeddingModel:
    def __init__(self, vectors: list[list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._vectors[len(self.calls) - 1]


def _draft(identifier: str = "continuous_square") -> ProofDraft:
    return ProofDraft(
        id=identifier,
        matched_prompt="Show that x squared is continuous.",
        openmath_xml=(
            '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
            '<OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="continuous_on"/><OMS cd="setname1" name="R"/>'
            '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR>'
            '<OMV name="x"/></OMBVAR><OMA><OMS cd="arith1" name="power"/>'
            '<OMV name="x"/><OMI>2</OMI></OMA></OMBIND></OMA></OMOBJ>'
        ),
        proof_strategy="Use the metric definition.",
        sketch_steps=("Fix epsilon.", "Choose delta."),
    )


def _reintroduced_function_sort_draft(identifier: str) -> ProofDraft:
    """A formerly excluded source identity with its unannotated function variable."""
    return ProofDraft(
        id=identifier,
        matched_prompt="Generic mathematical statement.",
        openmath_xml=(
            '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
            '<OMBIND><OMS cd="quant1" name="forall"/><OMBVAR><OMV name="f"/>'
            '</OMBVAR><OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="continuous_on"/><OMS cd="setname1" name="R"/>'
            '<OMV name="f"/></OMA></OMBIND></OMOBJ>'
        ),
        proof_strategy="Use the continuity premise.",
        sketch_steps=("Apply the continuity premise.",),
    )


def _fingerprint() -> SeedEmbeddingFingerprint:
    return SeedEmbeddingFingerprint(
        provider="provider",
        model="model",
        endpoint="https://embedding.invalid/v1",
        deployment="deployment",
        revision="revision",
        dimension=2,
        canonicalizer_version="openmath-cdbase-alpha-c14n-v4",
    )


def _builder(model: _EmbeddingModel) -> ProofDraftSeedBuilder:
    return ProofDraftSeedBuilder(
        embedding_model=model,
        fingerprint=_fingerprint(),
        canonicalizer_property=_CANONICALIZER_PROPERTY,
    )


def test_pfi_ag_002_rejects_c14n_v3_fingerprint_before_embedding() -> None:
    with pytest.raises(ValueError, match="canonicalizer version"):
        replace(_fingerprint(), canonicalizer_version="openmath-cdbase-alpha-c14n-v3")


@pytest.mark.parametrize(
    "source_commit",
    (
        "1" * 39,
        "1" * 41,
        "A" * 40,
        ("1" * 39) + "g",
        ("1" * 39) + "\n",
    ),
)
def test_pfi_ag_002_rejects_each_noncanonical_source_commit_before_embedding(
    tmp_path: Path,
    source_commit: str,
) -> None:
    model = _EmbeddingModel([[1.0, 0.0]])
    destination = tmp_path / "published"

    with pytest.raises(SeedBuildError, match="source commit"):
        _builder(model).build(
            drafts=(_draft(),),
            destination=destination,
            source_commit=source_commit,
        )

    assert model.calls == []
    assert not destination.exists()


def test_pfi_ag_002_builds_exact_atomic_seed_manifest_and_oci_property(
    tmp_path: Path,
) -> None:
    model = _EmbeddingModel([[1.0, -0.0]])
    output = tmp_path / "published"

    artifact = _builder(model).build(
        drafts=(_draft(),),
        destination=output,
        source_commit="1" * 40,
    )

    seed_bytes = artifact.seed_file.read_bytes()
    seed = json.loads(seed_bytes)
    assert seed_bytes == rfc8785.dumps(seed)
    assert not seed_bytes.endswith(b"\n")
    assert seed["schema_version"] == "pals.draft-catalog-seed.v1"
    assert seed["fingerprint"] == _fingerprint().as_json()
    assert list(seed["rows"][0]) == [
        "canonical_statement",
        "embedding",
        "id",
        "openmath_xml",
        "proof_strategy",
        "sketch_steps",
    ]
    assert seed["rows"][0]["canonical_statement"] == _draft().matched_prompt
    assert "matched_prompt" not in seed_bytes.decode("utf-8")
    assert seed["rows"][0]["embedding"] == [1.0, 0.0]
    assert model.calls == [seed["rows"][0]["openmath_xml"]]

    projection = [{key: value for key, value in seed["rows"][0].items() if key != "embedding"}]
    expected_manifest = "sha256:" + hashlib.sha256(rfc8785.dumps(projection)).hexdigest()
    assert artifact.seed_manifest_sha256 == expected_manifest

    labels = json.loads(artifact.oci_labels_file.read_bytes())
    encoded = labels["io.pals.draft-retrieval-provenance.v1"]
    provenance_bytes = base64.urlsafe_b64decode(encoded + ("=" * (-len(encoded) % 4)))
    provenance = json.loads(provenance_bytes)
    assert provenance_bytes == rfc8785.dumps(provenance)
    assert provenance["property_id"] == "PFI-BP-001"
    assert provenance["elementtree_source_path"] == _CANONICALIZER_PROPERTY.source_path
    assert provenance["elementtree_source_sha256"] == _CANONICALIZER_PROPERTY.source_sha256
    assert provenance["seed_manifest_sha256"] == expected_manifest
    assert provenance["seed_file_sha256"] == hashlib.sha256(seed_bytes).hexdigest()
    assert (
        labels["io.pals.draft-retrieval-provenance.sha256"]
        == hashlib.sha256(provenance_bytes).hexdigest()
    )


@pytest.mark.parametrize(
    "vectors",
    [
        [[0.0, -0.0]],
        [[float("inf"), 1.0]],
        [[1.0]],
    ],
)
def test_pfi_ag_002_invalid_embedding_publishes_nothing(
    tmp_path: Path,
    vectors: list[list[float]],
) -> None:
    output = tmp_path / "published"

    with pytest.raises(SeedBuildError):
        _builder(_EmbeddingModel(vectors)).build(
            drafts=(_draft(),),
            destination=output,
            source_commit="1" * 40,
        )

    assert not output.exists()


def test_pfi_ag_002_oversized_candidate_fails_before_embedding_and_publication(
    tmp_path: Path,
) -> None:
    """The 16 KiB candidate limit is a build-input gate, not a provider charge."""
    output = tmp_path / "published"
    model = _EmbeddingModel([[1.0, 0.0]])
    oversized = replace(_draft(), proof_strategy="x" * 20_000)

    with pytest.raises(SeedBuildError, match="candidate exceeds"):
        _builder(model).build(
            drafts=(oversized,),
            destination=output,
            source_commit="1" * 40,
        )

    assert model.calls == []
    assert not output.exists()


def test_pfi_ag_002_validates_every_row_before_any_embedding_request(
    tmp_path: Path,
) -> None:
    """A later invalid row must not charge the embedding provider for an earlier row."""
    output = tmp_path / "published"
    model = _EmbeddingModel([[1.0, 0.0]])
    oversized = replace(
        _draft("continuous_square_two"),
        proof_strategy="x" * 20_000,
    )

    with pytest.raises(SeedBuildError, match="candidate exceeds"):
        _builder(model).build(
            drafts=(_draft(), oversized),
            destination=output,
            source_commit="1" * 40,
        )

    assert model.calls == []
    assert not output.exists()


def test_pfi_ag_002_rejects_a_final_image_canonicalizer_that_differs_from_host(
    tmp_path: Path,
) -> None:
    output = tmp_path / "published"
    builder = replace(
        _builder(_EmbeddingModel([[1.0, 0.0]])),
        canonicalizer_property=replace(
            _CANONICALIZER_PROPERTY,
            source_sha256="0" * 64,
        ),
    )

    with pytest.raises(SeedBuildError, match="canonicalizer does not match"):
        builder.build(
            drafts=(_draft(),),
            destination=output,
            source_commit="1" * 40,
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "source_path",
    (
        "/opt/pals/../xml/ElementTree.py",
        "/proc/xml/ElementTree.py",
        "/sys/xml/ElementTree.py",
        "/dev/xml/ElementTree.py",
        "/run/xml/ElementTree.py",
        "/tmp/ElementTree.py",
        "//opt/pals/xml/ElementTree.py",
    ),
)
def test_pfi_ag_002_rejects_noncanonical_or_ephemeral_canonicalizer_source_paths(
    source_path: str,
) -> None:
    with pytest.raises(SeedBuildError, match="canonicalizer source path"):
        replace(_CANONICALIZER_PROPERTY, source_path=source_path)


def test_pfi_ag_002_rejects_a_same_named_elementtree_outside_the_base_image_stdlib() -> None:
    with pytest.raises(SeedBuildError, match="canonicalizer source path"):
        replace(
            _CANONICALIZER_PROPERTY,
            source_path="/opt/pals/fake/xml/etree/ElementTree.py",
        )


def test_pfi_ag_002_accepts_the_verified_container_elementtree_path(
    tmp_path: Path,
) -> None:
    output = tmp_path / "published"
    container_property = replace(
        _CANONICALIZER_PROPERTY,
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
    )
    builder = replace(
        _builder(_EmbeddingModel([[1.0, 0.0]])),
        canonicalizer_property=container_property,
    )

    artifact = builder.build(
        drafts=(_draft(),),
        destination=output,
        source_commit="1" * 40,
    )

    provenance = json.loads(artifact.build_provenance_file.read_bytes())
    assert provenance["elementtree_source_path"] == container_property.source_path


def test_pfi_ag_002_duplicate_id_and_mid_build_failure_are_atomic(
    tmp_path: Path,
) -> None:
    output = tmp_path / "published"
    duplicate = replace(_draft(), matched_prompt="A second row with the same ID.")

    with pytest.raises(SeedBuildError):
        _builder(_EmbeddingModel([[1.0, 0.0], [1.0, 0.0]])).build(
            drafts=(_draft(), duplicate),
            destination=output,
            source_commit="1" * 40,
        )

    assert not output.exists()


def test_pfi_ag_002_packaged_seed_excludes_exact_function_sort_ids_and_builds(
    tmp_path: Path,
) -> None:
    drafts = load_seed_drafts()
    model = _EmbeddingModel([[1.0, 0.5] for _draft_row in drafts])
    output = tmp_path / "published"

    assert len(drafts) == 31
    assert {draft.id for draft in drafts} == _EXPECTED_SOURCE_SEED_IDS
    assert _EXCLUDED_FUNCTION_SORT_SOURCE_IDS.isdisjoint(_EXPECTED_SOURCE_SEED_IDS)

    artifact = _builder(model).build(
        drafts=drafts,
        destination=output,
        source_commit="1" * 40,
    )

    seed = json.loads(artifact.seed_file.read_bytes())
    manifest_bytes = artifact.seed_manifest_file.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected_ids = sorted(_EXPECTED_SOURCE_SEED_IDS)

    assert artifact.seed_count == 31
    assert [row["id"] for row in seed["rows"]] == expected_ids
    assert [row["id"] for row in manifest] == expected_ids
    assert all("embedding" not in row for row in manifest)
    assert artifact.seed_manifest_sha256 == "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    assert model.calls == [row["openmath_xml"] for row in seed["rows"]]


@pytest.mark.parametrize("identifier", sorted(_EXCLUDED_FUNCTION_SORT_SOURCE_IDS))
def test_pfi_ag_002_reintroduced_function_sort_source_id_fails_atomically(
    tmp_path: Path,
    identifier: str,
) -> None:
    output = tmp_path / "published"
    model = _EmbeddingModel([[1.0, 0.5]])

    with pytest.raises(SeedBuildError):
        _builder(model).build(
            drafts=(_reintroduced_function_sort_draft(identifier),),
            destination=output,
            source_commit="1" * 40,
        )

    assert model.calls == []
    assert not output.exists()


@pytest.mark.parametrize(
    ("symbol", "expression"),
    [
        (
            "arith1:sum",
            '<OMA><OMS cd="relation1" name="eq"/><OMA><OMS cd="arith1" '
            'name="sum"/><OMS cd="setname1" name="R"/><OMI>1</OMI></OMA>'
            "<OMI>0</OMI></OMA>",
        ),
        (
            "arith1:product",
            '<OMA><OMS cd="relation1" name="eq"/><OMA><OMS cd="arith1" '
            'name="product"/><OMS cd="setname1" name="R"/><OMI>1</OMI></OMA>'
            "<OMI>0</OMI></OMA>",
        ),
        (
            "set1:map",
            '<OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="compact"/><OMA><OMS cd="set1" name="map"/><OMI>1</OMI>'
            '<OMS cd="setname1" name="R"/></OMA></OMA>',
        ),
        (
            "set1:suchthat",
            '<OMA><OMS cd="relation1" name="eq"/><OMA><OMS cd="set1" '
            'name="size"/><OMA><OMS cd="set1" name="suchthat"/>'
            '<OMS cd="setname1" name="R"/><OMI>1</OMI></OMA></OMA><OMI>0</OMI>'
            "</OMA>",
        ),
        (
            "pals1:continuous_on",
            '<OMA><OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" '
            'name="continuous_on"/><OMS cd="setname1" name="R"/><OMI>1</OMI>'
            "</OMA>",
        ),
    ],
)
def test_pfi_ag_002_retrieval_function_slots_reject_nested_term_values(
    symbol: str,
    expression: str,
) -> None:
    xml = f'<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">{expression}</OMOBJ>'

    with pytest.raises(MathXMLValidationError, match=rf"`{symbol}` must have sort"):
        canonicalize_retrieval_openmath_xml(xml)


def test_pfi_ag_002_v4_prefix_oracle_and_closed_variable_gate() -> None:
    free = (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">'
        '<OMA><OMS cd="relation1" name="eq"/><OMV name="x"/>'
        '<OMV name="y"/></OMA></OMOBJ>'
    )

    assert canonicalize_openmath_xml_v4(free) == (
        '<n1:OMOBJ xmlns:n1="http://www.openmath.org/OpenMath" '
        'version="2.0"><n1:OMA><n1:OMS cd="relation1" name="eq"></n1:OMS>'
        '<n1:OMV name="x"></n1:OMV><n1:OMV name="y"></n1:OMV>'
        "</n1:OMA></n1:OMOBJ>"
    )
    with pytest.raises(MathXMLValidationError):
        canonicalize_retrieval_openmath_xml(free)


def test_pfi_ag_002_mid_embedding_failure_publishes_nothing(tmp_path: Path) -> None:
    output = tmp_path / "published"
    second = replace(_draft(), id="continuous_square_two")
    model = _EmbeddingModel([[1.0, 0.0], [float("nan"), 1.0]])

    with pytest.raises(SeedBuildError):
        _builder(model).build(
            drafts=(_draft(), second),
            destination=output,
            source_commit="1" * 40,
        )

    assert len(model.calls) == 2
    assert not output.exists()


def test_pfi_ag_002_worker_image_requires_seed_and_exact_oci_labels() -> None:
    dockerfile = (PALS_ROOT / "pals-agent" / "Dockerfile").read_text(encoding="utf-8")
    normalized = " ".join(dockerfile.split())

    assert dockerfile.startswith("FROM python:3.12.13-slim")
    assert "build/proof-flow-index/rootfs/opt/pals/draft-seed.json" in normalized
    assert "io.pals.draft-retrieval-provenance.v1" in dockerfile
    assert "io.pals.draft-retrieval-provenance.sha256" in dockerfile
    assert "PALS_PFI_BUILD_PROVENANCE_SHA256" in dockerfile
    environment = dockerfile.split("ENV", 1)[1].split("WORKDIR", 1)[0]
    assert "PALS_PFI_PROVENANCE_SHA256" not in environment
    assert "PALS_PFI_BUILD_PROVENANCE_V1" not in environment
    assert "PALS_PFI_BUILD_PROVENANCE_SHA256" not in environment
