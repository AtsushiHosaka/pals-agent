from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
import rfc8785

from pals_agent.api_client import PalsApiError, VerifierAttestation
from pals_agent.explanations import ProofSemanticReview
from pals_agent.lean_target import (
    LeanTargetDeclaration,
    extract_single_target_declaration,
)
from pals_agent.models import Diagnostic, ProofJobState, ProofRequest
from pals_agent.openmath import OpenMathStructuringError
from pals_agent.pipeline import ApiRepairSeed
from pals_agent.private_recipe_selection import (
    RecipeNotSelected,
    RecipeSelected,
    RecipeSelectionQuery,
    ToolchainFingerprintV1,
)
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError
from pals_agent.recipe_attempt import RecipeAttemptPlannerV1
from pals_agent.settings import AgentSettings
from pals_agent.worker import (
    SqsProofWorker,
    _api_repair_seed_from_worker_input,
    _candidate_artifact_uri,
    _has_api_compile_failure,
    _has_pending_api_candidate,
    _verified_candidate_matches_statement,
)

_RECIPE_TOOLCHAIN = ToolchainFingerprintV1(
    lean_version="v4.19.0",
    lake_manifest_sha256="a" * 64,
    verifier_sha256="b" * 64,
    materializer_version="recipe-materializer-v1",
)
_RECIPE_SOURCE = "import Mathlib\n\nexample : True := by\n  trivial\n"
_MODEL_ARTIFACT_URI = "s3://pals-artifacts/proof-jobs/job-1/result.lean"


def test_worker_candidate_requires_the_model_pipeline_artifact() -> None:
    result = SimpleNamespace(artifact=SimpleNamespace(lean_uri=_MODEL_ARTIFACT_URI))

    assert _candidate_artifact_uri(run_result=result, lean_code=_RECIPE_SOURCE) == (
        _MODEL_ARTIFACT_URI
    )


def test_worker_candidate_does_not_fall_back_to_manual_fixture_provenance() -> None:
    result = SimpleNamespace(artifact=None)

    with pytest.raises(ValueError, match="durable model Lean artifact"):
        _candidate_artifact_uri(run_result=result, lean_code=_RECIPE_SOURCE)


class _RecipeSelector:
    def __init__(self) -> None:
        self.calls = 0
        self.query: RecipeSelectionQuery | None = None

    def select(self, query: object) -> RecipeSelected:
        assert isinstance(query, RecipeSelectionQuery)
        self.query = query
        self.calls += 1
        return RecipeSelected(
            recipe_id="recipe.square-v1",
            recipe_revision=1,
            alignment_id=None,
            alignment_revision=None,
            target_sha256=hashlib.sha256(b"True").hexdigest(),
            materialized_source=_RECIPE_SOURCE,
            materialized_source_sha256=hashlib.sha256(_RECIPE_SOURCE.encode("utf-8")).hexdigest(),
            toolchain_fingerprint=_RECIPE_TOOLCHAIN,
            toolchain_fingerprint_sha256=_RECIPE_TOOLCHAIN.sha256,
            compiler_receipt_sha256="c" * 64,
            source_author_principal="pals.principal.v1/recipe-author/local",
            selection_payload_sha256="d" * 64,
            selection_receipt_sha256="e" * 64,
        )


class _NoRecipeSelector:
    def __init__(self) -> None:
        self.calls = 0

    def select(self, query: object) -> RecipeNotSelected:
        del query
        self.calls += 1
        return RecipeNotSelected(exclusions=(), request_sha256="a" * 64)


def test_x_squared_alignment_rejects_an_unrelated_verified_theorem() -> None:
    statement = "x² が連続であることを説明してください。"

    assert _verified_candidate_matches_statement(
        statement,
        "theorem x_squared_continuous : Continuous (fun x : ℝ => x ^ 2) := by\n  fun_prop",
    )
    assert _verified_candidate_matches_statement(
        statement,
        "theorem x_squared_continuous : Continuous (fun y : ℝ => y ^ 2) := by\n  fun_prop",
    )
    assert not _verified_candidate_matches_statement(
        statement,
        "theorem identity_power : Continuous (fun x : ℝ => x) := by\n  fun_prop",
    )
    assert not _verified_candidate_matches_statement(
        statement,
        "theorem mismatched_binder : Continuous (fun x : ℝ => y ^ 2) := by\n  fun_prop",
    )


def test_candidate_target_extraction_rejects_missing_or_ambiguous_proof_declarations() -> None:
    assert extract_single_target_declaration("def helper : Nat := 1") is None
    assert (
        extract_single_target_declaration(
            "theorem first : True := by trivial\ntheorem second : True := by trivial\n"
        )
        is None
    )
    assert not _verified_candidate_matches_statement(
        "Show that True.",
        "theorem first : True := by trivial\ntheorem second : True := by trivial\n",
    )


def test_candidate_target_extraction_ignores_comments_and_string_decoys() -> None:
    target = extract_single_target_declaration(
        "-- theorem decoy : False := by contradiction\n"
        'def note : String := "lemma decoy : False := by contradiction"\n'
        "theorem target : True := by\n"
        "  trivial\n"
    )

    assert target == LeanTargetDeclaration(
        kind="theorem",
        name="target",
        proposition="True",
    )


def test_x_squared_alignment_ignores_harmless_balanced_parentheses() -> None:
    statement = "x² が連続であることを説明してください。"

    for proposition in (
        "Continuous (fun x : ℝ => (x ^ 2))",
        "Continuous ((fun x : ℝ => x ^ 2))",
        "Continuous (fun x : (ℝ) => x ^ 2)",
        "Continuous (fun x : ℝ => (x) ^ 2)",
        "Continuous (((fun x : ((ℝ)) => ((x) ^ 2))))",
    ):
        assert _verified_candidate_matches_statement(
            statement,
            f"theorem x_squared_continuous : {proposition} := by\n  fun_prop",
        )


def test_x_squared_alignment_does_not_ignore_unbalanced_parentheses() -> None:
    statement = "x² が連続であることを説明してください。"

    assert not _verified_candidate_matches_statement(
        statement,
        "theorem malformed : Continuous ((fun x : ℝ => x ^ 2) := by\n  fun_prop",
    )


def test_x_squared_alignment_requires_the_complete_real_valued_proposition() -> None:
    statement = "x² が連続であることを説明してください。"

    for proposition in (
        "False → Continuous (fun x : ℝ => x ^ 2)",
        "True ∨ Continuous (fun x : ℝ => x ^ 2)",
        "Continuous (fun x => x ^ 2)",
    ):
        assert not _verified_candidate_matches_statement(
            statement,
            f"theorem unrelated : {proposition} := by\n  sorry",
        )
    assert not _verified_candidate_matches_statement(
        statement,
        (
            "theorem identity : Continuous (fun x : ℝ => x) "
            "-- Continuous (fun x : ℝ => x ^ 2)\n"
            ":= by\n  fun_prop"
        ),
    )


def test_x_squared_alignment_finds_target_after_a_helper_declaration() -> None:
    statement = "x² が連続であることを説明してください。"
    lean_code = (
        "def two : Nat := 2\n"
        "theorem x_squared_continuous : "
        "Continuous (fun x : ℝ => (x ^ 2)) := by\n"
        "  fun_prop"
    )

    assert _verified_candidate_matches_statement(statement, lean_code)


def test_x_squared_alignment_ignores_declarations_inside_string_literals() -> None:
    statement = "x² が連続であることを説明してください。"
    lean_code = (
        'def decoy : String := "theorem fake : '
        'Continuous (fun x : ℝ => x ^ 2) := by"\n'
        "theorem identity : Continuous (fun x : ℝ => x) := by\n"
        "  fun_prop"
    )

    assert not _verified_candidate_matches_statement(statement, lean_code)


def test_x_squared_alignment_ignores_declarations_inside_quoted_identifiers() -> None:
    statement = "x² が連続であることを説明してください。"
    lean_code = (
        "def «theorem fake : Continuous (fun x : ℝ => x ^ 2) := by» : Nat := 0\n"
        "theorem identity : Continuous (fun x : ℝ => x) := by\n"
        "  fun_prop"
    )

    assert not _verified_candidate_matches_statement(statement, lean_code)


class ExplainerThatMustNotRun:
    def explain(self, **kwargs: Any) -> Any:
        raise AssertionError(f"unexpected explanation call: {kwargs}")

    def clarify(self, **kwargs: Any) -> Any:
        raise AssertionError(f"unexpected clarification call: {kwargs}")


class SemanticReviewApi:
    def __init__(self) -> None:
        self.evidence: list[dict[str, Any]] = []
        self.state = "semantic_review"

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": self.state,
            "result_artifact_uri": "s3://pals-artifacts/proof-jobs/job-semantic/result.lean",
            "chat_id": "chat-1",
            "output_language": "zh-Hans",
            "theorem_statement": "theorem sample : True := by trivial",
            "request_context": {"formal_statement": "True"},
            "lean_code": "theorem sample : True := by\n  trivial",
            "status_context": {
                "target_declaration": {
                    "kind": "theorem",
                    "name": "sample",
                    "proposition": "True",
                }
            },
            "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
            "generation_session_id": "11111111-1111-4111-8111-111111111111",
        }

    def get_verification_candidate_binding(self, **kwargs: Any) -> dict[str, Any]:
        job = self.get_proof_job(kwargs["proof_job_id"])
        return {
            "schema_version": "pals.verification-candidate-binding.v1", **kwargs,
            "mutation_claim_id": job["generation_session_id"],
            "lean_sha256": hashlib.sha256(job["lean_code"].encode()).hexdigest(),
            "result_artifact_uri": job["result_artifact_uri"],
            "source_binding_sha256": None, "candidate_status": "semantic_review",
        }

    def settle_proof_semantic_review_unavailable(self, *, proof_job_id, failure):
        self.operational_failure = failure
        self.state = "failed"
        return {"id": proof_job_id, "state": "failed"}

    def settle_proof_semantic_review(
        self,
        *,
        proof_job_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self.evidence.append(evidence)
        return {
            "id": proof_job_id,
            "state": "verified" if evidence["decision"] == "approved" else "failed",
        }


class RecordingSemanticReviewer:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.calls: list[dict[str, Any]] = []

    def review_proof(self, **kwargs: Any) -> ProofSemanticReview:
        self.calls.append(kwargs)
        return ProofSemanticReview(
            decision="rejected" if self.reject else "approved",
            rationale=(
                "The target does not match the learner request."
                if self.reject
                else "The target and proof match the learner request."
            ),
            reviewer_provider="openai",
            reviewer_model="gpt-5.4-mini-2026-03-17",
            session_id="33333333-3333-4333-8333-333333333333",
        )


class RaisingSemanticReviewer:
    def review_proof(self, **_kwargs: Any) -> ProofSemanticReview:
        raise RuntimeError("reviewer transport is unavailable")


class RecordingApi:
    def __init__(self, *, output_language: str = "en") -> None:
        self.updates: list[dict[str, Any]] = []
        self.output_language = output_language

    def acquire_proof_generation_claim(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        required_lease_ms: int = 3_600_000,
    ) -> dict[str, Any]:
        assert proof_job_id == "job-1"
        assert claim_id == "11111111-1111-4111-8111-111111111111"
        assert required_lease_ms == 3_600_000
        return {
            "claim_status": "acquired",
            "lease_remaining_ms": 3_600_000,
            "resource": {
                "id": proof_job_id,
                "job_id": proof_job_id,
                "project_id": None,
                "chat_id": "chat-1",
                "output_language": self.output_language,
                "theorem_statement": "invalid statement",
                "formal_statement": None,
                "state": "queued",
                "request_context": {},
                "status_context": None,
                "diagnostics": [],
                "result_artifact_uri": None,
                "lean_code": None,
                "verifier_attestation": None,
                "verification_candidate_id": None,
                "verification_candidate_state": None,
                "generation_session_id": None,
            },
        }

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "queued",
            "chat_id": "chat-1",
            "output_language": self.output_language,
            "theorem_statement": "invalid statement",
            "context": {},
        }

    def update_proof_job(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        state: ProofJobState,
        diagnostics: list[Diagnostic],
        result_artifact_uri: str | None,
        lean_code: str | None,
        context: dict[str, Any],
        verifier_attestation: VerifierAttestation | None = None,
    ) -> dict[str, Any]:
        self.updates.append(
            {
                "proof_job_id": proof_job_id,
                "claim_id": claim_id,
                "state": state,
                "diagnostics": diagnostics,
                "result_artifact_uri": result_artifact_uri,
                "lean_code": lean_code,
                "context": context,
                "verifier_attestation": verifier_attestation,
            }
        )
        return {"id": proof_job_id, "state": state}

    def upsert_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected explanation update: {kwargs}")

    def submit_verification_candidate(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected verification candidate import: {kwargs}")

    def settle_proof_semantic_review(
        self,
        *,
        proof_job_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        _ = (proof_job_id, evidence)
        raise AssertionError("unexpected semantic review settlement")

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]:
        raise AssertionError(f"unexpected clarification fetch: {clarification_id}")

    def update_proof_clarification(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected clarification update: {kwargs}")


@pytest.mark.parametrize(
    ("resumed_state", "expected_states"),
    [
        ("queued", ["retrieving_context", "drafting", "sketching", "proving", "compiling"]),
        (
            "retrieving_context",
            ["retrieving_context", "drafting", "sketching", "proving", "compiling"],
        ),
        ("drafting", ["drafting", "sketching", "proving", "compiling"]),
        ("sketching", ["sketching", "proving", "compiling"]),
        ("proving", ["proving", "compiling"]),
        ("compiling", ["compiling"]),
        ("repairing", ["drafting", "sketching", "proving", "compiling"]),
    ],
)
def test_resumed_generation_keeps_durable_progress_until_replayed_stages_catch_up(
    resumed_state: str,
    expected_states: list[str],
    *,
    acquired_state: str | None = None,
) -> None:
    class ResumedApi(RecordingApi):
        def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
            return {**super().get_proof_job(proof_job_id), "state": resumed_state}

        def acquire_proof_generation_claim(self, **kwargs: Any) -> dict[str, Any]:
            response = super().acquire_proof_generation_claim(**kwargs)
            response["resource"]["state"] = acquired_state or resumed_state
            return response

    class ReplayPipeline:
        def run_statement(self, *, on_status: Any, **_kwargs: Any) -> Any:
            for stage in ("retrieving_context", "drafting", "sketching", "proving", "compiling"):
                on_status(stage, [], None, None, {})
            # Stop before candidate import; this test checks resumed progress publication.
            raise OpenMathStructuringError("generation failed after replay")

    api = ResumedApi()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=api,
        pipeline=ReplayPipeline(),
        explainer=ExplainerThatMustNotRun(),
    )
    assert (
        worker.process_proof_job(
            "job-1",
            claim_id="11111111-1111-4111-8111-111111111111",
            extend_visibility=lambda _seconds: None,
        )
        is True
    )
    assert [update["state"] for update in api.updates] == [*expected_states, "failed"]


def test_resumed_generation_uses_state_from_acquired_claim_not_earlier_read() -> None:
    test_resumed_generation_keeps_durable_progress_until_replayed_stages_catch_up(
        "drafting",
        ["proving", "compiling"],
        acquired_state="proving",
    )


def test_resumed_generation_publishes_failure_before_reaching_previous_stage() -> None:
    class ResumedApi(RecordingApi):
        def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
            return {**super().get_proof_job(proof_job_id), "state": "compiling"}

    api = ResumedApi()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=api,
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )
    assert (
        worker.process_proof_job(
            "job-1",
            claim_id="11111111-1111-4111-8111-111111111111",
            extend_visibility=lambda _seconds: None,
        )
        is True
    )
    assert [update["state"] for update in api.updates] == ["failed"]


class PendingCandidateApi:
    def __init__(self) -> None:
        self.reconciliation_retries: list[tuple[str, str]] = []

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "compiling",
            "chat_id": "chat-1",
            "output_language": "en",
            "theorem_statement": "theorem pending : True := by trivial",
            "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
            "verification_candidate_state": "compiling",
            "diagnostics": [
                {
                    "severity": "info",
                    "message": "Verification is pending.",
                    "code": "pals.verification_pending",
                }
            ],
        }

    def retry_verification_candidate_reconciliation(
        self,
        *,
        proof_job_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        self.reconciliation_retries.append((proof_job_id, candidate_id))
        return {"reconciliation": "accepted"}

    def acquire_proof_generation_claim(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected generation claim: {kwargs}")


class MalformedRepairSeedApi(PendingCandidateApi):
    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "compiling",
            "chat_id": "chat-1",
            "output_language": "en",
            "theorem_statement": "theorem pending : True := by trivial",
            "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
            "verification_candidate_state": "verification_failed",
            "diagnostics": [
                {
                    "severity": "error",
                    "message": "Lean verification failed.",
                    "code": "verifier_compile_failed",
                }
            ],
            "status_context": {"stage": "compiling"},
        }


class StructuringFailurePipeline:
    def prepare_statement(self, *, statement: str) -> ProofRequest:
        return ProofRequest(id="custom_statement", prompt=statement)

    def run_statement(
        self,
        *,
        statement: str,
        formal_statement: str | None = None,
        proof_job_id: str,
        on_status: Any,
        api_repair_seed: ApiRepairSeed | None = None,
        prepared_request: ProofRequest | None = None,
    ) -> None:
        _ = (statement, formal_statement, proof_job_id, on_status, api_repair_seed)
        raise OpenMathStructuringError("ollama returned malformed OpenMath XML")


class RetrievalFailurePipeline:
    def run_statement(
        self,
        *,
        statement: str,
        formal_statement: str | None = None,
        proof_job_id: str,
        on_status: Any,
        api_repair_seed: ApiRepairSeed | None = None,
    ) -> None:
        _ = (statement, formal_statement, proof_job_id, on_status, api_repair_seed)
        raise ProofFlowRetrievalError("reranker_unavailable")


@pytest.mark.parametrize("prior_attempt", [1, 2])
def test_worker_rebuilds_only_api_authoritative_compile_failure_as_a_repair_seed(
    prior_attempt: int,
) -> None:
    prior_route = (
        {
            "route": "sketch",
            "selector_attempts": [
                {"attempt": 1, "outcome": "selected", "diagnostic_code": None, "route": "sketch"}
            ],
        }
        if prior_attempt > 1
        else None
    )
    seed = _api_repair_seed_from_worker_input(
        {
            "state": "compiling",
            "diagnostics": [
                {
                    "severity": "error",
                    "message": "Lean verification failed.",
                    "code": "verifier_compile_failed",
                    "line": None,
                    "column": None,
                }
            ],
            "status_context": {
                "schema_version": "pals.proof-status-context.v1",
                "stage": "compiling",
                "attempt_evidence": {
                    "attempt": prior_attempt,
                    "phase": "compile",
                    "generated": {
                        "lean_code": "theorem old_candidate : True := by\n  exact missing_name\n",
                        "model": "test-model",
                        "provider": "test-provider",
                        "elapsed_ms": 1,
                        "draft": None,
                        "sketch": None,
                        "stage_diagnostics": [],
                    },
                    "verification": {
                        "success": False,
                        "diagnostics": [
                            {
                                "severity": "error",
                                "message": "Unknown identifier missing_name.",
                                "code": "lean.unknown_identifier",
                                "line": 2,
                                "column": 8,
                            }
                        ],
                        "elapsed_ms": 0,
                    },
                    "diagnostics": [],
                    "checkpoint_status": "published",
                    "repair_route": prior_route,
                },
                "repairs_used": prior_attempt - 1,
                "max_repair_attempts": 12,
                "verification_elapsed_ms": 0,
            },
        }
    )

    assert seed is not None
    assert seed.attempt == prior_attempt
    assert seed.repairs_used == prior_attempt - 1
    assert seed.repair_route == prior_route
    assert seed.generated.lean_code.startswith("theorem old_candidate")
    assert [item.code for item in seed.verification.diagnostics] == [
        "verifier_compile_failed",
        "lean.unknown_identifier",
    ]
    assert seed.verification.diagnostics[1].line == 2
    assert "missing_name" in seed.verification.diagnostics[1].message


def test_worker_recognizes_an_api_owned_pending_verification_candidate() -> None:
    assert _has_pending_api_candidate(
        {
            "state": "compiling",
            "verification_candidate_state": "compiling",
            "diagnostics": [],
        }
    )
    assert _has_pending_api_candidate(
        {
            "state": "compiling",
            "diagnostics": [
                {
                    "severity": "info",
                    "message": "Verification is pending.",
                    "code": "pals.verification_pending",
                }
            ],
        }
    )
    assert not _has_pending_api_candidate(
        {
            "state": "compiling",
            "verification_candidate_state": "verification_failed",
            "diagnostics": [
                {
                    "severity": "error",
                    "message": "Lean verification failed.",
                    "code": "verifier_compile_failed",
                }
            ],
        }
    )
    assert _has_api_compile_failure(
        {
            "state": "compiling",
            "verification_candidate_state": "verification_failed",
            "diagnostics": [],
        }
    )


def test_worker_approves_semantically_reviewed_proof_only_after_independent_review() -> None:
    api = SemanticReviewApi()
    reviewer = RecordingSemanticReviewer()
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(explanation_model_timeout_seconds=17),
        ),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=ExplainerThatMustNotRun(),
        proof_reviewer=cast(Any, reviewer),
    )

    acknowledged = worker.process_proof_job("job-semantic")

    assert acknowledged is True
    assert len(api.evidence) == 1
    evidence = api.evidence[0]
    assert evidence["schema_version"] == "pals.proof-semantic-review.v2"
    assert evidence["candidate_id"] == "22222222-2222-4222-8222-222222222222"
    assert evidence["generator_session_id"] == "11111111-1111-4111-8111-111111111111"
    assert (
        evidence["lean_sha256"]
        == hashlib.sha256(b"theorem sample : True := by\n  trivial").hexdigest()
    )
    assert evidence["target_declaration"] == {
        "kind": "theorem",
        "name": "sample",
        "proposition": "True",
    }
    assert evidence["reviewer"] == {
        "provider": "openai",
        "model": "gpt-5.4-mini-2026-03-17",
        "session_id": "33333333-3333-4333-8333-333333333333",
    }
    assert evidence["decision"] == "approved"
    review_input = {
        "theorem_statement": "theorem sample : True := by trivial",
        "formal_statement": "True",
        "target_declaration": evidence["target_declaration"],
        "lean_sha256": evidence["lean_sha256"],
    }
    assert (
        evidence["review_input_sha256"] == hashlib.sha256(rfc8785.dumps(review_input)).hexdigest()
    )
    evidence_without_digest = {
        key: value for key, value in evidence.items() if key != "evidence_sha256"
    }
    assert (
        evidence["evidence_sha256"]
        == hashlib.sha256(rfc8785.dumps(evidence_without_digest)).hexdigest()
    )
    assert reviewer.calls == [
        {
            "theorem_statement": "theorem sample : True := by trivial",
            "formal_statement": "True",
            "target_declaration": LeanTargetDeclaration(
                kind="theorem",
                name="sample",
                proposition="True",
            ),
            "lean_code": "theorem sample : True := by\n  trivial",
            "timeout_seconds": 17,
        }
    ]


def test_worker_rejects_semantic_review_when_independent_review_fails() -> None:
    api = SemanticReviewApi()
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(explanation_model_timeout_seconds=17),
        ),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=ExplainerThatMustNotRun(),
        proof_reviewer=cast(Any, RecordingSemanticReviewer(reject=True)),
    )

    acknowledged = worker.process_proof_job("job-semantic")

    assert acknowledged is True
    assert api.evidence[0]["decision"] == "rejected"


@pytest.mark.parametrize("settled", [True, False])
def test_recipe_review_is_delegated_and_requires_authoritative_terminal_readback(settled) -> None:
    class Api:
        state = "semantic_review"
        def get_proof_job(self, proof_job_id):
            return {
                "id": proof_job_id, "state": self.state, "attempt_source": "recipe",
                "output_language": "en", "theorem_statement": "Show that True.",
                "lean_code": _RECIPE_SOURCE,
                "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
            }
        def settle_recipe_semantic_review(self, **kwargs):
            pytest.fail("Generic worker must never settle Recipe semantic review")
    api = Api()
    calls = []
    class Dispatcher:
        def request(self, **kwargs):
            calls.append(kwargs)
            if settled:
                api.state = "failed"
    reviewer = RecordingSemanticReviewer(reject=True)
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api), pipeline=None, explainer=ExplainerThatMustNotRun(),
        proof_reviewer=reviewer, recipe_review_dispatcher=cast(Any, Dispatcher()),
    )
    visibility = []
    assert (
        worker.process_proof_job("job-recipe-semantic", extend_visibility=visibility.append)
        is settled
    )
    assert calls == [{"proof_job_id": "job-recipe-semantic",
                      "candidate_id": "22222222-2222-4222-8222-222222222222",
                      "timeout_seconds": 79}]
    assert visibility == [109]
    assert reviewer.calls == []


def test_recipe_review_missing_isolated_actor_is_retryable_without_self_review() -> None:
    class Api:
        def get_proof_job(self, proof_job_id):
            return {
                "id": proof_job_id, "state": "semantic_review", "attempt_source": "recipe",
                "output_language": "en", "theorem_statement": "True", "lean_code": _RECIPE_SOURCE,
                "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
            }
    reviewer = RecordingSemanticReviewer(reject=True)
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()), api_client=cast(Any, Api()),
        pipeline=None, explainer=ExplainerThatMustNotRun(), proof_reviewer=reviewer,
    )
    assert worker.process_proof_job("job-recipe") is False
    assert reviewer.calls == []


@pytest.mark.parametrize(
    "proof_reviewer",
    [None, RaisingSemanticReviewer()],
    ids=["unavailable", "raises"],
)
def test_worker_durably_stops_without_rejection_when_the_independent_reviewer_is_unavailable(
    proof_reviewer: Any,
) -> None:
    api = SemanticReviewApi()
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(explanation_model_timeout_seconds=17),
        ),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=ExplainerThatMustNotRun(),
        proof_reviewer=proof_reviewer,
        uuid4_factory=lambda: uuid.UUID("44444444-4444-4444-8444-444444444444"),
    )

    acknowledged = worker.process_proof_job("job-semantic")

    assert acknowledged is True
    assert api.evidence == []
    assert api.operational_failure["failure_kind"] == "internal"
    assert "decision" not in api.operational_failure
    assert "reviewer" not in api.operational_failure


def test_worker_waits_for_api_candidate_reconciliation_before_regenerating() -> None:
    clock = [0.0]
    sleeps: list[float] = []
    visibility: list[int] = []

    def advance(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    api = PendingCandidateApi()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=cast(Any, api),
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
        monotonic=lambda: clock[0],
        sleep=advance,
    )

    acknowledged = worker.process_proof_job(
        "job-pending",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=visibility.append,
    )

    assert acknowledged is False
    assert api.reconciliation_retries == [("job-pending", "22222222-2222-4222-8222-222222222222")]
    assert visibility == [360]
    assert sum(sleeps) == 330.0


def test_worker_stops_candidate_polling_when_api_exposes_compile_failure() -> None:
    sleeps: list[float] = []
    visibility: list[int] = []
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=cast(Any, MalformedRepairSeedApi()),
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
        sleep=sleeps.append,
    )

    settled = worker._wait_for_candidate_reconciliation(
        proof_job_id="job-failed-candidate",
        extend_visibility=visibility.append,
        refresh_visibility=True,
    )

    assert settled is not None
    assert settled["state"] == "compiling"
    assert visibility == [360]
    assert sleeps == []


def test_worker_does_not_claim_when_the_api_compile_failure_lacks_a_repair_seed() -> None:
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=cast(Any, MalformedRepairSeedApi()),
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )

    acknowledged = worker.process_proof_job(
        "job-malformed-seed",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )

    assert acknowledged is False


def test_worker_marks_openmath_structuring_failure_as_terminal() -> None:
    api = RecordingApi()
    settings = cast(
        AgentSettings,
        SimpleNamespace(
            llm_provider="ollama",
            ollama_model="qwen2.5:3b",
            openai_model="gpt-5.4-nano",
        ),
    )
    worker = SqsProofWorker(
        settings=settings,
        api_client=api,
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )

    worker.process_proof_job(
        "job-1",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )

    assert len(api.updates) == 1
    update = api.updates[0]
    assert update["state"] == "failed"
    assert update["result_artifact_uri"] is None
    assert update["lean_code"] is None
    assert update["verifier_attestation"] is None
    assert update["diagnostics"][0].code == "pals.openmath_structuring_failed"
    assert update["context"]["stage"] == "failed"
    assert update["context"]["schema_version"] == "pals.proof-status-context.v1"
    assert update["context"]["termination_reason"] == "non_repairable_failure"


@pytest.mark.parametrize(
    ("language", "expected_message"),
    [
        ("en", "The theorem statement could not be structured."),
        ("ja", "定理の記述を構造化できませんでした。"),
        ("zh-Hans", "无法结构化定理陈述。"),
        ("zh-Hant", "無法結構化定理陳述。"),
    ],
)
def test_core_004_localizes_proof_generation_failures_to_the_chat_language(
    language: str,
    expected_message: str,
) -> None:
    api = RecordingApi(output_language=language)
    settings = cast(
        AgentSettings,
        SimpleNamespace(
            llm_provider="ollama",
            ollama_model="qwen2.5:3b",
            openai_model="gpt-5.4-nano",
        ),
    )
    worker = SqsProofWorker(
        settings=settings,
        api_client=api,
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )

    assert (
        worker.process_proof_job(
            "job-1",
            claim_id="11111111-1111-4111-8111-111111111111",
            extend_visibility=lambda _seconds: None,
        )
        is True
    )

    failure = api.updates[-1]["diagnostics"][0]
    assert failure.code == "pals.openmath_structuring_failed"
    assert failure.message == expected_message


def test_core_004_rejects_an_invalid_chat_language_without_falling_back() -> None:
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(
                llm_provider="ollama",
                ollama_model="qwen2.5:3b",
                openai_model="gpt-5.4-nano",
            ),
        ),
        api_client=RecordingApi(output_language="invalid"),
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )

    with pytest.raises(ValueError, match="output language is invalid"):
        worker.process_proof_job(
            "job-1",
            claim_id="11111111-1111-4111-8111-111111111111",
            extend_visibility=lambda _seconds: None,
        )


def test_worker_marks_closed_proof_flow_retrieval_error_as_terminal() -> None:
    api = RecordingApi()
    settings = cast(
        AgentSettings,
        SimpleNamespace(
            llm_provider="ollama",
            ollama_model="qwen2.5:3b",
            openai_model="gpt-5.4-nano",
        ),
    )
    worker = SqsProofWorker(
        settings=settings,
        api_client=api,
        pipeline=RetrievalFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )

    worker.process_proof_job(
        "job-1",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )

    assert len(api.updates) == 1
    update = api.updates[0]
    assert update["state"] == "failed"
    assert update["diagnostics"][0].code == "pals.proof_flow_retrieval_failed"
    assert update["context"]["stage"] == "failed"


def test_worker_marks_invalid_lazy_proof_pipeline_configuration_as_terminal() -> None:
    api = RecordingApi()
    settings = cast(
        AgentSettings,
        SimpleNamespace(
            llm_provider="ollama",
            ollama_model="qwen2.5:3b",
            openai_model="gpt-5.4-nano",
        ),
    )

    def invalid_pipeline_factory() -> RetrievalFailurePipeline:
        raise ValueError("PFI runtime provenance digest is invalid")

    worker = SqsProofWorker(
        settings=settings,
        api_client=api,
        pipeline=None,
        explainer=ExplainerThatMustNotRun(),
        pipeline_factory=invalid_pipeline_factory,
    )

    acknowledged = worker.process_proof_job(
        "job-1",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )

    assert acknowledged is True
    assert len(api.updates) == 1
    assert api.updates[0]["state"] == "failed"
    assert api.updates[0]["diagnostics"][0].code == "pals.proof_flow_retrieval_failed"


@pytest.mark.parametrize("formal_target", [True, False])
@pytest.mark.parametrize("ambiguous_import", [True, False])
def test_selected_recipe_submits_exact_bytes_without_constructing_pipeline_or_repair(
    formal_target: bool, ambiguous_import: bool,
) -> None:
    class RecipeApi:
        def __init__(self) -> None:
            self.recipe_submissions: list[dict[str, Any]] = []
            self.claims = 0
            self.retries = 0
            self.binding_reads = 0

        def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
            if self.recipe_submissions:
                return {
                    "id": proof_job_id,
                    "state": "compiling",
                    "diagnostics": [
                        {
                            "severity": "info",
                            "message": "Verification is pending.",
                            "code": "pals.verification_pending",
                        }
                    ],
                }
            return {
                "id": proof_job_id,
                "state": "queued",
                "theorem_statement": "Show that True.",
                "output_language": "en",
                "request_context": (
                    {"formal_statement": "example : True := by trivial"} if formal_target else {}
                ),
            }

        def acquire_proof_generation_claim(self, **_kwargs: Any) -> dict[str, Any]:
            self.claims += 1
            return {
                "claim_status": "acquired",
                "lease_remaining_ms": 3_600_000,
                "resource": {
                    "id": "job-1",
                    "job_id": "job-1",
                    "project_id": None,
                    "chat_id": "chat-1",
                    "output_language": "en",
                    "theorem_statement": "Show that True.",
                    "formal_statement": "example : True := by trivial",
                    "state": "queued",
                    "request_context": {"formal_statement": "example : True := by trivial"},
                    "status_context": None,
                    "diagnostics": [],
                    "result_artifact_uri": None,
                    "lean_code": None,
                    "verifier_attestation": None,
                    "verification_candidate_id": None,
                    "verification_candidate_state": None,
                    "generation_session_id": None,
                },
            }

        def submit_recipe_verification_candidate(self, **kwargs: Any) -> dict[str, Any]:
            self.recipe_submissions.append(kwargs)
            if ambiguous_import:
                raise PalsApiError("committed, but notification failed")
            return {"candidate_status": "compiling"}

        def get_verification_candidate_binding(self, **kwargs: Any) -> dict[str, Any]:
            self.binding_reads += 1
            submitted = self.recipe_submissions[-1]
            return {
                "schema_version": "pals.verification-candidate-binding.v1",
                **kwargs,
                "mutation_claim_id": submitted["mutation_claim_id"],
                "lean_sha256": hashlib.sha256(submitted["lean_code"].encode()).hexdigest(),
                "result_artifact_uri": submitted["result_artifact_uri"],
                "source_binding_sha256": hashlib.sha256(
                    rfc8785.dumps(submitted["candidate_source"])
                ).hexdigest(),
                "candidate_status": "compiling",
            }

        def retry_verification_candidate_reconciliation(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["candidate_id"] == self.recipe_submissions[-1]["candidate_id"]
            self.retries += 1
            raise PalsApiError("notifier remains unavailable")

    class PipelineThatMustNotRun:
        prepared_count = 0

        def prepare_statement(self, *, statement: str) -> ProofRequest:
            from dataclasses import replace

            from tests.unit.test_recipe_attempt import exact_draft_request

            self.prepared_count += 1
            return replace(exact_draft_request(), prompt=statement)

        def run_statement(self, **_kwargs: Any) -> Any:
            raise AssertionError("selected Recipe must not invoke the generation pipeline")

    api = RecipeApi()
    selector = _RecipeSelector()
    clock = [0.0]

    def advance(seconds: float) -> None:
        clock[0] += seconds

    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(
                artifacts_bucket="pals-artifacts",
                max_repair_attempts=12,
            ),
        ),
        api_client=cast(Any, api),
        pipeline=cast(Any, PipelineThatMustNotRun()),
        explainer=ExplainerThatMustNotRun(),
        recipe_attempt_planner=RecipeAttemptPlannerV1(selector, _RECIPE_TOOLCHAIN),
        monotonic=lambda: clock[0],
        sleep=advance,
    )

    assert not worker.process_proof_job(
        "job-1",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )
    assert selector.calls == 1
    assert selector.query is not None
    if formal_target:
        assert selector.query.draft_revision is None
    else:
        assert selector.query.draft_revision is not None
        assert selector.query.draft_revision.draft_id == "continuous_square"
        assert selector.query.proof_method_tag == "epsilon_delta"
        assert cast(PipelineThatMustNotRun, worker.pipeline).prepared_count == 1
    assert api.claims == 1
    assert api.binding_reads == int(ambiguous_import)
    assert api.retries == int(ambiguous_import)
    assert len(api.recipe_submissions) == 1
    submission = api.recipe_submissions[0]
    assert submission["lean_code"] == _RECIPE_SOURCE
    assert (
        submission["candidate_source"]["materialized_source_sha256"]
        == hashlib.sha256(_RECIPE_SOURCE.encode("utf-8")).hexdigest()
    )
    assert not {"model", "provider", "raw_model_output", "repair_route"} & set(
        submission["candidate_source"]
    )


def test_recipe_not_selected_keeps_the_existing_generation_pipeline() -> None:
    class TraceRecordingApi(RecordingApi):
        traces: list[dict[str, str]] = []

        def record_no_recipe_attempt(self, **kwargs: str) -> dict[str, str]:
            self.traces.append(kwargs)
            return {"schema_version": "pals.recipe-attempt-trace-response.v1", "status": "linked"}

    api = TraceRecordingApi()
    selector = _NoRecipeSelector()
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(max_repair_attempts=12),
        ),
        api_client=api,
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
        recipe_attempt_planner=RecipeAttemptPlannerV1(selector, _RECIPE_TOOLCHAIN),
    )

    assert worker.process_proof_job(
        "job-1",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )
    assert selector.calls == 1
    assert api.traces == [{
        "proof_job_id": "job-1", "mutation_claim_id": "11111111-1111-4111-8111-111111111111",
        "request_sha256": "a" * 64,
    }]
    assert api.updates[-1]["state"] == "failed"
    assert api.updates[-1]["diagnostics"][0].code == "pals.openmath_structuring_failed"


@pytest.mark.parametrize("mismatch", [
    "mutation_claim_id", "candidate_id", "proof_job_id", "lean_sha256",
    "result_artifact_uri", "source_binding_sha256", "candidate_status", "unavailable",
])
def test_semantic_review_never_sends_legacy_or_raced_candidate_to_model(mismatch: str) -> None:
    class StaleApi(SemanticReviewApi):
        def get_verification_candidate_binding(self, **kwargs: Any) -> dict[str, Any]:
            if mismatch == "unavailable":
                raise PalsApiError("binding read unavailable")
            result = super().get_verification_candidate_binding(**kwargs)
            result[mismatch] = (
                "verified" if mismatch == "candidate_status" else
                "33333333-3333-4333-8333-333333333333"
            )
            return result

    api = StaleApi()
    reviewer = RecordingSemanticReviewer()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api), pipeline=None, explainer=ExplainerThatMustNotRun(),
        proof_reviewer=cast(Any, reviewer),
    )
    assert not worker.process_proof_job("job-semantic")
    assert reviewer.calls == []
    assert api.evidence == []


def test_semantic_review_visibility_failure_prevents_model_call() -> None:
    api = SemanticReviewApi()
    reviewer = RecordingSemanticReviewer()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api), pipeline=None, explainer=ExplainerThatMustNotRun(),
        proof_reviewer=cast(Any, reviewer),
    )
    def unavailable(seconds: int) -> None:
        assert seconds == 81
        raise RuntimeError("queue unavailable")
    assert not worker.process_proof_job("job-semantic", extend_visibility=unavailable)
    assert not reviewer.calls and not api.evidence


@pytest.mark.parametrize("timeout", [True, 0, -1, 301, float("nan"), float("inf")])
def test_semantic_review_rejects_invalid_visibility_timeout_before_model_call(timeout: Any) -> None:
    reviewer = RecordingSemanticReviewer()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=timeout)),
        api_client=cast(Any, SemanticReviewApi()), pipeline=None,
        explainer=ExplainerThatMustNotRun(), proof_reviewer=cast(Any, reviewer),
    )
    assert not worker.process_proof_job("job-semantic", extend_visibility=lambda _seconds: None)
    assert not reviewer.calls


def test_unavailable_settlement_response_loss_acks_durable_failure_without_second_model_call():
    class Api(SemanticReviewApi):
        def settle_proof_semantic_review_unavailable(self, **kwargs):
            super().settle_proof_semantic_review_unavailable(**kwargs)
            raise PalsApiError("settlement response lost")

    class Reviewer:
        calls = 0

        def review_proof(self, **kwargs):
            self.calls += 1
            raise RuntimeError("provider unavailable")

    api, reviewer = Api(), Reviewer()
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(explanation_model_timeout_seconds=17)),
        api_client=cast(Any, api), pipeline=None, explainer=ExplainerThatMustNotRun(),
        proof_reviewer=cast(Any, reviewer),
    )
    assert worker.process_proof_job("job-semantic") is False
    assert worker.process_proof_job("job-semantic") is True
    assert reviewer.calls == 1
    assert api.evidence == []
