from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import platform
import re
import shutil
import stat
import struct
import sysconfig
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import rfc8785

from pals_agent.models import ProofDraft
from pals_agent.openmath import (
    MathXMLValidationError,
    canonicalize_retrieval_openmath_xml,
    validate_canonical_retrieval_openmath_xml,
    validate_openmath_statement_semantics,
)

_PARENT_HASHES = {
    "requirements.md": "358225f8fce24dbaf3b8a87dd71b674a2968979a9f60e3106ec8cce8a530c4ac",
    "design.md": "a4e03127d9903495ee6444d87df238025cbdabdce0b2e8d9d9a6d417413b2a4d",
    "tasks.md": "44effa741ddad7740325c7b7e9d389c23da51ecd57cf96450cd722ab87fc8de0",
}
_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v4"
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DRAFT_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SEED_PATH = "/opt/pals/draft-seed.json"
_CONTAINER_ELEMENTTREE_PATH = "/usr/local/lib/python3.12/xml/etree/ElementTree.py"
_MAX_TEXT = 20_000
_MAX_ROWS = 4096
_MAX_STEPS = 256
_MAX_CANDIDATE_BYTES = 16_384
_MAX_SEED_BYTES = 536_870_912
_PROVENANCE_LABEL = "io.pals.draft-retrieval-provenance.v1"
_PROVENANCE_DIGEST_LABEL = "io.pals.draft-retrieval-provenance.sha256"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ParentPFIAuthorityError(RuntimeError):
    pass


class SeedBuildError(RuntimeError):
    pass


class ContinuityCatalogError(RuntimeError):
    """Fail-closed admission error for the approved continuity-v2 source set."""

    def __init__(self, code: str) -> None:
        super().__init__(f"continuity catalog rejected: {code}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ContinuityCatalogCard:
    draft_id: str
    coverage: Mapping[str, Any]
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ContinuityCatalog:
    schema_version: str
    cards: tuple[ContinuityCatalogCard, ...]
    required_signatures: tuple[Mapping[str, Any], ...]


_CONTINUITY_CATALOG_SCHEMA = "pals.continuity-draft-catalog.v2"
_CONTINUITY_PROFILE_SCHEMA = "pals.continuity-coverage-profile.v1"
_COVERAGE_FIELDS = frozenset(
    {
        "context",
        "operators",
        "prerequisites",
        "proof_schema",
        "representation",
        "stratum",
        "topic",
    }
)
_CONTINUITY_CARD_FIELDS = frozenset(
    {
        "canonical_statement",
        "coverage",
        "coverage_objective",
        "draft_id",
        "english_expected_draft_id",
        "english_query",
        "hard_negative_expected_result",
        "hard_negative_query",
        "japanese_expected_draft_id",
        "japanese_query",
        "lean_target",
        "novelty_key",
        "openmath_xml",
        "proof_strategy",
        "sketch_steps",
    }
)
_NOVELTY_KEY = re.compile(r"^sha256:[0-9a-f]{64}$")
_COVERAGE_TOPICS = frozenset(
    {
        "closure_add_sub_neg",
        "closure_compose",
        "closure_div_nonzero",
        "closure_mul_scale",
        "continuity_at",
        "continuity_on",
        "limit_at",
        "sequence_convergence",
        "sequential_continuity",
    }
)
_COVERAGE_CONTEXTS = frozenset({"continuity_at", "continuity_on", "limit_at", "sequence"})
_COVERAGE_STRATA = frozenset({"bridge", "core_law", "instance"})
_COVERAGE_REPRESENTATIONS = frozenset({"concrete_lambda", "sequence_lambda", "variable_closure"})
_COVERAGE_PROOF_SCHEMAS = frozenset({"basic", "closure", "concrete_instance", "transport"})
_CONTINUITY_OPERATORS = frozenset(
    {
        "constant_function",
        "function_add",
        "function_compose",
        "function_div",
        "function_mul",
        "function_neg",
        "function_scale",
        "function_sub",
        "identity_function",
        "sequence_add",
        "sequence_compose",
        "sequence_div",
        "sequence_mul",
        "sequence_neg",
        "sequence_scale",
        "sequence_sub",
    }
)
_CONTINUITY_PREREQUISITES = frozenset(
    {
        "continuous_at_denominator",
        "continuous_at_left",
        "continuous_at_numerator",
        "continuous_at_right",
        "continuous_at_subject",
        "continuous_on_real_denominator",
        "continuous_on_real_left",
        "continuous_on_real_numerator",
        "continuous_on_real_right",
        "continuous_on_real_subject",
        "converges_to_denominator",
        "converges_to_left",
        "converges_to_numerator",
        "converges_to_right",
        "converges_to_subject",
        "has_limit_at_denominator",
        "has_limit_at_left",
        "has_limit_at_numerator",
        "has_limit_at_right",
        "has_limit_at_subject",
        "inner_continuous_at",
        "inner_converges_to",
        "inner_has_limit_at",
        "nonzero_denominator_at",
        "nonzero_denominator_everywhere",
        "nonzero_denominator_limit",
        "nonzero_denominator_sequence_limit",
        "outer_continuous_at_inner_limit",
        "outer_continuous_at_inner_value",
    }
)


def _continuity_error(code: str) -> None:
    raise ContinuityCatalogError(code)


def _canonical_json_bytes(value: Any, *, error_code: str) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ContinuityCatalogError(error_code) from exc


def _coverage_signature(value: Any, *, error_code: str) -> tuple[Mapping[str, Any], bytes]:
    if not isinstance(value, dict) or set(value) != _COVERAGE_FIELDS:
        _continuity_error(error_code)
    if any(
        not isinstance(value[name], str) or not value[name]
        for name in _COVERAGE_FIELDS - {"operators", "prerequisites"}
    ):
        _continuity_error(error_code)
    for name in ("operators", "prerequisites"):
        entries = value[name]
        if (
            not isinstance(entries, list)
            or any(not isinstance(item, str) or not item for item in entries)
            or entries != sorted(entries, key=lambda item: item.encode("utf-8"))
            or len(entries) != len(set(entries))
        ):
            _continuity_error(error_code)
    return value, _canonical_json_bytes(value, error_code=error_code)


def _validated_coverage_signature(
    value: Any, *, error_code: str
) -> tuple[Mapping[str, Any], bytes]:
    signature, canonical = _coverage_signature(value, error_code=error_code)
    if (
        signature["topic"] not in _COVERAGE_TOPICS
        or signature["context"] not in _COVERAGE_CONTEXTS
        or signature["stratum"] not in _COVERAGE_STRATA
        or signature["representation"] not in _COVERAGE_REPRESENTATIONS
        or signature["proof_schema"] not in _COVERAGE_PROOF_SCHEMAS
        or not set(signature["operators"]).issubset(_CONTINUITY_OPERATORS)
        or not set(signature["prerequisites"]).issubset(_CONTINUITY_PREREQUISITES)
    ):
        _continuity_error(error_code)
    return signature, canonical


def _coverage(
    topic: str,
    context: str,
    operators: tuple[str, ...],
    prerequisites: tuple[str, ...],
    proof_schema: str,
    representation: str,
    *,
    stratum: str = "core_law",
) -> dict[str, Any]:
    return {
        "context": context,
        "operators": sorted(operators, key=lambda item: item.encode("utf-8")),
        "prerequisites": sorted(prerequisites, key=lambda item: item.encode("utf-8")),
        "proof_schema": proof_schema,
        "representation": representation,
        "stratum": stratum,
        "topic": topic,
    }


def _expanded_c0_signature_bytes() -> tuple[bytes, ...]:
    """Mechanically expand the PFI-008 C0 table; it is not a card-count contract."""

    signatures = [
        _coverage("limit_at", "limit_at", ("constant_function",), (), "basic", "concrete_lambda"),
        _coverage("limit_at", "limit_at", ("identity_function",), (), "basic", "concrete_lambda"),
        _coverage("sequence_convergence", "sequence", (), (), "basic", "sequence_lambda"),
        _coverage(
            "continuity_at", "continuity_at", ("constant_function",), (), "basic", "concrete_lambda"
        ),
        _coverage(
            "continuity_at", "continuity_at", ("identity_function",), (), "basic", "concrete_lambda"
        ),
        _coverage(
            "continuity_on", "continuity_on", ("constant_function",), (), "basic", "concrete_lambda"
        ),
        _coverage(
            "continuity_on", "continuity_on", ("identity_function",), (), "basic", "concrete_lambda"
        ),
        _coverage(
            "limit_at",
            "limit_at",
            (),
            ("continuous_at_subject",),
            "transport",
            "variable_closure",
            stratum="bridge",
        ),
        _coverage(
            "continuity_at",
            "continuity_at",
            (),
            ("continuous_on_real_subject",),
            "transport",
            "variable_closure",
            stratum="bridge",
        ),
        _coverage(
            "sequential_continuity",
            "sequence",
            ("sequence_compose",),
            ("continuous_at_subject", "converges_to_subject"),
            "transport",
            "sequence_lambda",
            stratum="bridge",
        ),
    ]
    for function_operator, sequence_operator in (
        ("function_add", "sequence_add"),
        ("function_sub", "sequence_sub"),
        ("function_mul", "sequence_mul"),
    ):
        topic = (
            "closure_mul_scale" if function_operator == "function_mul" else "closure_add_sub_neg"
        )
        signatures.extend(
            (
                _coverage(
                    topic,
                    "continuity_at",
                    (function_operator,),
                    ("continuous_at_left", "continuous_at_right"),
                    "closure",
                    "variable_closure",
                ),
                _coverage(
                    topic,
                    "continuity_on",
                    (function_operator,),
                    ("continuous_on_real_left", "continuous_on_real_right"),
                    "closure",
                    "variable_closure",
                ),
                _coverage(
                    topic,
                    "limit_at",
                    (function_operator,),
                    ("has_limit_at_left", "has_limit_at_right"),
                    "closure",
                    "variable_closure",
                ),
                _coverage(
                    topic,
                    "sequence",
                    (sequence_operator,),
                    ("converges_to_left", "converges_to_right"),
                    "closure",
                    "variable_closure",
                ),
            )
        )
    for context, operator, prerequisite in (
        ("continuity_at", "function_neg", "continuous_at_subject"),
        ("continuity_on", "function_neg", "continuous_on_real_subject"),
        ("limit_at", "function_neg", "has_limit_at_subject"),
        ("sequence", "sequence_neg", "converges_to_subject"),
        ("continuity_at", "function_scale", "continuous_at_subject"),
        ("continuity_on", "function_scale", "continuous_on_real_subject"),
        ("limit_at", "function_scale", "has_limit_at_subject"),
        ("sequence", "sequence_scale", "converges_to_subject"),
    ):
        signatures.append(
            _coverage(
                "closure_add_sub_neg" if "neg" in operator else "closure_mul_scale",
                context,
                (operator,),
                (prerequisite,),
                "closure",
                "variable_closure",
            )
        )
    signatures.extend(
        (
            _coverage(
                "closure_compose",
                "continuity_at",
                ("function_compose",),
                ("inner_continuous_at", "outer_continuous_at_inner_value"),
                "closure",
                "variable_closure",
            ),
            _coverage(
                "closure_compose",
                "limit_at",
                ("function_compose",),
                ("inner_has_limit_at", "outer_continuous_at_inner_limit"),
                "closure",
                "variable_closure",
            ),
            _coverage(
                "closure_compose",
                "sequence",
                ("sequence_compose",),
                ("inner_converges_to", "outer_continuous_at_inner_limit"),
                "closure",
                "variable_closure",
            ),
            _coverage(
                "closure_div_nonzero",
                "continuity_at",
                ("function_div",),
                ("continuous_at_denominator", "continuous_at_numerator", "nonzero_denominator_at"),
                "closure",
                "variable_closure",
            ),
            _coverage(
                "closure_div_nonzero",
                "continuity_on",
                ("function_div",),
                (
                    "continuous_on_real_denominator",
                    "continuous_on_real_numerator",
                    "nonzero_denominator_everywhere",
                ),
                "closure",
                "variable_closure",
            ),
            _coverage(
                "closure_div_nonzero",
                "limit_at",
                ("function_div",),
                ("has_limit_at_denominator", "has_limit_at_numerator", "nonzero_denominator_limit"),
                "closure",
                "variable_closure",
            ),
            _coverage(
                "closure_div_nonzero",
                "sequence",
                ("sequence_div",),
                (
                    "converges_to_denominator",
                    "converges_to_numerator",
                    "nonzero_denominator_sequence_limit",
                ),
                "closure",
                "variable_closure",
            ),
        )
    )
    canonical = tuple(
        sorted(_canonical_json_bytes(item, error_code="c0_invalid") for item in signatures)
    )
    if len(canonical) != 37 or len(canonical) != len(set(canonical)):
        raise AssertionError("PFI-008 C0 expansion is malformed")
    return canonical


def load_continuity_catalog(path: Path) -> ContinuityCatalog:
    """Load only exact v2 JCS bytes and admit a complete one-card-per-C0 profile."""

    try:
        mode = path.lstat().st_mode
        raw = path.read_bytes()
    except OSError as exc:
        raise ContinuityCatalogError("catalog_unreadable") from exc
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        _continuity_error("catalog_not_regular_file")
    if not raw or b"\n" in raw or raw.startswith(b"\xef\xbb\xbf"):
        _continuity_error("catalog_not_jcs")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContinuityCatalogError("catalog_not_json") from exc
    if _canonical_json_bytes(payload, error_code="catalog_not_jcs") != raw:
        _continuity_error("catalog_not_jcs")
    if not isinstance(payload, dict) or set(payload) != {
        "cards",
        "coverage_profile",
        "schema_version",
    }:
        _continuity_error("catalog_schema_invalid")
    if payload["schema_version"] != _CONTINUITY_CATALOG_SCHEMA:
        _continuity_error("catalog_schema_invalid")
    profile = payload["coverage_profile"]
    if not isinstance(profile, dict) or set(profile) != {
        "required_signatures",
        "schema_version",
    }:
        _continuity_error("coverage_profile_invalid")
    if profile["schema_version"] != _CONTINUITY_PROFILE_SCHEMA:
        _continuity_error("coverage_profile_invalid")
    required = profile["required_signatures"]
    if not isinstance(required, list) or not required:
        _continuity_error("coverage_profile_invalid")
    required_pairs = [
        _validated_coverage_signature(signature, error_code="coverage_profile_invalid")
        for signature in required
    ]
    required_signatures = [pair[1] for pair in required_pairs]
    if required_signatures != sorted(required_signatures) or len(required_signatures) != len(
        set(required_signatures)
    ):
        _continuity_error("coverage_profile_invalid")
    required_set = set(required_signatures)
    c0_signatures = set(_expanded_c0_signature_bytes())
    if not c0_signatures.issubset(required_set):
        _continuity_error("coverage_profile_missing_c0")
    for signature, canonical in required_pairs:
        if canonical not in c0_signatures and signature["representation"] == "variable_closure":
            _continuity_error("coverage_profile_invalid")

    raw_cards = payload["cards"]
    if not isinstance(raw_cards, list) or not raw_cards or len(raw_cards) > _MAX_ROWS:
        _continuity_error("catalog_cards_invalid")
    cards: list[ContinuityCatalogCard] = []
    draft_ids: list[str] = []
    openmath_values: list[str] = []
    novelty_keys: list[str] = []
    card_signatures: list[bytes] = []
    for card in raw_cards:
        if not isinstance(card, dict) or set(card) != _CONTINUITY_CARD_FIELDS:
            _continuity_error("catalog_card_schema_invalid")
        for name in _CONTINUITY_CARD_FIELDS - {"coverage", "sketch_steps"}:
            if not isinstance(card[name], str) or not card[name]:
                _continuity_error("catalog_card_schema_invalid")
        steps = card["sketch_steps"]
        if (
            not isinstance(steps, list)
            or not steps
            or any(not isinstance(step, str) or not step for step in steps)
        ):
            _continuity_error("catalog_card_schema_invalid")
        coverage, signature = _validated_coverage_signature(
            card["coverage"], error_code="catalog_card_schema_invalid"
        )
        draft_id = card["draft_id"]
        if (
            not _DRAFT_ID.fullmatch(draft_id)
            or card["english_expected_draft_id"] != draft_id
            or card["japanese_expected_draft_id"] != draft_id
            or card["hard_negative_expected_result"] != "no_match"
            or card["coverage_objective"] != coverage["topic"]
            or not _NOVELTY_KEY.fullmatch(card["novelty_key"])
        ):
            _continuity_error("catalog_card_contract_invalid")
        try:
            canonical_openmath = validate_canonical_retrieval_openmath_xml(
                card["openmath_xml"]
            )
        except MathXMLValidationError as exc:
            raise ContinuityCatalogError("catalog_openmath_invalid") from exc
        expected_novelty_key = "sha256:" + hashlib.sha256(
            _canonical_json_bytes(
                {
                    "coverage_signature": coverage,
                    "openmath_xml_sha256": "sha256:"
                    + hashlib.sha256(canonical_openmath.encode("utf-8")).hexdigest(),
                },
                error_code="catalog_card_contract_invalid",
            )
        ).hexdigest()
        if card["novelty_key"] != expected_novelty_key:
            _continuity_error("catalog_novelty_key_invalid")
        cards.append(ContinuityCatalogCard(draft_id, coverage, card))
        draft_ids.append(draft_id)
        openmath_values.append(card["openmath_xml"])
        novelty_keys.append(card["novelty_key"])
        card_signatures.append(signature)
    if draft_ids != sorted(draft_ids, key=lambda item: item.encode("utf-8")):
        _continuity_error("catalog_cards_unsorted")
    if len(draft_ids) != len(set(draft_ids)):
        _continuity_error("catalog_duplicate_draft_id")
    if len(openmath_values) != len(set(openmath_values)):
        _continuity_error("catalog_duplicate_openmath")
    if len(novelty_keys) != len(set(novelty_keys)):
        _continuity_error("catalog_duplicate_novelty")
    card_set = set(card_signatures)
    if card_set - required_set:
        _continuity_error("coverage_profile_incomplete")
    if not c0_signatures.issubset(card_set):
        _continuity_error("catalog_missing_c0")
    return ContinuityCatalog(
        schema_version=payload["schema_version"],
        cards=tuple(cards),
        required_signatures=tuple(pair[0] for pair in required_pairs),
    )


@dataclass(frozen=True, slots=True)
class CanonicalizerChildProperty:
    source_path: str
    source_sha256: str

    def __post_init__(self) -> None:
        segments = self.source_path.split("/")
        forbidden_roots = ("/proc", "/sys", "/dev", "/run", "/tmp")
        if (
            not self.source_path.startswith("/")
            or self.source_path.startswith("//")
            or "\x00" in self.source_path
            or any(segment in {"", ".", ".."} for segment in segments[1:])
            or str(PurePosixPath(self.source_path)) != self.source_path
            or self.source_path != _CONTAINER_ELEMENTTREE_PATH
            or any(
                self.source_path == root or self.source_path.startswith(f"{root}/")
                for root in forbidden_roots
            )
        ):
            raise SeedBuildError("PFI canonicalizer source path is invalid")
        if not _SHA256.fullmatch(self.source_sha256):
            raise SeedBuildError("PFI canonicalizer source digest is invalid")


def host_elementtree_source_sha256() -> str:
    path = Path(sysconfig.get_path("stdlib")) / "xml/etree/ElementTree.py"
    try:
        source_is_symlink = path.is_symlink()
        resolved = path.resolve(strict=True)
        mode = resolved.lstat().st_mode
        raw = resolved.read_bytes()
    except OSError as exc:
        raise SeedBuildError("PFI host ElementTree source is unreadable") from exc
    if source_is_symlink or not stat.S_ISREG(mode) or resolved.is_symlink():
        raise SeedBuildError("PFI host ElementTree source is invalid")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ParentPFIAuthorityGate:
    repository_root: Path

    def verify(self) -> None:
        bundle = self.repository_root / "specs" / "proof-flow-index"
        for name, expected in _PARENT_HASHES.items():
            path = bundle / name
            try:
                mode = path.lstat().st_mode
                raw = path.read_bytes()
            except OSError as exc:
                raise ParentPFIAuthorityError("approved parent PFI is unreadable") from exc
            if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                raise ParentPFIAuthorityError("approved parent PFI is not a regular file")
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ParentPFIAuthorityError("approved parent PFI hash mismatch")
            if name == "requirements.md":
                frontmatter = raw.split(b"---", 2)
                if len(frontmatter) != 3 or b"\nstatus: approved\n" not in frontmatter[1]:
                    raise ParentPFIAuthorityError("parent PFI status is not approved")


class SeedEmbeddingModel(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class SeedEmbeddingFingerprint:
    provider: str
    model: str
    endpoint: str
    deployment: str
    revision: str
    dimension: int
    canonicalizer_version: str

    def __post_init__(self) -> None:
        for value in (
            self.provider,
            self.model,
            self.endpoint,
            self.deployment,
            self.revision,
        ):
            if not value.strip() or len(value) > _MAX_TEXT:
                raise ValueError("embedding fingerprint string is invalid")
        if isinstance(self.dimension, bool) or not 1 <= self.dimension <= 4096:
            raise ValueError("embedding fingerprint dimension is invalid")
        if self.canonicalizer_version != _CANONICALIZER_VERSION:
            raise ValueError("embedding canonicalizer version is invalid")

    def as_json(self) -> dict[str, str | int]:
        return {
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "revision": self.revision,
            "dimension": self.dimension,
            "canonicalizer_version": self.canonicalizer_version,
        }


@dataclass(frozen=True, slots=True)
class SeedBuildArtifact:
    root: Path
    seed_file: Path
    seed_manifest_file: Path
    fingerprint_file: Path
    build_provenance_file: Path
    oci_labels_file: Path
    seed_manifest_sha256: str
    seed_count: int


@dataclass(frozen=True, slots=True)
class ProofDraftSeedBuilder:
    authority: ParentPFIAuthorityGate
    embedding_model: SeedEmbeddingModel
    fingerprint: SeedEmbeddingFingerprint
    canonicalizer_property: CanonicalizerChildProperty

    def build(
        self,
        *,
        drafts: tuple[ProofDraft, ...],
        destination: Path,
        source_commit: str,
    ) -> SeedBuildArtifact:
        self.authority.verify()
        if platform.python_version() != "3.12.13":
            raise SeedBuildError("PFI seed build requires exact CPython 3.12.13")
        if self.canonicalizer_property.source_sha256 != host_elementtree_source_sha256():
            raise SeedBuildError(
                "PFI final-image canonicalizer does not match the build interpreter"
            )
        if not _SOURCE_COMMIT.fullmatch(source_commit):
            raise SeedBuildError("PFI Agent source commit is invalid")
        if destination.exists() or destination.is_symlink():
            raise SeedBuildError("PFI publication destination already exists")
        if not destination.parent.is_dir() or destination.parent.is_symlink():
            raise SeedBuildError("PFI publication parent is not a real directory")

        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.",
                dir=destination.parent,
            )
        )
        os.chmod(temporary, 0o700)
        try:
            artifact = self._build_private(
                drafts=drafts,
                root=temporary,
                source_commit=source_commit,
            )
            os.replace(temporary, destination)
            return SeedBuildArtifact(
                root=destination,
                seed_file=destination / artifact.seed_file.relative_to(temporary),
                seed_manifest_file=(
                    destination / artifact.seed_manifest_file.relative_to(temporary)
                ),
                fingerprint_file=(destination / artifact.fingerprint_file.relative_to(temporary)),
                build_provenance_file=(
                    destination / artifact.build_provenance_file.relative_to(temporary)
                ),
                oci_labels_file=(destination / artifact.oci_labels_file.relative_to(temporary)),
                seed_manifest_sha256=artifact.seed_manifest_sha256,
                seed_count=artifact.seed_count,
            )
        except Exception as exc:
            if temporary.exists():
                shutil.rmtree(temporary)
            if isinstance(exc, ParentPFIAuthorityError | SeedBuildError):
                raise
            raise SeedBuildError("PFI seed build failed closed") from exc

    def _build_private(
        self,
        *,
        drafts: tuple[ProofDraft, ...],
        root: Path,
        source_commit: str,
    ) -> SeedBuildArtifact:
        if len(drafts) > _MAX_ROWS:
            raise SeedBuildError("PFI seed exceeds 4,096 rows")
        identities = [draft.id for draft in drafts]
        if len(identities) != len(set(identities)):
            raise SeedBuildError("PFI seed Draft IDs are not unique")
        candidates = [
            self._validate_row(draft)
            for draft in sorted(drafts, key=lambda item: item.id.encode("utf-8"))
        ]
        rows = [self._embed_candidate(candidate) for candidate in candidates]
        projection = [
            {key: value for key, value in row.items() if key != "embedding"} for row in rows
        ]
        manifest_bytes = rfc8785.dumps(projection)
        manifest_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
        fingerprint_bytes = rfc8785.dumps(self.fingerprint.as_json())
        seed_bytes = rfc8785.dumps(
            {
                "schema_version": "pals.draft-catalog-seed.v1",
                "fingerprint": self.fingerprint.as_json(),
                "rows": rows,
            }
        )
        if len(seed_bytes) > _MAX_SEED_BYTES:
            raise SeedBuildError("PFI seed exceeds its byte bound")

        provenance: dict[str, Any] = {
            "canonicalizer_version": _CANONICALIZER_VERSION,
            "elementtree_source_path": self.canonicalizer_property.source_path,
            "elementtree_source_sha256": self.canonicalizer_property.source_sha256,
            "property_id": "PFI-BP-001",
            "python_version": "3.12.13",
            "schema_version": "pals.draft-retrieval-build-provenance.v1",
            "seed_count": len(rows),
            "seed_file_sha256": hashlib.sha256(seed_bytes).hexdigest(),
            "seed_manifest_sha256": manifest_sha256,
            "seed_path": _SEED_PATH,
            "source_commit": source_commit,
        }
        provenance_bytes = rfc8785.dumps(provenance)
        labels = {
            _PROVENANCE_LABEL: base64.urlsafe_b64encode(provenance_bytes)
            .rstrip(b"=")
            .decode("ascii"),
            _PROVENANCE_DIGEST_LABEL: hashlib.sha256(provenance_bytes).hexdigest(),
        }
        labels_bytes = rfc8785.dumps(labels)

        seed_file = root / "rootfs" / _SEED_PATH.removeprefix("/")
        metadata = root / "metadata"
        seed_file.parent.mkdir(parents=True, mode=0o700)
        metadata.mkdir(mode=0o700)
        seed_manifest_file = metadata / "seed-manifest.json"
        fingerprint_file = metadata / "fingerprint.json"
        build_provenance_file = metadata / "build-provenance.json"
        oci_labels_file = metadata / "oci-labels.json"
        for path, value in (
            (seed_file, seed_bytes),
            (seed_manifest_file, manifest_bytes),
            (fingerprint_file, fingerprint_bytes),
            (build_provenance_file, provenance_bytes),
            (oci_labels_file, labels_bytes),
        ):
            _write_private_file(path, value)
        return SeedBuildArtifact(
            root=root,
            seed_file=seed_file,
            seed_manifest_file=seed_manifest_file,
            fingerprint_file=fingerprint_file,
            build_provenance_file=build_provenance_file,
            oci_labels_file=oci_labels_file,
            seed_manifest_sha256=manifest_sha256,
            seed_count=len(rows),
        )

    def _validate_row(self, draft: ProofDraft) -> dict[str, Any]:
        if not _DRAFT_ID.fullmatch(draft.id):
            raise SeedBuildError("PFI seed Draft ID is not retrieval eligible")
        for value in (
            draft.matched_prompt,
            draft.proof_strategy,
            *draft.sketch_steps,
        ):
            if not value.strip() or len(value) > _MAX_TEXT:
                raise SeedBuildError("PFI seed text field is invalid")
        if len(draft.sketch_steps) > _MAX_STEPS:
            raise SeedBuildError("PFI seed Sketch steps exceed the bound")
        try:
            validate_openmath_statement_semantics(
                draft.openmath_xml,
                draft.matched_prompt,
            )
            canonical = canonicalize_retrieval_openmath_xml(draft.openmath_xml)
        except MathXMLValidationError as exc:
            raise SeedBuildError("PFI seed OpenMath is invalid") from exc
        candidate: dict[str, Any] = {
            "id": draft.id,
            "canonical_statement": draft.matched_prompt,
            "openmath_xml": canonical,
            "proof_strategy": draft.proof_strategy,
            "sketch_steps": list(draft.sketch_steps),
        }
        if len(rfc8785.dumps(candidate)) > _MAX_CANDIDATE_BYTES:
            raise SeedBuildError("PFI seed candidate exceeds its aggregate bound")
        return candidate

    def _embed_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        try:
            embedding = _binary32_embedding(
                self.embedding_model.embed(candidate["openmath_xml"]),
                dimension=self.fingerprint.dimension,
            )
        except Exception as exc:
            if isinstance(exc, SeedBuildError):
                raise
            raise SeedBuildError("PFI seed embedding failed") from exc
        return {**candidate, "embedding": embedding}


def _binary32_embedding(value: object, *, dimension: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise SeedBuildError("PFI embedding dimension mismatch")
    converted: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, int | float):
            raise SeedBuildError("PFI embedding contains a non-number")
        numeric = float(component)
        if not math.isfinite(numeric):
            raise SeedBuildError("PFI embedding contains a non-finite number")
        try:
            binary32 = struct.unpack("!f", struct.pack("!f", numeric))[0]
        except (OverflowError, struct.error) as exc:
            raise SeedBuildError("PFI embedding is not finite binary32") from exc
        if not math.isfinite(binary32):
            raise SeedBuildError("PFI embedding is not finite binary32")
        converted.append(0.0 if binary32 == 0.0 else binary32)
    if not any(component != 0.0 for component in converted):
        raise SeedBuildError("PFI embedding has zero norm")
    return converted


def _write_private_file(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        written = 0
        while written < len(value):
            written += os.write(descriptor, value[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
