from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class EmbeddingError(RuntimeError):
    pass


class EmbeddingModel(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def endpoint_identity(self) -> str: ...

    @property
    def deployment_identity(self) -> str: ...

    @property
    def revision(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class OpenAIEmbeddingModel:
    api_key: str
    revision: str
    model: str = "text-embedding-3-small"
    dimension: int = 384
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0
    endpoint_identity_override: str | None = None
    deployment_identity_override: str | None = None

    def __post_init__(self) -> None:
        _validate_dimension(self.dimension)
        _validate_identity("embedding revision", self.revision)
        _validate_optional_identity(
            "embedding endpoint identity",
            self.endpoint_identity_override,
        )
        _validate_optional_identity(
            "embedding deployment identity",
            self.deployment_identity_override,
        )
        _ = self.endpoint_identity

    @property
    def endpoint_identity(self) -> str:
        return self.endpoint_identity_override or normalize_embedding_endpoint(self.base_url)

    @property
    def deployment_identity(self) -> str:
        return self.deployment_identity_override or self.model

    def embed(self, text: str) -> list[float]:
        if not self.api_key.strip():
            raise EmbeddingError(
                "OPENAI_API_KEY is required when PALS_DRAFT_EMBEDDING_PROVIDER=openai."
            )

        payload: dict[str, object] = {
            "model": self.model,
            "input": text,
        }
        if self.model.startswith("text-embedding-3"):
            payload["dimensions"] = self.dimension

        request = Request(
            self.base_url.rstrip("/") + "/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"OpenAI embedding failed: HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"OpenAI embedding failed: {exc}") from exc

        return _extract_embedding(body, expected_dimension=self.dimension)


@dataclass(frozen=True, slots=True)
class OllamaEmbeddingModel:
    revision: str
    host: str = "http://127.0.0.1:11434"
    model: str = "nomic-embed-text"
    dimension: int = 768
    timeout_seconds: float = 60.0
    endpoint_identity_override: str | None = None
    deployment_identity_override: str | None = None

    def __post_init__(self) -> None:
        _validate_dimension(self.dimension)
        _validate_identity("embedding revision", self.revision)
        _validate_optional_identity(
            "embedding endpoint identity",
            self.endpoint_identity_override,
        )
        _validate_optional_identity(
            "embedding deployment identity",
            self.deployment_identity_override,
        )
        _ = self.endpoint_identity

    @property
    def endpoint_identity(self) -> str:
        return self.endpoint_identity_override or normalize_embedding_endpoint(self.host)

    @property
    def deployment_identity(self) -> str:
        return self.deployment_identity_override or self.model

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": text}
        try:
            body = self._post("/api/embed", payload)
        except EmbeddingError:
            body = self._post("/api/embeddings", {"model": self.model, "prompt": text})
        return _extract_embedding(body, expected_dimension=self.dimension)

    def _post(self, path: str, payload: dict[str, str]) -> dict[str, object]:
        request = Request(
            self.host.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"Ollama embedding failed: {exc}") from exc
        if not isinstance(body, dict):
            raise EmbeddingError("Ollama embedding response was not a JSON object.")
        return body


def embedding_to_pgvector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def normalize_embedding_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint.strip())
    if not parts.scheme or parts.hostname is None:
        raise ValueError("embedding endpoint must be an absolute URL")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port is not None else host
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{netloc}{path}"


def _extract_embedding(body: object, *, expected_dimension: int) -> list[float]:
    embedding: object | None = None
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            embedding = data[0].get("embedding")
        if embedding is None:
            embeddings = body.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                embedding = embeddings[0]
        if embedding is None:
            embedding = body.get("embedding")

    if not isinstance(embedding, list) or not all(_is_number(value) for value in embedding):
        raise EmbeddingError("Embedding response did not contain a numeric vector.")

    vector = [float(value) for value in embedding]
    if len(vector) != expected_dimension:
        raise EmbeddingError(
            "Embedding dimension mismatch: "
            f"expected {expected_dimension}, got {len(vector)}. "
            "Set PALS_DRAFT_EMBEDDING_DIM to the model output dimension."
        )
    return vector


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _validate_dimension(dimension: int) -> None:
    if dimension <= 0:
        raise ValueError("embedding dimension must be positive")


def _validate_identity(label: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must not be blank")


def _validate_optional_identity(label: str, value: str | None) -> None:
    if value is not None:
        _validate_identity(label, value)
