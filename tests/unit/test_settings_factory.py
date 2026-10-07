from __future__ import annotations

import pytest

from pals_agent.draft_embeddings import (
    OllamaEmbeddingModel,
    OpenAIEmbeddingModel,
)
from pals_agent.factory import (
    build_draft_embedding_model,
    build_pipeline,
    build_proof_explainer,
    build_proof_flow_runtime,
    build_proof_output_reviewer,
    build_proof_semantic_reviewer,
    build_recipe_attempt_planner,
    build_semantic_stage_judge,
    build_statement_openmath_structurer,
)
from pals_agent.generator import HybridLeanGenerator
from pals_agent.model_roles import (
    RELEASE_ROLE_REGISTRY,
    RELEASE_ROLE_REGISTRY_REVISION,
    ModelRole,
    fixed_model_default,
)
from pals_agent.ollama import OllamaClient
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.openmath import LLMStatementOpenMathStructurer
from pals_agent.proof_flow_runtime import ProofFlowRuntime
from pals_agent.settings import AgentSettings


def test_settings_default_to_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALS_LLM_PROVIDER", raising=False)

    settings = AgentSettings.from_env()

    assert settings.llm_provider == "ollama"
    assert settings.ollama_model == "qwen2.5:3b"
    assert settings.openai_model == "gpt-6-luna"
    assert build_recipe_attempt_planner(settings) is None
    assert settings.openai_max_output_tokens == 12000
    assert settings.prove_mlx_model_path is None
    assert settings.mlx_generate_binary == "mlx_lm.generate"
    assert settings.mlx_max_tokens == 4096
    assert settings.mlx_timeout_seconds == 600.0
    assert settings.mlx_temperature == 0.0
    assert settings.draft_embedding_provider == "openai"
    assert settings.draft_embedding_model == "text-embedding-3-small"
    assert settings.draft_embedding_endpoint_identity is None
    assert settings.draft_embedding_deployment_identity is None
    assert settings.draft_embedding_revision is None
    assert settings.draft_embedding_dimension == 384
    assert settings.draft_embedding_timeout_seconds == 60.0
    assert settings.pfi_runtime_provenance_sha256 is None
    assert settings.max_repair_attempts == 12


def test_settings_reject_partial_recipe_selection_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_RECIPE_WORKER_SECRET", "recipe-secret")

    with pytest.raises(ValueError, match="Recipe selection requires"):
        AgentSettings.from_env()


def test_dpb_014_settings_build_recipe_selection_from_signed_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_RECIPE_WORKER_SECRET", "recipe-secret")
    monkeypatch.setenv("PALS_RECIPE_VERIFIER_SHA256", "b" * 64)
    monkeypatch.setenv("PALS_RECIPE_ACTIVE_LEAN_VERSION", "v4.19.0")
    monkeypatch.setenv("PALS_RECIPE_ACTIVE_LAKE_MANIFEST_SHA256", "a" * 64)
    monkeypatch.setenv("PALS_API_BASE_URL", "https://api.palschat.site")

    planner = build_recipe_attempt_planner(AgentSettings.from_env())

    assert planner is not None
    assert planner.toolchain_fingerprint.lean_version == "v4.19.0"
    assert planner.toolchain_fingerprint.lake_manifest_sha256 == "a" * 64
    assert planner.toolchain_fingerprint.verifier_sha256 == "b" * 64
    assert planner.toolchain_fingerprint.materializer_version == "pals.recipe-materializer.v1"


def test_settings_read_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PALS_OPENAI_MODEL", "gpt-5.4-nano")
    monkeypatch.setenv("PALS_OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("PALS_OPENAI_MAX_OUTPUT_TOKENS", "8192")

    settings = AgentSettings.from_env()

    assert settings.llm_provider == "openai"
    assert settings.openai_api_key == "sk-test"
    assert settings.openai_model == "gpt-5.4-nano"
    assert settings.openai_base_url == "https://api.openai.test/v1"
    assert settings.openai_max_output_tokens == 8192
    assert settings.draft_embedding_provider == "openai"
    assert settings.draft_embedding_model == "text-embedding-3-small"


def test_settings_reject_direct_database_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_DATABASE_URL", "postgresql://ignored")

    with pytest.raises(ValueError, match="forbids removed direct-storage"):
        AgentSettings.from_env()


def test_settings_read_mlx_prove_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALS_PROVE_MLX_MODEL_PATH", "/models/OProver-32B-MLX-4bit")
    monkeypatch.setenv("PALS_MLX_GENERATE_BINARY", "/repo/.venv-oprover/bin/mlx_lm.generate")
    monkeypatch.setenv("PALS_MLX_MAX_TOKENS", "4096")
    monkeypatch.setenv("PALS_MLX_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("PALS_MLX_TEMPERATURE", "0.2")

    settings = AgentSettings.from_env()

    assert settings.prove_mlx_model_path == "/models/OProver-32B-MLX-4bit"
    assert settings.mlx_generate_binary == "/repo/.venv-oprover/bin/mlx_lm.generate"
    assert settings.mlx_max_tokens == 4096
    assert settings.mlx_timeout_seconds == 300.0
    assert settings.mlx_temperature == 0.2


def test_settings_reject_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALS_LLM_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="PALS_LLM_PROVIDER"):
        AgentSettings.from_env()


def test_settings_reject_unknown_draft_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="PALS_DRAFT_EMBEDDING_PROVIDER"):
        AgentSettings.from_env()


def test_factory_uses_openai_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.delenv("PALS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PALS_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")

    pipeline = build_pipeline(AgentSettings.from_env())

    assert isinstance(pipeline.generator, HybridLeanGenerator)
    assert pipeline.generator.provider == "openai"
    assert pipeline.generator.model == "gpt-6-luna"
    assert pipeline.generator.openai is not None
    assert pipeline.generator.openai.max_output_tokens == 12000
    assert pipeline.draft_catalog is None
    assert isinstance(pipeline.proof_flow_retriever, ProofFlowRuntime)
    assert pipeline.verifier is None
    assert pipeline.verification_mode == "api_reconcile"


def test_factory_builds_distinct_explanation_and_review_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PALS_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    settings = AgentSettings.from_env()
    explainer = build_proof_explainer(settings)
    reviewer = build_proof_output_reviewer(settings)
    proof_reviewer = build_proof_semantic_reviewer(settings)

    assert explainer.client is not reviewer.client
    assert explainer.client is not proof_reviewer.client
    assert reviewer.client is not proof_reviewer.client
    assert explainer.model == reviewer.model == "gpt-6-luna"
    assert explainer.provider == reviewer.provider == "openai"


def test_factory_rejects_generation_provider_override_before_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")

    with pytest.raises(ValueError, match="PALS_LLM_PROVIDER"):
        build_pipeline(AgentSettings.from_env())


def _clear_semantic_evaluator_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PALS_SEMANTIC_EVALUATOR_PROVIDER",
        "PALS_SEMANTIC_EVALUATOR_MODEL",
        "PALS_SEMANTIC_EVALUATOR_REVISION",
        "PALS_SEMANTIC_EVALUATOR_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_factory_never_implicitly_uses_generation_model_as_semantic_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_semantic_evaluator_env(monkeypatch)
    monkeypatch.setenv("PALS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PALS_OPENAI_MODEL", "generation-model")

    judge = build_semantic_stage_judge(AgentSettings.from_env())

    assert judge.configured is False
    assert judge.provider is None
    assert judge.model is None
    assert judge.model_revision is None


def test_factory_builds_semantic_judge_only_from_pinned_evaluator_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_DRAFT_MODEL", "generation-model")
    monkeypatch.setenv("PALS_OPENAI_API_KEY", "sk-evaluator-test")
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_PROVIDER", "openai")
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_MODEL", "gpt-evaluator-2026-07")
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_REVISION", "deploy:sha256-abc")
    monkeypatch.setenv(
        "PALS_SEMANTIC_EVALUATOR_BASE_URL",
        "https://evaluator.test/v1",
    )

    settings = AgentSettings.from_env()
    judge = build_semantic_stage_judge(settings)

    assert settings.semantic_evaluator_provider == "openai"
    assert settings.semantic_evaluator_model == "gpt-evaluator-2026-07"
    assert settings.semantic_evaluator_revision == "deploy:sha256-abc"
    assert settings.semantic_evaluator_base_url == "https://evaluator.test/v1"
    assert judge.configured is True
    assert judge.provider == "openai"
    assert judge.model == "gpt-evaluator-2026-07"
    assert judge.model_revision == "deploy:sha256-abc"
    assert isinstance(judge.client, OpenAIResponsesClient)
    assert judge.client.base_url == "https://evaluator.test/v1"


def test_factory_builds_independent_ollama_evaluator_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PALS_OPENAI_MODEL", "generation-model")
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_PROVIDER", "ollama")
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_MODEL", "judge-model:7b")
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_REVISION", "digest:123")
    monkeypatch.setenv(
        "PALS_SEMANTIC_EVALUATOR_BASE_URL",
        "http://judge-ollama.test:11434",
    )

    judge = build_semantic_stage_judge(AgentSettings.from_env())

    assert isinstance(judge.client, OllamaClient)
    assert judge.client.host == "http://judge-ollama.test:11434"


@pytest.mark.parametrize(
    "missing",
    [
        "PALS_SEMANTIC_EVALUATOR_PROVIDER",
        "PALS_SEMANTIC_EVALUATOR_MODEL",
        "PALS_SEMANTIC_EVALUATOR_REVISION",
        "PALS_SEMANTIC_EVALUATOR_BASE_URL",
    ],
)
def test_settings_reject_partial_semantic_evaluator_tuple(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    values = {
        "PALS_SEMANTIC_EVALUATOR_PROVIDER": "openai",
        "PALS_SEMANTIC_EVALUATOR_MODEL": "judge-model",
        "PALS_SEMANTIC_EVALUATOR_REVISION": "judge-revision",
        "PALS_SEMANTIC_EVALUATOR_BASE_URL": "https://judge.test/v1",
    }
    for name, value in values.items():
        if name != missing:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="semantic evaluator"):
        AgentSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PALS_SEMANTIC_EVALUATOR_PROVIDER", "anthropic"),
        ("PALS_SEMANTIC_EVALUATOR_PROVIDER", "OpenAI"),
        ("PALS_SEMANTIC_EVALUATOR_MODEL", ""),
        ("PALS_SEMANTIC_EVALUATOR_MODEL", " judge-model"),
        ("PALS_SEMANTIC_EVALUATOR_MODEL", "judge model"),
        ("PALS_SEMANTIC_EVALUATOR_MODEL", "j" * 257),
        ("PALS_SEMANTIC_EVALUATOR_REVISION", ""),
        ("PALS_SEMANTIC_EVALUATOR_REVISION", "revision#fragment"),
        ("PALS_SEMANTIC_EVALUATOR_REVISION", "r" * 257),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", "judge.test/v1"),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", "ftp://judge.test/v1"),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", "https:///v1"),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", "https://user@judge.test/v1"),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", "https://judge.test/v1?q=1"),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", "https://judge.test/v1#fragment"),
        ("PALS_SEMANTIC_EVALUATOR_BASE_URL", " https://judge.test/v1"),
    ],
)
def test_settings_reject_invalid_semantic_evaluator_configuration(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    values = {
        "PALS_SEMANTIC_EVALUATOR_PROVIDER": "openai",
        "PALS_SEMANTIC_EVALUATOR_MODEL": "judge-model",
        "PALS_SEMANTIC_EVALUATOR_REVISION": "judge-revision",
        "PALS_SEMANTIC_EVALUATOR_BASE_URL": "https://judge.test/v1",
    }
    values[name] = value
    for env_name, env_value in values.items():
        monkeypatch.setenv(env_name, env_value)

    with pytest.raises(ValueError, match="semantic evaluator"):
        AgentSettings.from_env()


def test_factory_rejects_semantic_self_judge_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_PROVIDER", "openai")
    monkeypatch.setenv(
        "PALS_SEMANTIC_EVALUATOR_MODEL",
        "gpt-6-luna",
    )
    monkeypatch.setenv("PALS_SEMANTIC_EVALUATOR_REVISION", "judge-revision")
    monkeypatch.setenv(
        "PALS_SEMANTIC_EVALUATOR_BASE_URL",
        "https://judge.test/v1",
    )

    with pytest.raises(ValueError, match="generation provider/model"):
        build_semantic_stage_judge(AgentSettings.from_env())


def test_release_role_registry_is_complete_immutable_and_code_owned() -> None:
    assert RELEASE_ROLE_REGISTRY_REVISION == "pals.release-role-registry.v2"
    assert tuple(entry.role for entry in RELEASE_ROLE_REGISTRY) == (
        ModelRole.OPENMATH,
        ModelRole.DRAFT,
        ModelRole.SKETCH,
        ModelRole.PROVE,
        ModelRole.ROUTE,
        ModelRole.REPAIR,
        ModelRole.EXPLAIN,
        ModelRole.CLARIFY,
        ModelRole.PROOF_REVIEW,
        ModelRole.PROOF_REUSE_JUDGE,
        ModelRole.PROOF_REUSE_JUDGE_ESCALATION,
    )
    assert all(entry.provider == "openai" for entry in RELEASE_ROLE_REGISTRY)
    assert all(
        entry.model
        == (
            "gpt-5.6-terra"
            if entry.role == ModelRole.PROOF_REUSE_JUDGE_ESCALATION
            else "gpt-6-luna"
        )
        for entry in RELEASE_ROLE_REGISTRY
    )
    assert all(fixed_model_default(entry.role) == entry for entry in RELEASE_ROLE_REGISTRY)


def test_openmath_structuring_uses_fixed_role_model_and_preserves_power(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated_xml = (
        '<OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0"><OMBIND>'
        '<OMS cd="quant1" name="forall"/><OMBVAR><OMV name="n"/></OMBVAR>'
        '<OMA><OMS cd="logic1" name="implies"/><OMA><OMS cd="set1" name="in"/>'
        '<OMV name="n"/><OMS cd="setname1" name="N"/></OMA><OMA>'
        '<OMS cdbase="urn:pals:openmath:cd:v1" cd="pals1" name="continuous_on"/>'
        '<OMS cd="setname1" name="R"/>'
        '<OMBIND><OMS cd="fns1" name="lambda"/><OMBVAR><OMV name="y"/></OMBVAR>'
        '<OMA><OMS cd="arith1" name="power"/><OMV name="y"/><OMV name="n"/>'
        "</OMA></OMBIND></OMA></OMA></OMBIND></OMOBJ>"
    )
    calls: list[tuple[str, str]] = []

    def fake_generate(
        _client: OpenAIResponsesClient,
        *,
        model: str,
        prompt: str,
    ) -> str:
        calls.append((model, prompt))
        return generated_xml

    monkeypatch.setattr(OpenAIResponsesClient, "generate", fake_generate)
    monkeypatch.delenv("PALS_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PALS_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("PALS_OPENAI_MAX_OUTPUT_TOKENS", "8192")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openmath-test")
    monkeypatch.setenv("PALS_OPENAI_BASE_URL", "https://openmath.test/v1")

    structurer = build_statement_openmath_structurer(AgentSettings.from_env())
    result = structurer.structure("y^n が連続であることを示せ")

    assert isinstance(structurer, LLMStatementOpenMathStructurer)
    from pals_agent.proof_reuse_usage import RoleBoundClient

    assert isinstance(structurer.client, RoleBoundClient)
    assert structurer.client.role == "openmath"
    assert isinstance(structurer.client.client, OpenAIResponsesClient)
    assert structurer.provider == "openai"
    assert structurer.model == "gpt-6-luna"
    assert structurer.client.client.api_key == "sk-openmath-test"
    assert structurer.client.client.base_url == "https://openmath.test/v1"
    assert structurer.client.client.max_output_tokens == 8192
    assert len(calls) == 1
    assert calls[0][0] == "gpt-6-luna"
    assert "y^n が連続であることを示せ" in calls[0][1]
    assert 'cd="arith1" name="power"' in result
    assert 'name="v1"' in result
    assert 'name="v2"' in result
    assert 'name="n"' not in result
    assert 'name="y"' not in result


def test_factory_rejects_prove_model_override_before_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_PROVE_MLX_MODEL_PATH", "/models/OProver-32B-MLX-4bit")
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")

    with pytest.raises(ValueError, match="PALS_PROVE_MLX_MODEL_PATH"):
        build_pipeline(AgentSettings.from_env())


def test_factory_uses_direct_verified_proof_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.delenv("PALS_PFI_PROVENANCE_SHA256")
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_DIM", "32")

    pipeline = build_pipeline(AgentSettings.from_env())

    assert pipeline.draft_catalog is None
    assert pipeline.proof_flow_retriever is None


def test_factory_rejects_missing_pfi_runtime_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.delenv("PALS_PFI_PROVENANCE_SHA256")

    with pytest.raises(ValueError, match="runtime provenance digest"):
        build_proof_flow_runtime(AgentSettings.from_env())


def test_factory_uses_openai_draft_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PALS_OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_DIM", "384")
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv(
        "PALS_DRAFT_EMBEDDING_ENDPOINT_IDENTITY",
        "openai-project:project-1",
    )
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_DEPLOYMENT_IDENTITY", "embed-prod")

    model = build_draft_embedding_model(AgentSettings.from_env())

    assert isinstance(model, OpenAIEmbeddingModel)
    assert model.api_key == "sk-test"
    assert model.base_url == "https://api.openai.test/v1"
    assert model.model == "text-embedding-3-small"
    assert model.dimension == 384
    assert model.timeout_seconds == 12.0
    assert model.endpoint_identity == "openai-project:project-1"
    assert model.deployment_identity == "embed-prod"
    assert model.revision == "sha256:test-embedding-revision"


def test_factory_uses_ollama_draft_embedding_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_DIM", "768")
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.test:11434")

    model = build_draft_embedding_model(AgentSettings.from_env())

    assert isinstance(model, OllamaEmbeddingModel)
    assert model.host == "http://ollama.test:11434"
    assert model.model == "nomic-embed-text"
    assert model.dimension == 768
    assert model.endpoint_identity == "http://ollama.test:11434"
    assert model.deployment_identity == "nomic-embed-text"
    assert model.revision == "sha256:test-embedding-revision"


def test_factory_reads_repair_attempt_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_MAX_REPAIR_ATTEMPTS", "2")
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    pipeline = build_pipeline(AgentSettings.from_env())

    assert pipeline.max_repair_attempts == 2


def test_factory_rejects_missing_embedding_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PALS_DRAFT_EMBEDDING_REVISION", raising=False)
    monkeypatch.delenv("PALS_DRAFT_EMBEDDING_DIGEST", raising=False)

    with pytest.raises(RuntimeError, match="pin immutable embedding behavior"):
        build_draft_embedding_model(AgentSettings.from_env())


def test_settings_accept_embedding_digest_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALS_DRAFT_EMBEDDING_REVISION", raising=False)
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_DIGEST", "sha256:digest-only")

    assert AgentSettings.from_env().draft_embedding_revision == "sha256:digest-only"


def test_settings_reject_conflicting_embedding_revision_and_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_REVISION", "revision-a")
    monkeypatch.setenv("PALS_DRAFT_EMBEDDING_DIGEST", "revision-b")

    with pytest.raises(ValueError, match="must match"):
        AgentSettings.from_env()


def _pin_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PALS_DRAFT_EMBEDDING_REVISION",
        "sha256:test-embedding-revision",
    )
    monkeypatch.delenv("PALS_DRAFT_EMBEDDING_DIGEST", raising=False)
    monkeypatch.setenv("PALS_PFI_PROVENANCE_SHA256", "b" * 64)
    monkeypatch.setenv("PALS_WORKER_SHARED_SECRET", "worker-test-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def test_learner_factory_fails_closed_on_explicit_invalid_pfi_capability(monkeypatch):
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")
    monkeypatch.setenv("PALS_PFI_PROVENANCE_SHA256", "invalid")
    with pytest.raises(ValueError, match="runtime provenance digest"):
        build_pipeline(AgentSettings.from_env())


def test_learner_factory_requires_complete_embedding_binding_when_pfi_enabled(monkeypatch):
    _pin_embedding(monkeypatch)
    monkeypatch.setenv("PALS_ARTIFACTS_BUCKET", "pals-artifacts")
    monkeypatch.delenv("PALS_DRAFT_EMBEDDING_REVISION")
    with pytest.raises(RuntimeError, match="REVISION"):
        build_pipeline(AgentSettings.from_env())


@pytest.mark.parametrize("environment", ["local", "production", "test", ""])
def test_recipe_local_compose_http_is_only_enabled_in_explicit_local_environment(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    monkeypatch.setenv("PALS_ENV", environment)
    monkeypatch.setenv("PALS_RECIPE_WORKER_SECRET", "recipe-secret")
    monkeypatch.setenv("PALS_RECIPE_VERIFIER_SHA256", "b" * 64)
    monkeypatch.setenv("PALS_RECIPE_ACTIVE_LEAN_VERSION", "v4.19.0")
    monkeypatch.setenv("PALS_RECIPE_ACTIVE_LAKE_MANIFEST_SHA256", "a" * 64)
    monkeypatch.setenv("PALS_API_BASE_URL", "http://api:8000")
    if environment == "local":
        assert build_recipe_attempt_planner(AgentSettings.from_env()) is not None
    else:
        with pytest.raises(ValueError, match="absolute HTTPS origin"):
            build_recipe_attempt_planner(AgentSettings.from_env())
