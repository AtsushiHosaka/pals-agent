from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.models import DEFAULT_MAX_REPAIR_ATTEMPTS

_SEMANTIC_EVALUATOR_TOKEN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}",
    flags=re.ASCII,
)
_RELEASE_GENERATION_OVERRIDE_NAMES = (
    "PALS_LLM_PROVIDER",
    "PALS_OPENAI_MODEL",
    "OPENAI_MODEL",
    "OLLAMA_DRAFT_MODEL",
    "OLLAMA_PROVE_MODEL",
    "PALS_PROVE_MLX_MODEL_PATH",
)


@dataclass(frozen=True, slots=True)
class AgentSettings:
    llm_provider: Literal["ollama", "openai"]
    aws_region: str
    aws_endpoint_url: str | None
    proof_jobs_queue_url: str | None
    artifacts_bucket: str | None
    api_base_url: str
    worker_shared_secret: str
    ollama_host: str
    ollama_model: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    openai_max_output_tokens: int
    prove_mlx_model_path: str | None
    mlx_generate_binary: str
    mlx_max_tokens: int
    mlx_timeout_seconds: float
    mlx_temperature: float
    draft_embedding_provider: Literal["openai", "ollama"]
    draft_embedding_model: str
    draft_embedding_endpoint_identity: str | None
    draft_embedding_deployment_identity: str | None
    draft_embedding_revision: str | None
    draft_embedding_dimension: int
    draft_embedding_timeout_seconds: float
    lean_binary: str
    lake_binary: str
    lean_project_dir: Path | None
    pfi_runtime_provenance_sha256: str | None = None
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS
    worker_idle_sleep_seconds: float = 2.0
    explanation_model_timeout_seconds: int = 90
    semantic_evaluator_provider: Literal["openai", "ollama"] | None = None
    semantic_evaluator_model: str | None = None
    semantic_evaluator_revision: str | None = None
    semantic_evaluator_base_url: str | None = None

    def __post_init__(self) -> None:
        generation_binding = fixed_model_default(ModelRole.DRAFT)
        _validate_semantic_evaluator_configuration(
            provider=self.semantic_evaluator_provider,
            model=self.semantic_evaluator_model,
            revision=self.semantic_evaluator_revision,
            base_url=self.semantic_evaluator_base_url,
            generation_provider=generation_binding.provider,
            generation_model=generation_binding.model,
        )

    @classmethod
    def from_env(cls) -> AgentSettings:
        lean_project_dir = os.getenv("PALS_LEAN_PROJECT_DIR")
        artifacts_bucket = _first_env("PALS_S3_ARTIFACT_BUCKET", "PALS_ARTIFACTS_BUCKET")
        llm_provider = _llm_provider()
        draft_embedding_provider = _draft_embedding_provider()
        semantic_evaluator = _semantic_evaluator_env()
        _reject_removed_pfi_configuration()
        return cls(
            llm_provider=llm_provider,
            aws_region=_first_env("PALS_AWS_REGION", "AWS_REGION", "AWS_DEFAULT_REGION")
            or "ap-northeast-1",
            aws_endpoint_url=_first_env(
                "PALS_LOCALSTACK_ENDPOINT_URL",
                "PALS_AWS_ENDPOINT_URL",
                "AWS_ENDPOINT_URL",
            ),
            proof_jobs_queue_url=_first_env(
                "PALS_SQS_PROOF_JOBS_QUEUE_URL",
                "PALS_PROOF_JOBS_QUEUE_URL",
            ),
            artifacts_bucket=artifacts_bucket,
            api_base_url=os.getenv("PALS_API_BASE_URL", "http://localhost:8000"),
            worker_shared_secret=os.getenv("PALS_WORKER_SHARED_SECRET", ""),
            ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("OLLAMA_PROVE_MODEL")
            or os.getenv("OLLAMA_DRAFT_MODEL")
            or "qwen2.5:3b",
            openai_api_key=_first_env("PALS_OPENAI_API_KEY", "OPENAI_API_KEY") or "",
            openai_model=_first_env("PALS_OPENAI_MODEL", "OPENAI_MODEL")
            or "gpt-5.4-nano",
            openai_base_url=os.getenv(
                "PALS_OPENAI_BASE_URL",
                "https://api.openai.com/v1",
            ),
            openai_max_output_tokens=_positive_int_env("PALS_OPENAI_MAX_OUTPUT_TOKENS", 12000),
            prove_mlx_model_path=_optional_env("PALS_PROVE_MLX_MODEL_PATH"),
            mlx_generate_binary=os.getenv("PALS_MLX_GENERATE_BINARY", "mlx_lm.generate"),
            mlx_max_tokens=_positive_int_env("PALS_MLX_MAX_TOKENS", 4096),
            mlx_timeout_seconds=_positive_float_env("PALS_MLX_TIMEOUT_SECONDS", 600.0),
            mlx_temperature=_float_env("PALS_MLX_TEMPERATURE", 0.0),
            draft_embedding_provider=draft_embedding_provider,
            draft_embedding_model=_draft_embedding_model(draft_embedding_provider),
            draft_embedding_endpoint_identity=_optional_env(
                "PALS_DRAFT_EMBEDDING_ENDPOINT_IDENTITY"
            ),
            draft_embedding_deployment_identity=_optional_env(
                "PALS_DRAFT_EMBEDDING_DEPLOYMENT_IDENTITY"
            ),
            draft_embedding_revision=_draft_embedding_revision(),
            draft_embedding_dimension=_positive_int_env("PALS_DRAFT_EMBEDDING_DIM", 384),
            draft_embedding_timeout_seconds=_positive_float_env(
                "PALS_DRAFT_EMBEDDING_TIMEOUT_SECONDS",
                60.0,
            ),
            lean_binary=os.getenv("PALS_LEAN_BINARY", "lean"),
            lake_binary=os.getenv("PALS_LAKE_BINARY", "lake"),
            lean_project_dir=Path(lean_project_dir) if lean_project_dir else None,
            pfi_runtime_provenance_sha256=_optional_env("PALS_PFI_PROVENANCE_SHA256"),
            max_repair_attempts=_bounded_ascii_int_env(
                "PALS_MAX_REPAIR_ATTEMPTS",
                DEFAULT_MAX_REPAIR_ATTEMPTS,
                minimum=1,
                maximum=64,
            ),
            worker_idle_sleep_seconds=float(
                os.getenv("PALS_AGENT_WORKER_IDLE_SLEEP_SECONDS", "2.0")
            ),
            explanation_model_timeout_seconds=_bounded_ascii_int_env(
                "PALS_EXPLANATION_MODEL_TIMEOUT_SECONDS",
                90,
                minimum=1,
                maximum=300,
            ),
            semantic_evaluator_provider=semantic_evaluator[0],
            semantic_evaluator_model=semantic_evaluator[1],
            semantic_evaluator_revision=semantic_evaluator[2],
            semantic_evaluator_base_url=semantic_evaluator[3],
        )


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_release_generation_environment() -> None:
    """Reject every release generation model/provider override before any work starts."""

    configured = [
        name
        for name in _RELEASE_GENERATION_OVERRIDE_NAMES
        if (value := os.getenv(name)) is not None and value.strip()
    ]
    if configured:
        raise ValueError(
            "Release generation roles are code-owned; remove: "
            + ", ".join(configured)
        )


def _reject_removed_pfi_configuration() -> None:
    configured = [
        name
        for name in os.environ
        if name.startswith("PALS_")
        and any(marker in name for marker in ("DATABASE", "RDS", "DRAFT_RETRIEVAL"))
    ]
    if configured:
        raise ValueError(
            "Agent PFI runtime forbids removed direct-storage configuration: "
            + ", ".join(configured)
        )


def _llm_provider() -> Literal["ollama", "openai"]:
    value = os.getenv("PALS_LLM_PROVIDER", "ollama").strip().lower()
    if value == "ollama":
        return "ollama"
    if value == "openai":
        return "openai"
    raise ValueError("PALS_LLM_PROVIDER must be one of: ollama, openai")


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _bounded_ascii_int_env(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    if re.fullmatch(r"[0-9]+", value, flags=re.ASCII) is None:
        raise ValueError(
            f"{name} must be an ASCII base-10 integer between {minimum} and {maximum}"
        )
    parsed = int(value, 10)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _positive_float_env(name: str, default: float) -> float:
    value = _float_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def _draft_embedding_provider() -> Literal["openai", "ollama"]:
    configured = os.getenv("PALS_DRAFT_EMBEDDING_PROVIDER")
    value = (
        "openai"
        if configured is None or configured.strip() == ""
        else configured.strip().lower()
    )
    if value == "openai":
        return "openai"
    if value == "ollama":
        return "ollama"
    raise ValueError("PALS_DRAFT_EMBEDDING_PROVIDER must be one of: openai, ollama")


def _draft_embedding_model(provider: Literal["openai", "ollama"]) -> str:
    configured = _optional_env("PALS_DRAFT_EMBEDDING_MODEL")
    if configured is not None:
        return configured
    if provider == "openai":
        return "text-embedding-3-small"
    if provider == "ollama":
        return "nomic-embed-text"
    raise AssertionError(f"Unhandled draft embedding provider: {provider}")


def _draft_embedding_revision() -> str | None:
    revision = _optional_env("PALS_DRAFT_EMBEDDING_REVISION")
    digest = _optional_env("PALS_DRAFT_EMBEDDING_DIGEST")
    if revision is not None and digest is not None and revision != digest:
        raise ValueError(
            "PALS_DRAFT_EMBEDDING_REVISION and PALS_DRAFT_EMBEDDING_DIGEST "
            "must match when both are set"
        )
    return revision or digest


def _semantic_evaluator_env() -> tuple[
    Literal["openai", "ollama"] | None,
    str | None,
    str | None,
    str | None,
]:
    names = (
        "PALS_SEMANTIC_EVALUATOR_PROVIDER",
        "PALS_SEMANTIC_EVALUATOR_MODEL",
        "PALS_SEMANTIC_EVALUATOR_REVISION",
        "PALS_SEMANTIC_EVALUATOR_BASE_URL",
    )
    values = tuple(os.getenv(name) for name in names)
    if all(value is None for value in values):
        return None, None, None, None
    if any(value is None for value in values):
        raise ValueError("semantic evaluator configuration must set all four variables")
    provider, model, revision, base_url = values
    assert provider is not None
    assert model is not None
    assert revision is not None
    assert base_url is not None
    if provider not in {"openai", "ollama"}:
        raise ValueError("semantic evaluator provider must be openai or ollama")
    semantic_provider: Literal["openai", "ollama"] = (
        "openai" if provider == "openai" else "ollama"
    )
    return semantic_provider, model, revision, base_url


def _validate_semantic_evaluator_configuration(
    *,
    provider: object,
    model: object,
    revision: object,
    base_url: object,
    generation_provider: object,
    generation_model: object,
) -> None:
    values = (provider, model, revision, base_url)
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise ValueError("semantic evaluator configuration must be all-or-none")
    if provider not in {"openai", "ollama"}:
        raise ValueError("semantic evaluator provider must be openai or ollama")
    if not isinstance(model, str) or _SEMANTIC_EVALUATOR_TOKEN_RE.fullmatch(model) is None:
        raise ValueError("semantic evaluator model is invalid")
    if (
        not isinstance(revision, str)
        or _SEMANTIC_EVALUATOR_TOKEN_RE.fullmatch(revision) is None
    ):
        raise ValueError("semantic evaluator revision is invalid")
    if not isinstance(base_url, str) or base_url != base_url.strip():
        raise ValueError("semantic evaluator base URL is invalid")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("semantic evaluator base URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in base_url
        or "#" in base_url
        or "\\" in base_url
        or any(character.isspace() for character in base_url)
    ):
        raise ValueError("semantic evaluator base URL is invalid")
    if provider == generation_provider and model == generation_model:
        raise ValueError(
            "semantic evaluator must differ from the generation provider/model"
        )
