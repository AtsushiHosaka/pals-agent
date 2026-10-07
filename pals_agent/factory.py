from __future__ import annotations

import os
from dataclasses import replace

import boto3  # type: ignore[import-untyped]

from pals_agent.artifacts import ArtifactStore, S3ArtifactStore
from pals_agent.draft_embeddings import (
    EmbeddingModel,
    OllamaEmbeddingModel,
    OpenAIEmbeddingModel,
)
from pals_agent.explanations import (
    LeanGroundedOutputReviewer,
    LeanProofExplainer,
    LeanProofSemanticReviewer,
)
from pals_agent.generator import HybridLeanGenerator
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.ollama import OllamaClient
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.openmath import (
    LLMStatementOpenMathStructurer,
    StatementOpenMathStructurer,
)
from pals_agent.pipeline import ProofPipeline
from pals_agent.private_draft_candidates import (
    DraftEmbeddingFingerprint,
    validate_draft_embedding_fingerprint,
)
from pals_agent.private_recipe_selection import (
    PrivateRecipeSelectionClient,
    ToolchainFingerprintV1,
)
from pals_agent.private_typed_candidates import PrivateTypedCandidateClient
from pals_agent.profile_routing import ProfileRoutedProofFlowRuntime
from pals_agent.proof_flow_reranker import OpenAIDraftReranker
from pals_agent.proof_flow_runtime import ProofFlowRuntime, build_private_proof_flow_runtime
from pals_agent.proof_request_worker import ProofRequestApi, ProofRequestProcessor
from pals_agent.proof_reuse_usage import RoleBoundClient
from pals_agent.recipe_attempt import RecipeAttemptPlannerV1
from pals_agent.semantic_evaluation import SemanticStageJudge
from pals_agent.settings import AgentSettings, validate_release_generation_environment
from pals_agent.typed_runtime import TypedProofFlowRuntime


def build_pipeline(settings: AgentSettings) -> ProofPipeline:
    generator = build_generator(settings)
    return ProofPipeline(
        generator=generator,
        verifier=None,
        artifact_store=build_artifact_store(settings),
        # Explicit pinned PFI capability enables exact Draft evidence. Its errors
        # fail closed; an unconfigured deployment retains direct generation.
        proof_flow_retriever=(
            build_profile_routed_runtime(settings)
            if settings.typed_catalog_enabled
            else build_proof_flow_runtime(settings)
            if settings.pfi_runtime_provenance_sha256 is not None
            else None
        ),
        max_repair_attempts=settings.max_repair_attempts,
        verification_mode="api_reconcile",
    )


def build_recipe_attempt_planner(settings: AgentSettings) -> RecipeAttemptPlannerV1 | None:
    """Compose Recipe selection only from the same pinned verifier workspace.

    An absent four-value configuration leaves legacy no-Recipe generation unchanged.  Partial
    configuration is rejected by ``AgentSettings``; malformed pinned workspace data fails startup
    instead of allowing a guessed toolchain fingerprint.
    """

    if settings.recipe_worker_secret is None:
        return None
    if (
        settings.recipe_verifier_sha256 is None
        or settings.recipe_active_lean_version is None
        or settings.recipe_active_lake_manifest_sha256 is None
    ):
        raise ValueError("Recipe selection configuration is incomplete")
    return RecipeAttemptPlannerV1(
        selector=PrivateRecipeSelectionClient(
            base_url=settings.api_base_url,
            worker_secret=settings.recipe_worker_secret,
            allow_local_http=os.environ.get("PALS_ENV") == "local",
        ),
        toolchain_fingerprint=ToolchainFingerprintV1(
            lean_version=settings.recipe_active_lean_version,
            lake_manifest_sha256=settings.recipe_active_lake_manifest_sha256,
            verifier_sha256=settings.recipe_verifier_sha256,
            materializer_version="pals.recipe-materializer.v1",
        ),
    )


def build_proof_request_processor(
    settings: AgentSettings, api_client: ProofRequestApi
) -> ProofRequestProcessor:
    """Compose natural proof answering separately from all Lean/artifact capabilities."""
    from pals_agent.chat_runtime import ChatRuntime
    from pals_agent.proof_reuse import ProofReuseRuntime
    from pals_agent.proof_reuse_catalog import ApiProofReuseCatalog

    client = replace(_release_openai_client(settings), max_output_tokens=6000)

    return ProofRequestProcessor(
        api=api_client,
        token_accounting_enabled=(
            os.environ.get("PALS_ENV") in {"local", "prod"}
            and os.environ.get("PALS_TOKEN_ACCOUNTING_ENABLED") == "true"
        ),
        runtime=ChatRuntime(
            client=client,
            proof_runtime=ProofReuseRuntime(client=client, catalog=ApiProofReuseCatalog(settings)),
        ),
    )


def build_generator(settings: AgentSettings) -> HybridLeanGenerator:
    binding = fixed_model_default(ModelRole.DRAFT)
    return HybridLeanGenerator(
        model=binding.model,
        provider=binding.provider,
        openai=_release_openai_client(settings),
    )


def build_proof_explainer(settings: AgentSettings) -> LeanProofExplainer:
    binding = fixed_model_default(ModelRole.EXPLAIN)
    return LeanProofExplainer(
        client=_release_openai_client(settings),
        model=binding.model,
        provider=binding.provider,
        max_attempts=3,
    )


def build_proof_output_reviewer(settings: AgentSettings) -> LeanGroundedOutputReviewer:
    """Build a distinct Responses client for the mandatory publication review."""
    binding = fixed_model_default(ModelRole.EXPLAIN)
    return LeanGroundedOutputReviewer(
        client=_release_openai_client(settings),
        model=binding.model,
        provider=binding.provider,
        max_attempts=2,
    )


def build_proof_semantic_reviewer(settings: AgentSettings) -> LeanProofSemanticReviewer:
    """Build a separate LLM session for the post-Lean proof acceptance gate."""
    binding = fixed_model_default(ModelRole.PROOF_REVIEW)
    return LeanProofSemanticReviewer(
        client=_release_openai_client(settings),
        model=binding.model,
        provider=binding.provider,
        max_attempts=2,
    )


def build_semantic_stage_judge(settings: AgentSettings) -> SemanticStageJudge:
    provider = settings.semantic_evaluator_provider
    model = settings.semantic_evaluator_model
    revision = settings.semantic_evaluator_revision
    base_url = settings.semantic_evaluator_base_url
    if provider is None:
        if any(value is not None for value in (model, revision, base_url)):
            raise ValueError("semantic evaluator configuration must be all-or-none")
        return SemanticStageJudge.unconfigured()
    if model is None or revision is None or base_url is None:
        raise ValueError("semantic evaluator configuration must be all-or-none")
    generation_binding = fixed_model_default(ModelRole.DRAFT)
    if provider == generation_binding.provider and model == generation_binding.model:
        raise ValueError("semantic evaluator must differ from the generation provider/model")
    if provider == "openai":
        return SemanticStageJudge(
            client=OpenAIResponsesClient(
                api_key=settings.openai_api_key,
                base_url=base_url,
                max_output_tokens=settings.openai_max_output_tokens,
            ),
            model=model,
            provider="openai",
            model_revision=revision,
        )
    return SemanticStageJudge(
        client=OllamaClient(host=base_url),
        model=model,
        provider="ollama",
        model_revision=revision,
    )


def build_artifact_store(settings: AgentSettings) -> ArtifactStore:
    if not settings.artifacts_bucket:
        raise RuntimeError("PALS_ARTIFACTS_BUCKET is required for proof artifacts.")
    return S3ArtifactStore(
        client=boto3.client(
            "s3",
            endpoint_url=settings.aws_endpoint_url,
            region_name=settings.aws_region,
        ),
        bucket=settings.artifacts_bucket,
    )


def build_statement_openmath_structurer(
    settings: AgentSettings,
) -> StatementOpenMathStructurer:
    binding = fixed_model_default(ModelRole.OPENMATH)
    return LLMStatementOpenMathStructurer(
        client=RoleBoundClient(_release_openai_client(settings), "openmath"),
        model=binding.model,
        provider=binding.provider,
    )


def _release_openai_client(settings: AgentSettings) -> OpenAIResponsesClient:
    validate_release_generation_environment()
    if not settings.openai_api_key.strip():
        raise ValueError("PALS_OPENAI_API_KEY or OPENAI_API_KEY is required for release generation")
    return OpenAIResponsesClient(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        max_output_tokens=settings.openai_max_output_tokens,
    )


def build_draft_embedding_model(settings: AgentSettings) -> EmbeddingModel:
    if settings.draft_embedding_revision is None:
        raise RuntimeError(
            "PALS_DRAFT_EMBEDDING_REVISION or PALS_DRAFT_EMBEDDING_DIGEST is "
            "required to pin immutable embedding behavior."
        )
    if settings.draft_embedding_provider == "openai":
        return OpenAIEmbeddingModel(
            api_key=settings.openai_api_key,
            revision=settings.draft_embedding_revision,
            model=settings.draft_embedding_model,
            dimension=settings.draft_embedding_dimension,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.draft_embedding_timeout_seconds,
            endpoint_identity_override=settings.draft_embedding_endpoint_identity,
            deployment_identity_override=(settings.draft_embedding_deployment_identity),
        )
    return OllamaEmbeddingModel(
        revision=settings.draft_embedding_revision,
        host=settings.ollama_host,
        model=settings.draft_embedding_model,
        dimension=settings.draft_embedding_dimension,
        timeout_seconds=settings.draft_embedding_timeout_seconds,
        endpoint_identity_override=settings.draft_embedding_endpoint_identity,
        deployment_identity_override=settings.draft_embedding_deployment_identity,
    )


def build_proof_flow_runtime(settings: AgentSettings) -> ProofFlowRuntime:
    embedding_model = build_draft_embedding_model(settings)
    return build_private_proof_flow_runtime(
        structurer=build_statement_openmath_structurer(settings),
        embedding_model=embedding_model,
        embedding_fingerprint=validate_draft_embedding_fingerprint(
            DraftEmbeddingFingerprint(
                provider=settings.draft_embedding_provider,
                model=settings.draft_embedding_model,
                endpoint=embedding_model.endpoint_identity,
                deployment=embedding_model.deployment_identity,
                revision=embedding_model.revision,
                dimension=embedding_model.dimension,
            )
        ),
        runtime_provenance_sha256=settings.pfi_runtime_provenance_sha256 or "",
        api_base_url=settings.api_base_url,
        worker_secret=settings.worker_shared_secret,
        openai_api_key=settings.openai_api_key,
    )


def build_profile_routed_runtime(settings: AgentSettings) -> ProfileRoutedProofFlowRuntime:
    """Worker-only API capability; no release credential or database access."""
    client = _release_openai_client(settings)
    return ProfileRoutedProofFlowRuntime(
        client=client,
        typed=TypedProofFlowRuntime(
            client=client,
            embeddings=OpenAIEmbeddingModel(
                api_key=settings.openai_api_key,
                revision="openai-release-2024-01-25",
                timeout_seconds=settings.draft_embedding_timeout_seconds,
            ),
            candidates=PrivateTypedCandidateClient(
                settings.api_base_url, settings.worker_shared_secret,
            ),
            reranker=OpenAIDraftReranker(api_key=settings.openai_api_key),
        ),
        generic=(build_proof_flow_runtime(settings)
                 if settings.pfi_runtime_provenance_sha256 is not None else None),
    )
