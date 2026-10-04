"""DCE typed candidate port. No DB capability and no cross-profile fallback."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import rfc8785

from pals_agent import typed_local_catalog as local
from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.models import ProofDraft
from pals_agent.private_draft_candidates import (
    DraftCandidate,
    DraftCandidateCompatibilityError,
    DraftCandidateUnavailableError,
    _bounded_int,
    _decode_json,
    _embedding,
    _exact_object,
    _finite_number,
    _header_values,
    _hex64,
    _text,
    _uuid4,
    _validate_api_base_url,
)


def profile_contract(profile_id: str) -> tuple[local._ProfileSpec, dict[str, Any]]:
    specs = [
        value
        for value in vars(local).values()
        if isinstance(value, local._ProfileSpec) and value.profile_id == profile_id
    ]
    if not specs:
        raise DraftCandidateCompatibilityError("Typed profile is unsupported.")
    spec = specs[0]
    root = Path(__file__).parent
    binding = dict(
        profile_id=profile_id,
        validator_sha256=hashlib.sha256(
            (root / Path(spec.validator_module_path).name).read_bytes()
        ).hexdigest(),
        registry_sha256=hashlib.sha256(
            (root / "content_dictionaries" / Path(spec.registry_path).name).read_bytes()
        ).hexdigest(),
        canonicalizer_version=local.TYPED_OPENMATH_CANONICALIZER_VERSION,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimension=384,
        embedding_revision="openai-release-2024-01-25",
        embedding_input_version=local.TYPED_EMBEDDING_INPUT_VERSION,
    )
    return spec, binding


@dataclass(frozen=True, slots=True)
class TypedCandidateResult:
    generation_id: str
    layout_sha256: str
    profile_id: str
    row_count: int
    candidates: tuple[DraftCandidate, ...]


@dataclass(frozen=True, slots=True)
class PrivateTypedCandidateClient:
    base_url: str
    worker_secret: str = field(repr=False)
    transport: HttpTransport = field(
        default_factory=lambda: HardDeadlineHttpTransport(max_response_bytes=262144), repr=False
    )

    evaluation_generation_id: str | None = None

    def __post_init__(self) -> None:
        _validate_api_base_url(self.base_url)
        if self.evaluation_generation_id is not None:
            _uuid4(self.evaluation_generation_id)
        if (
            not self.worker_secret.strip()
            or "\n" in self.worker_secret
            or "\r" in self.worker_secret
        ):
            raise ValueError("Worker secret invalid")

    def find_candidates(
        self, *, profile_id: str, query_openmath: str, embedding: list[float]
    ) -> TypedCandidateResult:
        spec, binding = profile_contract(profile_id)
        try:
            spec.validate_canonical(query_openmath)
            vector = _embedding(embedding, dimension=384)
        except ValueError as error:
            raise DraftCandidateCompatibilityError("Typed query incompatible.") from error
        payload = dict(
            schema_version="pals.typed-draft-candidate-query.v1", binding=binding, embedding=vector
        )
        path = "/v1/internal/typed-catalog/candidates"
        header = "X-PALS-Worker-Secret"
        if self.evaluation_generation_id:
            payload["schema_version"] = "pals.typed-draft-evaluation-query.v1"
            payload["generation_id"] = self.evaluation_generation_id
            path = "/v1/internal/typed-catalog/evaluation-candidates"
            header = "X-PALS-Release-Secret"
        try:
            response = self.transport.request(
                method="POST",
                url=self.base_url.rstrip("/") + path,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    header: self.worker_secret,
                },
                body=rfc8785.dumps(cast(Any, payload)),
                timeout_seconds=10.0,
            )
        except HardDeadlineHttpError as error:
            raise DraftCandidateUnavailableError("Typed retrieval unavailable.") from error
        if response.status_code == 503:
            raise DraftCandidateUnavailableError("Typed retrieval unavailable.")
        if (
            response.status_code != 200
            or len(response.body) > 262144
            or _header_values(response.headers, "content-type") != ("application/json",)
        ):
            raise DraftCandidateCompatibilityError("Typed response incompatible.")
        try:
            value = _exact_object(
                _decode_json(response.body),
                {
                    "schema_version",
                    "generation_id",
                    "layout_sha256",
                    "binding",
                    "row_count",
                    "candidates",
                },
            )
            if (
                value["schema_version"] != "pals.typed-draft-candidate-result.v1"
                or value["binding"] != binding
            ):
                raise ValueError("binding mismatch")
            if (
                self.evaluation_generation_id
                and value["generation_id"] != self.evaluation_generation_id
            ):
                raise ValueError("evaluation generation mismatch")
            count = _bounded_int(value["row_count"], minimum=1, maximum=4096)
            rows = value["candidates"]
            if not isinstance(rows, list) or len(rows) != min(8, count):
                raise ValueError("candidate count mismatch")
            candidates = []
            for raw in rows:
                row = _exact_object(raw, {"draft", "cosine_distance"})
                draft = _exact_object(
                    row["draft"],
                    {"id", "canonical_statement", "openmath_xml", "proof_strategy", "sketch_steps"},
                )
                xml = spec.validate_canonical(_text(draft["openmath_xml"]))
                steps = draft["sketch_steps"]
                if (
                    not isinstance(steps, list)
                    or not 1 <= len(steps) <= 256
                    or len(rfc8785.dumps(cast(Any, draft))) > 16384
                ):
                    raise ValueError("candidate bounds")
                if not isinstance(draft["id"], str) or not re.fullmatch(
                    r"[a-z][a-z0-9_]{0,63}", draft["id"]
                ):
                    raise ValueError("candidate ID invalid")
                distance = _finite_number(row["cosine_distance"])
                if not 0 <= distance <= 2:
                    raise ValueError("candidate distance")
                candidates.append(
                    DraftCandidate(
                        ProofDraft(
                            id=_text(draft["id"]),
                            matched_prompt=_text(draft["canonical_statement"]),
                            openmath_xml=xml,
                            proof_strategy=_text(draft["proof_strategy"]),
                            sketch_steps=tuple(_text(v) for v in steps),
                        ),
                        distance,
                    )
                )
            ids = [item.draft.id for item in candidates]
            if len(set(ids)) != len(ids) or candidates != sorted(
                candidates, key=lambda item: (item.cosine_distance, item.draft.id.encode())
            ):
                raise ValueError("candidate order/identities")
            return TypedCandidateResult(
                _uuid4(value["generation_id"]),
                _hex64(value["layout_sha256"]),
                profile_id,
                count,
                tuple(candidates),
            )
        except (TypeError, ValueError) as error:
            raise DraftCandidateCompatibilityError("Typed response incompatible.") from error
