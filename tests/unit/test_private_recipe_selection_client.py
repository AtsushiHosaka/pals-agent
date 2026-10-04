from __future__ import annotations

import copy
import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any, cast

import pytest
import rfc8785

from pals_agent.http_transport import HttpResponse, HttpTransportError
from pals_agent.private_recipe_selection import (
    ClosedRecipeHeaderV1,
    DraftRevisionReference,
    FormalTarget,
    PrivateRecipeSelectionClient,
    RecipeNotSelected,
    RecipeSelected,
    RecipeSelectionQuery,
    RecipeSelectionUnavailableError,
    ToolchainFingerprintV1,
)

_SECRET = "recipe-worker-secret"
_NONCE = "a" * 64


def _formal_target(declaration_source: str) -> FormalTarget:
    target = FormalTarget.from_declaration(declaration_source)
    assert target is not None
    return target


_TARGET = _formal_target("example : Continuous (fun x : ℝ => x ^ 2) := by\n  fun_prop\n")
_TOOLCHAIN = ToolchainFingerprintV1(
    lean_version="v4.19.0",
    lake_manifest_sha256="b" * 64,
    verifier_sha256="c" * 64,
    materializer_version="recipe-materializer-v1",
)
_DRAFT = DraftRevisionReference(
    draft_id="continuous_square",
    draft_payload_sha256="d" * 64,
)
_QUERY = RecipeSelectionQuery(
    formal_target=_TARGET,
    draft_revision=_DRAFT,
    proof_method_tag="explicit_epsilon_delta",
    toolchain_fingerprint=_TOOLCHAIN,
)


class RecordingTransport:
    def __init__(
        self,
        *,
        status_code: int = 200,
        body: bytes,
        headers: tuple[tuple[str, str], ...] = (("Content-Type", "application/json"),),
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return HttpResponse(
            status_code=self.status_code,
            body=self.body,
            headers=self.headers,
        )


class TransportThatMustNotRun:
    def request(self, **kwargs: Any) -> HttpResponse:
        del kwargs
        pytest.fail("Recipe selection transport must not run")


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _sha256_jcs(value: object) -> str:
    return hashlib.sha256(rfc8785.dumps(cast(Any, value))).hexdigest()


def _selected_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recipe_id": "continuous_square_explicit_eps_delta",
        "recipe_revision": 1,
        "alignment_id": "continuous_square_alignment",
        "alignment_revision": 1,
        "target_sha256": _TARGET.target_sha256,
        "materialized_source": (
            "import Mathlib\n\nexample : Continuous (fun x : ℝ => x ^ 2) := by\n  fun_prop\n"
        ),
        "materialized_source_sha256": "",
        "toolchain_fingerprint": _TOOLCHAIN.as_json(),
        "toolchain_fingerprint_sha256": _TOOLCHAIN.sha256,
        "compiler_receipt_sha256": "e" * 64,
        "source_author_principal": "pals.principal.v1/recipe-author/continuous-square",
        "selection_payload_sha256": "",
        "selection_receipt_sha256": "f" * 64,
    }
    payload["materialized_source_sha256"] = hashlib.sha256(
        payload["materialized_source"].encode("utf-8")
    ).hexdigest()
    payload["selection_payload_sha256"] = _sha256_jcs(
        {
            key: value
            for key, value in payload.items()
            if key not in {"selection_payload_sha256", "selection_receipt_sha256"}
        }
    )
    return payload


def _selection_with_catalog_ids(*, recipe_id: str, alignment_id: str | None) -> dict[str, Any]:
    payload = _selected_payload()
    payload["recipe_id"] = recipe_id
    payload["alignment_id"] = alignment_id
    payload["alignment_revision"] = None if alignment_id is None else 1
    payload["selection_payload_sha256"] = _sha256_jcs(
        {
            key: value
            for key, value in payload.items()
            if key not in {"selection_payload_sha256", "selection_receipt_sha256"}
        }
    )
    return payload


def _response(
    *,
    request: dict[str, Any],
    status: str = "selected",
    selection: dict[str, Any] | None = None,
    exclusions: list[dict[str, Any]] | None = None,
) -> bytes:
    root: dict[str, Any] = {
        "schema_version": "pals.recipe-selection-result.v1",
        "status": status,
        "request_nonce": request["request_nonce"],
        "request_sha256": hashlib.sha256(rfc8785.dumps(request)).hexdigest(),
        "selection": (
            _selected_payload() if selection is None and status == "selected" else selection
        ),
        "exclusions": None if status == "selected" else exclusions,
    }
    root["response_mac_sha256"] = hmac.new(
        _SECRET.encode("utf-8"),
        root["request_sha256"].encode("ascii") + rfc8785.dumps(root),
        hashlib.sha256,
    ).hexdigest()
    return rfc8785.dumps(cast(Any, root))


class _RequestAwareTransport:
    def __init__(
        self,
        *,
        mutate: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.mutate = mutate
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        request = json.loads(kwargs["body"].decode("utf-8"))
        body = _response(request=request)
        if self.mutate is not None:
            root = json.loads(body.decode("utf-8"))
            self.mutate(root)
            body = rfc8785.dumps(cast(Any, root))
        return HttpResponse(
            status_code=200,
            body=body,
            headers=(("Content-Type", "application/json"),),
        )


def _client(
    transport: Any,
    *,
    nonce_factory: Callable[[], str] | None = None,
    nonce_clock: Callable[[], float] | None = None,
) -> PrivateRecipeSelectionClient:
    return PrivateRecipeSelectionClient(
        base_url="https://api.pals.example",
        worker_secret=_SECRET,
        transport=transport,
        nonce_factory=(lambda: _NONCE) if nonce_factory is None else nonce_factory,
        nonce_clock=(lambda: 0.0) if nonce_clock is None else nonce_clock,
    )


@pytest.mark.parametrize(
    "base_url",
    (
        "http://api.pals.example",
        "https://api.pals.example ",
        "https://api.pals.example/path",
        "https://user:pass@api.pals.example",
    ),
)
def test_lrc_t005_rejects_non_https_or_nonorigin_catalog_urls(base_url: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTPS origin"):
        PrivateRecipeSelectionClient(
            base_url=base_url,
            worker_secret=_SECRET,
            transport=TransportThatMustNotRun(),
        )


def test_lrc_t005_sends_one_bound_authenticated_selection_request() -> None:
    transport = _RequestAwareTransport()

    result = _client(transport).select(_QUERY)

    assert isinstance(result, RecipeSelected)
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.pals.example/v1/internal/lean-recipe-catalog/selections"
    assert call["headers"] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-PALS-Recipe-Worker-Secret": _SECRET,
    }
    assert call["timeout_seconds"] == 10.0
    assert call["body"] is not None
    assert len(call["body"]) <= 32 * 1024
    assert json.loads(call["body"].decode("utf-8")) == {
        "schema_version": "pals.recipe-selection-query.v1",
        "request_nonce": _NONCE,
        "formal_target": _TARGET.as_json(),
        "draft_revision": _DRAFT.as_json(),
        "proof_method_tag": "explicit_epsilon_delta",
        "toolchain_fingerprint": _TOOLCHAIN.as_json(),
    }
    assert result.materialized_source_bytes == result.materialized_source.encode("utf-8")
    assert result.source_author_principal == "pals.principal.v1/recipe-author/continuous-square"


def test_lrc_t005_rejects_noncanonical_response_even_when_mac_is_valid() -> None:
    class NoncanonicalResponseTransport:
        def request(self, **kwargs: Any) -> HttpResponse:
            request = json.loads(kwargs["body"].decode("utf-8"))
            canonical = _response(request=request)
            # Whitespace does not alter the parsed HMAC preimage, but these
            # wire bytes are not RFC 8785 canonical.
            root = json.loads(canonical.decode("utf-8"))
            noncanonical = json.dumps(root, ensure_ascii=False).encode("utf-8")
            assert noncanonical != canonical
            return HttpResponse(
                status_code=200,
                body=noncanonical,
                headers=(("Content-Type", "application/json"),),
            )

    with pytest.raises(RecipeSelectionUnavailableError):
        _client(NoncanonicalResponseTransport()).select(_QUERY)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda root: root.update({"unexpected": True}),
        lambda root: root.__setitem__("request_nonce", "0" * 64),
        lambda root: root.__setitem__("request_sha256", "0" * 64),
        lambda root: root["selection"].__setitem__(
            "materialized_source", "example : True := by trivial"
        ),
        lambda root: root["selection"].__setitem__("target_sha256", "0" * 64),
        lambda root: root["selection"]["toolchain_fingerprint"].__setitem__(
            "lean_version", "wrong"
        ),
        lambda root: root["selection"].__setitem__("selection_payload_sha256", "0" * 64),
        lambda root: root["selection"].__setitem__("selection_receipt_sha256", "not-a-digest"),
        lambda root: root.__setitem__("response_mac_sha256", "0" * 64),
    ),
)
def test_lrc_t005_rejects_tampered_or_nonclosed_selected_dtos(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    transport = _RequestAwareTransport(mutate=mutate)

    with pytest.raises(RecipeSelectionUnavailableError):
        _client(transport).select(_QUERY)

    assert len(transport.calls) == 1


def test_lrc_t005_rejects_a_replayed_local_nonce_before_a_second_request() -> None:
    transport = _RequestAwareTransport()
    client = _client(transport)

    assert isinstance(client.select(_QUERY), RecipeSelected)
    with pytest.raises(RecipeSelectionUnavailableError):
        client.select(_QUERY)

    assert len(transport.calls) == 1


def test_lrc_t005_retains_every_nonce_for_the_full_ten_minute_receipt_window() -> None:
    clock = _Clock()
    transport = _RequestAwareTransport()
    client = _client(transport, nonce_clock=clock)

    assert isinstance(client.select(_QUERY), RecipeSelected)
    clock.now = 599.999
    with pytest.raises(RecipeSelectionUnavailableError):
        client.select(_QUERY)
    clock.now = 600.0
    assert isinstance(client.select(_QUERY), RecipeSelected)

    assert len(transport.calls) == 2


def test_lrc_t005_fails_closed_if_its_nonce_store_cannot_retain_an_issued_nonce() -> None:
    class FailingNonceStore:
        def claim(self, nonce: str) -> bool:
            del nonce
            raise MemoryError("nonce storage exhausted")

    transport = TransportThatMustNotRun()
    client = _client(transport)
    client._nonce_guard = FailingNonceStore()  # type: ignore[assignment]

    with pytest.raises(RecipeSelectionUnavailableError):
        client.select(_QUERY)


@pytest.mark.parametrize("error", (RuntimeError("clock failed"), OSError("clock unavailable")))
def test_lrc_t005_fails_closed_before_transport_when_nonce_clock_raises(
    error: Exception,
) -> None:
    def raising_clock() -> float:
        raise error

    with pytest.raises(RecipeSelectionUnavailableError):
        _client(TransportThatMustNotRun(), nonce_clock=raising_clock).select(_QUERY)


@pytest.mark.parametrize(
    "mutate_selection",
    (
        lambda selection: selection.update({"unexpected": True}),
        lambda selection: selection.__setitem__("selection_payload_sha256", "0" * 64),
        lambda selection: selection.__setitem__("materialized_source_sha256", "0" * 64),
    ),
)
def test_lrc_t005_rejects_closed_or_digest_invalid_selected_dto_even_with_valid_mac(
    mutate_selection: Callable[[dict[str, Any]], None],
) -> None:
    request = _QUERY.as_json(request_nonce=_NONCE)
    selection = _selected_payload()
    mutate_selection(selection)

    with pytest.raises(RecipeSelectionUnavailableError):
        _client(RecordingTransport(body=_response(request=request, selection=selection))).select(
            _QUERY
        )


def test_lrc_t005_returns_authenticated_structured_not_selected_result() -> None:
    request = _QUERY.as_json(request_nonce=_NONCE)
    response = _response(
        request=request,
        status="not_selected",
        selection=None,
        exclusions=[
            {
                "reason_code": "ambiguous_recipe",
                "recipe_id": "continuous_square_explicit_eps_delta",
                "recipe_revision": 1,
            }
        ],
    )

    result = _client(RecordingTransport(body=response)).select(_QUERY)

    assert isinstance(result, RecipeNotSelected)
    assert result.exclusions[0].reason_code == "ambiguous_recipe"
    assert result.exclusions[0].recipe_id == "continuous_square_explicit_eps_delta"


def test_lrc_t005_accepts_catalog_grammar_for_selected_recipe_and_alignment_ids() -> None:
    request = _QUERY.as_json(request_nonce=_NONCE)
    selection = _selection_with_catalog_ids(
        recipe_id="2continuous.square-explicit",
        alignment_id="3continuous.square-alignment",
    )

    result = _client(
        RecordingTransport(body=_response(request=request, selection=selection))
    ).select(_QUERY)

    assert isinstance(result, RecipeSelected)
    assert result.recipe_id == "2continuous.square-explicit"
    assert result.alignment_id == "3continuous.square-alignment"


def test_lrc_t005_accepts_catalog_grammar_for_excluded_recipe_ids() -> None:
    request = _QUERY.as_json(request_nonce=_NONCE)
    response = _response(
        request=request,
        status="not_selected",
        selection=None,
        exclusions=[
            {
                "reason_code": "ambiguous_recipe",
                "recipe_id": "2continuous.square-explicit",
                "recipe_revision": 1,
            }
        ],
    )

    result = _client(RecordingTransport(body=response)).select(_QUERY)

    assert isinstance(result, RecipeNotSelected)
    assert result.exclusions[0].recipe_id == "2continuous.square-explicit"


@pytest.mark.parametrize("draft_id", ("continuous.square", "continuous-square"))
def test_lrc_t005_keeps_draft_ids_lower_snake_case(draft_id: str) -> None:
    with pytest.raises(ValueError, match="Draft ID"):
        DraftRevisionReference(
            draft_id=draft_id,
            draft_payload_sha256="d" * 64,
        )


@pytest.mark.parametrize(
    "transport",
    (
        RecordingTransport(
            status_code=503,
            body=b'{"error":{"code":"recipe_selection_unavailable"}}',
        ),
        RecordingTransport(
            body=b"{" + b"x" * (512 * 1024 + 1) + b"}",
        ),
        RecordingTransport(
            body=b"{}",
            headers=(("Content-Type", "application/json; charset=utf-8"),),
        ),
        RecordingTransport(body=b"{}", error=HttpTransportError("network")),
    ),
)
def test_lrc_t005_treats_transport_authentication_size_and_media_failures_as_unavailable(
    transport: RecordingTransport,
) -> None:
    with pytest.raises(RecipeSelectionUnavailableError):
        _client(transport).select(_QUERY)


def test_lrc_t005_rejects_invalid_query_before_transport() -> None:
    with pytest.raises(TypeError, match="must be extracted"):
        FormalTarget(target_source="True", target_sha256="0" * 64)
    with pytest.raises(ValueError, match="Draft canonicalizer"):
        DraftRevisionReference(
            draft_id="continuous_square",
            draft_payload_sha256="d" * 64,
            canonicalizer_version="wrong",
        )
    with pytest.raises(ValueError, match="toolchain fingerprint"):
        RecipeSelectionQuery(toolchain_fingerprint=copy.copy("not-a-toolchain"))  # type: ignore[arg-type]


def test_lrc_t005_rejects_v4_draft_selection_before_hmac_or_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _reject_v4_contract() -> None:
        from pals_agent.openmath_v4_contract import OpenMathV4ContractError

        raise OpenMathV4ContractError("tampered v4 contract")

    monkeypatch.setattr(
        "pals_agent.private_recipe_selection.require_openmath_c14n_v4_contract",
        _reject_v4_contract,
    )

    with pytest.raises(RecipeSelectionUnavailableError):
        _client(TransportThatMustNotRun()).select(_QUERY)


def test_lrc_t001_extracts_only_one_closed_declaration_and_normalizes_its_target() -> None:
    compact = _formal_target("example : ∀ x : ℝ, x = x := by\n  intro x\n  rfl")
    spaced = _formal_target("example :  ∀    x : ℝ,  x = x := by\n  intro x\n  rfl")
    renamed = _formal_target("example : ∀ y : ℝ, y = y := by\n  intro y\n  rfl")

    assert compact.target_source == "∀ x : ℝ, x = x"
    assert compact.target_source == spaced.target_source
    assert compact.target_sha256 == spaced.target_sha256
    assert compact.target_source != renamed.target_source
    assert compact.target_sha256 != renamed.target_sha256


@pytest.mark.parametrize(
    "declaration_source",
    (
        "theorem parameterized (x : ℕ) : True := by trivial",
        "theorem implicit_parameter {x : ℕ} : True := by trivial",
        "theorem typeclass_parameter [Inhabited ℕ] : True := by trivial",
        "theorem universe_parameter.{u} : True := by trivial",
        "universe u\ntheorem ambient_universe : True := by trivial",
        "variable [Inhabited ℕ]\ntheorem ambient_typeclass : True := by trivial",
    ),
)
def test_lrc_t001_rejects_parameter_universe_and_typeclass_declaration_headers(
    declaration_source: str,
) -> None:
    assert ClosedRecipeHeaderV1.extract(declaration_source) is None
    assert FormalTarget.from_declaration(declaration_source) is None


@pytest.mark.parametrize(
    "origin", ["http://api:8000", "http://localhost:8000", "http://127.0.0.1:8000"]
)
def test_local_http_requires_explicit_opt_in_and_fixed_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTPS origin"):
        PrivateRecipeSelectionClient(origin, _SECRET)
    assert PrivateRecipeSelectionClient(origin, _SECRET, allow_local_http=True).base_url == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://api.example:8000",
        "http://api:8001",
        "http://api:8000/path",
        "http://user@api:8000",
        "http://api:8000?token=x",
    ],
)
def test_local_http_opt_in_does_not_allow_arbitrary_insecure_origins(origin: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTPS origin"):
        PrivateRecipeSelectionClient(origin, _SECRET, allow_local_http=True)
