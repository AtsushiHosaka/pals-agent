"""Closed, authenticated Agent boundary for Lean Recipe selection.

This module deliberately owns no catalog persistence or Recipe materialization.  It sends a
bounded request to the API-owned catalog and exposes a selection only after authenticating and
cross-checking every immutable binding returned by that service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import rfc8785

from pals_agent.http_transport import (
    HardDeadlineHttpError,
    HardDeadlineHttpTransport,
    HttpTransport,
)
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.openmath_v4_contract import (
    OpenMathV4ContractError,
    require_openmath_c14n_v4_contract,
)

_PATH = "/v1/internal/lean-recipe-catalog/selections"
_QUERY_SCHEMA_VERSION = "pals.recipe-selection-query.v1"
_RESULT_SCHEMA_VERSION = "pals.recipe-selection-result.v1"
_TOOLCHAIN_SCHEMA_VERSION = "pals.lean-toolchain-fingerprint.v1"
_DRAFT_CATALOG_ID = "pals.draft-candidate-result.v1"
_DRAFT_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v4"
_MAX_REQUEST_BYTES = 32 * 1024
_MAX_RESPONSE_BYTES = 512 * 1024
_MAX_TARGET_CODE_POINTS = 20_000
_MAX_SOURCE_CODE_POINTS = 480_000
_MAX_TEXT_CODE_POINTS = 20_000
_MAX_EXCLUSIONS = 64
_NONCE_RETENTION_SECONDS = 600.0
_HEX64 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_NONCE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_DRAFT_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,127}$", re.ASCII)
_CATALOG_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$", re.ASCII)
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$", re.ASCII)
_PRINCIPAL_PREFIX = "pals.principal.v1/"
_DECLARATION_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_'.]*", re.ASCII)
_PROOF_DECLARATION = re.compile(r"(?:theorem|lemma|example)\b")
_OUTER_CONTEXT_COMMAND = re.compile(r"(?m)^[ \t]*(?:universe|variable)\b")


class RecipeSelectionUnavailableError(RuntimeError):
    """The authenticated Recipe-selection boundary cannot safely yield a result."""


@dataclass(frozen=True, slots=True)
class DraftRevisionReference:
    """The immutable five-field PFI projection a Recipe alignment may reference."""

    draft_id: str
    draft_payload_sha256: str
    catalog_id: str = _DRAFT_CATALOG_ID
    canonicalizer_version: str = _DRAFT_CANONICALIZER_VERSION

    def __post_init__(self) -> None:
        if self.catalog_id != _DRAFT_CATALOG_ID:
            raise ValueError("Draft catalog ID is invalid")
        if self.canonicalizer_version != _DRAFT_CANONICALIZER_VERSION:
            raise ValueError("Draft canonicalizer version is invalid")
        _require_draft_identifier(self.draft_id, "Draft ID")
        _require_hex64(self.draft_payload_sha256, "Draft payload digest")

    def as_json(self) -> dict[str, str]:
        return {
            "catalog_id": self.catalog_id,
            "draft_id": self.draft_id,
            "draft_payload_sha256": self.draft_payload_sha256,
            "canonicalizer_version": self.canonicalizer_version,
        }


@dataclass(frozen=True, slots=True)
class ClosedRecipeHeaderV1:
    """A v1 proof declaration whose outer header cannot carry ambient binders."""

    kind: Literal["theorem", "lemma", "example"]
    name: str | None
    target_source: str

    @classmethod
    def extract(cls, declaration_source: str) -> ClosedRecipeHeaderV1 | None:
        """Use the existing extractor only after rejecting a non-closed declaration header."""
        if not isinstance(declaration_source, str) or not declaration_source.strip():
            return None
        target = extract_single_target_declaration(declaration_source)
        if target is None:
            return None
        masked = _mask_lean_comments_and_literals(declaration_source)
        declarations = _top_level_proof_declarations(masked)
        if len(declarations) != 1:
            return None
        declaration = declarations[0]
        if _OUTER_CONTEXT_COMMAND.search(masked[: declaration.start()]) is not None:
            return None
        raw_kind = declaration.group(0)
        if raw_kind not in {"theorem", "lemma", "example"}:
            return None
        kind = cast(Literal["theorem", "lemma", "example"], raw_kind)
        index = _skip_whitespace(masked, declaration.end())
        if kind == "example":
            name: str | None = None
        else:
            name_match = _DECLARATION_NAME.match(masked, index)
            if name_match is None:
                return None
            name = name_match.group(0)
            index = _skip_whitespace(masked, name_match.end())
        # The only permitted bytes before the type colon are the declaration keyword and, where
        # applicable, a bare name.  This rejects explicit/implicit/typeclass and universe binders.
        if index >= len(masked) or masked[index] != ":" or masked.startswith(":=", index):
            return None
        if target.kind != kind or target.name != name:
            return None
        return cls(kind=kind, name=name, target_source=target.proposition)


@dataclass(frozen=True, slots=True, init=False)
class FormalTarget:
    """Exact target bytes produced only from a validated closed Lean declaration."""

    target_source: str
    target_sha256: str

    def __init__(self, target_source: str, target_sha256: str) -> None:
        del target_source, target_sha256
        raise TypeError("FormalTarget must be extracted from a closed Lean declaration")

    @classmethod
    def from_declaration(cls, declaration_source: str) -> FormalTarget | None:
        header = ClosedRecipeHeaderV1.extract(declaration_source)
        if header is None:
            return None
        instance = object.__new__(cls)
        object.__setattr__(instance, "target_source", header.target_source)
        object.__setattr__(instance, "target_sha256", _sha256_utf8(header.target_source))
        return instance

    def as_json(self) -> dict[str, str]:
        return {
            "target_source": self.target_source,
            "target_sha256": self.target_sha256,
        }


@dataclass(frozen=True, slots=True)
class ToolchainFingerprintV1:
    """The complete active verifier fingerprint required for exact Recipe selection."""

    lean_version: str
    lake_manifest_sha256: str
    verifier_sha256: str
    materializer_version: str
    schema_version: str = _TOOLCHAIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _TOOLCHAIN_SCHEMA_VERSION:
            raise ValueError("toolchain fingerprint schema version is invalid")
        _require_text(self.lean_version, "Lean version")
        _require_hex64(self.lake_manifest_sha256, "lake manifest digest")
        _require_hex64(self.verifier_sha256, "verifier digest")
        _require_text(self.materializer_version, "materializer version")

    def as_json(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "lean_version": self.lean_version,
            "lake_manifest_sha256": self.lake_manifest_sha256,
            "verifier_sha256": self.verifier_sha256,
            "materializer_version": self.materializer_version,
        }

    @property
    def sha256(self) -> str:
        return _sha256_jcs(self.as_json())


@dataclass(frozen=True, slots=True)
class RecipeSelectionQuery:
    """Closed inputs for one keyed catalog lookup.

    ``formal_target`` and ``draft_revision`` are independently optional.  The API records a
    no-selection result when neither is available; this client does not invent either one.
    """

    toolchain_fingerprint: ToolchainFingerprintV1
    formal_target: FormalTarget | None = None
    draft_revision: DraftRevisionReference | None = None
    proof_method_tag: str | None = None
    proof_job_id: str | None = None
    mutation_claim_id: str | None = None

    def __post_init__(self) -> None:
        if (self.proof_job_id is None) != (self.mutation_claim_id is None):
            raise ValueError("selection claim binding is incomplete")
        if not isinstance(self.toolchain_fingerprint, ToolchainFingerprintV1):
            raise ValueError("toolchain fingerprint is invalid")
        if self.formal_target is not None and not isinstance(self.formal_target, FormalTarget):
            raise ValueError("formal target is invalid")
        if self.draft_revision is not None and not isinstance(
            self.draft_revision, DraftRevisionReference
        ):
            raise ValueError("Draft revision reference is invalid")
        if self.proof_method_tag is not None:
            _require_reason_code(self.proof_method_tag, "proof method tag")

    def as_json(self, *, request_nonce: str) -> dict[str, object]:
        _require_nonce(request_nonce)
        return {
            "schema_version": _QUERY_SCHEMA_VERSION,
            "request_nonce": request_nonce,
            "formal_target": (None if self.formal_target is None else self.formal_target.as_json()),
            "draft_revision": (
                None if self.draft_revision is None else self.draft_revision.as_json()
            ),
            "proof_method_tag": self.proof_method_tag,
            "toolchain_fingerprint": self.toolchain_fingerprint.as_json(),
        }


@dataclass(frozen=True, slots=True)
class RecipeSelected:
    recipe_id: str
    recipe_revision: int
    alignment_id: str | None
    alignment_revision: int | None
    target_sha256: str
    materialized_source: str
    materialized_source_sha256: str
    toolchain_fingerprint: ToolchainFingerprintV1
    toolchain_fingerprint_sha256: str
    compiler_receipt_sha256: str
    source_author_principal: str
    selection_payload_sha256: str
    selection_receipt_sha256: str

    @property
    def materialized_source_bytes(self) -> bytes:
        """Return the exact UTF-8 bytes the API authenticated; do not normalize source text."""
        return self.materialized_source.encode("utf-8")


@dataclass(frozen=True, slots=True)
class RecipeExclusion:
    reason_code: str
    recipe_id: str | None
    recipe_revision: int | None


@dataclass(frozen=True, slots=True)
class RecipeNotSelected:
    exclusions: tuple[RecipeExclusion, ...]
    request_sha256: str | None = None


type RecipeSelection = RecipeSelected | RecipeNotSelected


@dataclass(slots=True)
class _NonceReplayGuard:
    """Retain every issued nonce throughout the receipt-admission window."""

    clock: Callable[[], float] = field(default=monotonic, repr=False, compare=False)
    _expiry_by_nonce: dict[str, float] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def claim(self, nonce: str) -> bool:
        _require_nonce(nonce)
        with self._lock:
            now = _monotonic_now(self.clock)
            expired = [
                issued_nonce
                for issued_nonce, expiry in self._expiry_by_nonce.items()
                if expiry <= now
            ]
            for issued_nonce in expired:
                del self._expiry_by_nonce[issued_nonce]
            if nonce in self._expiry_by_nonce:
                return False
            self._expiry_by_nonce[nonce] = now + _NONCE_RETENTION_SECONDS
            return True


def _new_nonce() -> str:
    return secrets.token_hex(32)


@dataclass(slots=True)
class PrivateRecipeSelectionClient:
    """The Agent's only selection path; it has no catalog or database behavior."""

    base_url: str
    worker_secret: str
    allow_local_http: bool = False
    transport: HttpTransport = field(
        default_factory=lambda: HardDeadlineHttpTransport(max_response_bytes=_MAX_RESPONSE_BYTES),
        repr=False,
        compare=False,
    )
    nonce_factory: Callable[[], str] = field(default=_new_nonce, repr=False, compare=False)
    nonce_clock: Callable[[], float] = field(default=monotonic, repr=False, compare=False)
    _nonce_guard: _NonceReplayGuard = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validate_api_base_url(self.base_url, allow_local_http=self.allow_local_http)
        if (
            not isinstance(self.worker_secret, str)
            or not self.worker_secret.strip()
            or "\n" in self.worker_secret
            or "\r" in self.worker_secret
        ):
            raise ValueError("Recipe worker secret is invalid")
        try:
            self.worker_secret.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Recipe worker secret is invalid") from exc
        if not callable(self.nonce_factory):
            raise ValueError("Recipe nonce factory is invalid")
        if not callable(self.nonce_clock):
            raise ValueError("Recipe nonce clock is invalid")
        self._nonce_guard = _NonceReplayGuard(clock=self.nonce_clock)

    def select(self, query: RecipeSelectionQuery) -> RecipeSelection:
        if not isinstance(query, RecipeSelectionQuery):
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.")
        if query.draft_revision is not None:
            try:
                require_openmath_c14n_v4_contract()
            except OpenMathV4ContractError:
                raise RecipeSelectionUnavailableError("Recipe selection is unavailable.") from None
        try:
            request_nonce = self.nonce_factory()
            _require_nonce(request_nonce)
        except (TypeError, ValueError):
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.") from None
        try:
            nonce_claimed = self._nonce_guard.claim(request_nonce)
        except Exception:
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.") from None
        if not nonce_claimed:
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.")

        try:
            payload = query.as_json(request_nonce=request_nonce)
            body = rfc8785.dumps(cast(Any, payload))
        except (TypeError, ValueError):
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.") from None
        if len(body) > _MAX_REQUEST_BYTES:
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.")
        request_sha256 = _sha256_bytes(body)

        try:
            response = self.transport.request(
                method="POST",
                url=self.base_url.rstrip("/") + _PATH,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-PALS-Recipe-Worker-Secret": self.worker_secret,
                    **(
                        {
                            "X-PALS-Proof-Job-Id": query.proof_job_id,
                            "X-PALS-Mutation-Claim-Id": query.mutation_claim_id,
                        }
                        if query.proof_job_id is not None and query.mutation_claim_id is not None
                        else {}
                    ),
                },
                body=body,
                timeout_seconds=10.0,
            )
        except HardDeadlineHttpError:
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.") from None

        if response.status_code != 200:
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.")
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.")
        if _header_values(response.headers, "content-type") != ("application/json",):
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.")
        try:
            decoded = _decode_json(response.body)
            if rfc8785.dumps(cast(Any, decoded)) != response.body:
                raise ValueError("Recipe selection response is not RFC 8785 canonical")
            return _selection_result(
                decoded,
                request_nonce=request_nonce,
                request_sha256=request_sha256,
                query=query,
                worker_secret=self.worker_secret,
            )
        except (TypeError, ValueError):
            raise RecipeSelectionUnavailableError("Recipe selection is unavailable.") from None


def _selection_result(
    value: object,
    *,
    request_nonce: str,
    request_sha256: str,
    query: RecipeSelectionQuery,
    worker_secret: str,
) -> RecipeSelection:
    root = _exact_object(
        value,
        {
            "schema_version",
            "status",
            "request_nonce",
            "request_sha256",
            "response_mac_sha256",
            "selection",
            "exclusions",
        },
    )
    if root["schema_version"] != _RESULT_SCHEMA_VERSION:
        raise ValueError("Recipe selection result schema is invalid")
    if root["status"] not in {"selected", "not_selected"}:
        raise ValueError("Recipe selection status is invalid")
    if root["request_nonce"] != request_nonce:
        raise ValueError("Recipe selection nonce does not match")
    if root["request_sha256"] != request_sha256:
        raise ValueError("Recipe selection request digest does not match")
    response_mac_sha256 = _require_hex64(root["response_mac_sha256"], "Recipe response MAC")
    unsigned = {key: item for key, item in root.items() if key != "response_mac_sha256"}
    expected_mac = hmac.new(
        worker_secret.encode("utf-8"),
        request_sha256.encode("ascii") + rfc8785.dumps(cast(Any, unsigned)),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(response_mac_sha256, expected_mac):
        raise ValueError("Recipe response MAC does not match")

    if root["status"] == "selected":
        if root["exclusions"] is not None:
            raise ValueError("selected Recipe response includes exclusions")
        return _selected(root["selection"], query=query)
    if root["selection"] is not None:
        raise ValueError("not-selected Recipe response includes a selection")
    return RecipeNotSelected(
        exclusions=_exclusions(root["exclusions"]), request_sha256=request_sha256
    )


def _selected(value: object, *, query: RecipeSelectionQuery) -> RecipeSelected:
    root = _exact_object(
        value,
        {
            "recipe_id",
            "recipe_revision",
            "alignment_id",
            "alignment_revision",
            "target_sha256",
            "materialized_source",
            "materialized_source_sha256",
            "toolchain_fingerprint",
            "toolchain_fingerprint_sha256",
            "compiler_receipt_sha256",
            "source_author_principal",
            "selection_payload_sha256",
            "selection_receipt_sha256",
        },
    )
    recipe_id = _require_catalog_identifier(root["recipe_id"], "Recipe ID")
    recipe_revision = _require_positive_int(root["recipe_revision"], "Recipe revision")
    alignment_id = _nullable_catalog_identifier(root["alignment_id"], "alignment ID")
    alignment_revision = _nullable_positive_int(root["alignment_revision"], "alignment revision")
    if (alignment_id is None) != (alignment_revision is None):
        raise ValueError("Recipe alignment identity is incomplete")
    if query.draft_revision is not None and alignment_id is None:
        raise ValueError("Draft-based selection lacks an alignment")
    target_sha256 = _require_hex64(root["target_sha256"], "Recipe target digest")
    if query.formal_target is not None and target_sha256 != query.formal_target.target_sha256:
        raise ValueError("Recipe target digest does not match formal target")
    materialized_source = _require_source(root["materialized_source"])
    materialized_source_sha256 = _require_hex64(
        root["materialized_source_sha256"],
        "materialized source digest",
    )
    if _sha256_utf8(materialized_source) != materialized_source_sha256:
        raise ValueError("materialized source digest does not match source")
    toolchain_fingerprint = _toolchain_from_value(root["toolchain_fingerprint"])
    if toolchain_fingerprint != query.toolchain_fingerprint:
        raise ValueError("Recipe toolchain fingerprint does not match request")
    toolchain_fingerprint_sha256 = _require_hex64(
        root["toolchain_fingerprint_sha256"],
        "toolchain fingerprint digest",
    )
    if toolchain_fingerprint.sha256 != toolchain_fingerprint_sha256:
        raise ValueError("toolchain fingerprint digest does not match fingerprint")
    compiler_receipt_sha256 = _require_hex64(
        root["compiler_receipt_sha256"],
        "compiler receipt digest",
    )
    source_author_principal = _require_principal(root["source_author_principal"])
    selection_payload_sha256 = _require_hex64(
        root["selection_payload_sha256"],
        "selection payload digest",
    )
    selection_receipt_sha256 = _require_hex64(
        root["selection_receipt_sha256"],
        "selection receipt digest",
    )
    selected_preimage = {
        key: item
        for key, item in root.items()
        if key not in {"selection_payload_sha256", "selection_receipt_sha256"}
    }
    if _sha256_jcs(selected_preimage) != selection_payload_sha256:
        raise ValueError("selection payload digest does not match selected DTO")
    return RecipeSelected(
        recipe_id=recipe_id,
        recipe_revision=recipe_revision,
        alignment_id=alignment_id,
        alignment_revision=alignment_revision,
        target_sha256=target_sha256,
        materialized_source=materialized_source,
        materialized_source_sha256=materialized_source_sha256,
        toolchain_fingerprint=toolchain_fingerprint,
        toolchain_fingerprint_sha256=toolchain_fingerprint_sha256,
        compiler_receipt_sha256=compiler_receipt_sha256,
        source_author_principal=source_author_principal,
        selection_payload_sha256=selection_payload_sha256,
        selection_receipt_sha256=selection_receipt_sha256,
    )


def _exclusions(value: object) -> tuple[RecipeExclusion, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= _MAX_EXCLUSIONS:
        raise ValueError("Recipe exclusions are invalid")
    exclusions: list[RecipeExclusion] = []
    for item in value:
        root = _exact_object(item, {"reason_code", "recipe_id", "recipe_revision"})
        recipe_id = _nullable_catalog_identifier(root["recipe_id"], "excluded Recipe ID")
        recipe_revision = _nullable_positive_int(
            root["recipe_revision"],
            "excluded Recipe revision",
        )
        if (recipe_id is None) != (recipe_revision is None):
            raise ValueError("excluded Recipe identity is incomplete")
        exclusions.append(
            RecipeExclusion(
                reason_code=_require_reason_code(root["reason_code"], "exclusion reason"),
                recipe_id=recipe_id,
                recipe_revision=recipe_revision,
            )
        )
    if len(set(exclusions)) != len(exclusions):
        raise ValueError("Recipe exclusions are duplicated")
    return tuple(exclusions)


def _toolchain_from_value(value: object) -> ToolchainFingerprintV1:
    root = _exact_object(
        value,
        {
            "schema_version",
            "lean_version",
            "lake_manifest_sha256",
            "verifier_sha256",
            "materializer_version",
        },
    )
    return ToolchainFingerprintV1(
        schema_version=cast(str, root["schema_version"]),
        lean_version=cast(str, root["lean_version"]),
        lake_manifest_sha256=cast(str, root["lake_manifest_sha256"]),
        verifier_sha256=cast(str, root["verifier_sha256"]),
        materializer_version=cast(str, root["materializer_version"]),
    )


def _mask_lean_comments_and_literals(source: str) -> str:
    """Replace non-code Lean text with spaces while preserving declaration offsets."""
    masked = list(source)
    index = 0
    block_depth = 0
    in_string = False
    in_quoted_identifier = False
    escaped = False
    while index < len(source):
        if block_depth > 0:
            if source.startswith("/-", index):
                masked[index : index + 2] = (" ", " ")
                block_depth += 1
                index += 2
            elif source.startswith("-/", index):
                masked[index : index + 2] = (" ", " ")
                block_depth -= 1
                index += 2
            else:
                if source[index] != "\n":
                    masked[index] = " "
                index += 1
            continue
        if in_quoted_identifier:
            character = source[index]
            if character != "\n":
                masked[index] = " "
            index += 1
            if character == "»":
                in_quoted_identifier = False
            continue
        if in_string:
            character = source[index]
            if character != "\n":
                masked[index] = " "
            index += 1
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if source.startswith("--", index):
            line_end = source.find("\n", index + 2)
            if line_end < 0:
                line_end = len(source)
            for comment_index in range(index, line_end):
                masked[comment_index] = " "
            index = line_end
            continue
        if source.startswith("/-", index):
            masked[index : index + 2] = (" ", " ")
            block_depth = 1
            index += 2
            continue
        character = source[index]
        if character == '"':
            masked[index] = " "
            in_string = True
        elif character == "«":
            masked[index] = " "
            in_quoted_identifier = True
        index += 1
    return "".join(masked)


def _top_level_proof_declarations(source: str) -> list[re.Match[str]]:
    declarations: list[re.Match[str]] = []
    depth = 0
    index = 0
    while index < len(source):
        character = source[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            declaration = _PROOF_DECLARATION.match(source, index)
            if declaration is not None and (
                index == 0 or not (source[index - 1].isalnum() or source[index - 1] == "_")
            ):
                declarations.append(declaration)
                index = declaration.end()
                continue
        index += 1
    return declarations


def _skip_whitespace(source: str, index: int) -> int:
    while index < len(source) and source[index].isspace():
        index += 1
    return index


class _JsonPairs(list[tuple[str, Any]]):
    pass


def _decode_json(raw: bytes) -> object:
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_JsonPairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Recipe selection response is not valid JSON") from exc
    return _reject_duplicate_members(decoded)


def _reject_duplicate_members(value: object) -> object:
    if isinstance(value, _JsonPairs):
        result: dict[str, object] = {}
        for key, child in value:
            if key in result:
                raise ValueError("Recipe selection response has duplicate members")
            result[key] = _reject_duplicate_members(child)
        return result
    if isinstance(value, list):
        return [_reject_duplicate_members(item) for item in value]
    return value


def _exact_object(value: object, expected: set[str]) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or not all(isinstance(key, str) for key in value)
    ):
        raise ValueError("Recipe selection object does not match the closed DTO")
    return value


def _validate_api_base_url(value: str, *, allow_local_http: bool = False) -> None:
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() or ord(character) < 0x20 for character in value)
    ):
        raise ValueError("Recipe API base URL must be an absolute HTTPS origin")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ValueError("Recipe API base URL must be an absolute HTTPS origin") from exc
    if (
        not (
            parts.scheme == "https"
            or allow_local_http is True
            and value.rstrip("/")
            in {"http://api:8000", "http://localhost:8000", "http://127.0.0.1:8000"}
        )
        or parts.hostname is None
        or port is not None
        and not 1 <= port <= 65_535
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("Recipe API base URL must be an absolute HTTPS origin")


def _require_text(value: object, label: str, *, maximum: int = _MAX_TEXT_CODE_POINTS) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} is invalid") from exc
    return value


def _require_source(value: object) -> str:
    source = _require_text(value, "materialized source", maximum=_MAX_SOURCE_CODE_POINTS)
    if "\x00" in source:
        raise ValueError("materialized source is invalid")
    return source


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _require_nonce(value: object) -> str:
    if not isinstance(value, str) or _NONCE.fullmatch(value) is None:
        raise ValueError("Recipe request nonce is invalid")
    return value


def _require_draft_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _DRAFT_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _require_catalog_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _CATALOG_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _nullable_catalog_identifier(value: object, label: str) -> str | None:
    return None if value is None else _require_catalog_identifier(value, label)


def _require_reason_code(value: object, label: str) -> str:
    if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError(f"{label} is invalid")
    return value


def _nullable_positive_int(value: object, label: str) -> int | None:
    return None if value is None else _require_positive_int(value, label)


def _require_principal(value: object) -> str:
    principal = _require_text(value, "source author principal")
    if not principal.startswith(_PRINCIPAL_PREFIX):
        raise ValueError("source author principal is invalid")
    return principal


def _monotonic_now(clock: Callable[[], float]) -> float:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Recipe nonce clock is invalid")
    return float(value)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_utf8(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_jcs(value: object) -> str:
    return _sha256_bytes(rfc8785.dumps(cast(Any, value)))


def _header_values(headers: tuple[tuple[str, str], ...], name: str) -> tuple[str, ...]:
    return tuple(value for key, value in headers if key.lower() == name)
