from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from pals_agent.api_client import VerifierAttestation
from pals_agent.models import Diagnostic, ProofJobState
from pals_agent.openmath import OpenMathStructuringError
from pals_agent.pipeline import ApiRepairSeed
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError
from pals_agent.settings import AgentSettings
from pals_agent.worker import (
    SqsProofWorker,
    _api_repair_seed_from_worker_input,
    _has_pending_api_candidate,
    _verified_candidate_matches_statement,
)


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


class RecordingApi:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

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
                "theorem_statement": "invalid statement",
                "formal_statement": None,
                "state": "queued",
                "request_context": {},
                "status_context": None,
                "diagnostics": [],
                "result_artifact_uri": None,
                "lean_code": None,
                "verifier_attestation": None,
            },
        }

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "queued",
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

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]:
        raise AssertionError(f"unexpected clarification fetch: {clarification_id}")

    def update_proof_clarification(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected clarification update: {kwargs}")


class PendingCandidateApi:
    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "compiling",
            "theorem_statement": "theorem pending : True := by trivial",
            "diagnostics": [
                {
                    "severity": "info",
                    "message": "Verification is pending.",
                    "code": "pals.verification_pending",
                }
            ],
        }

    def acquire_proof_generation_claim(self, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected generation claim: {kwargs}")


class MalformedRepairSeedApi(PendingCandidateApi):
    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "compiling",
            "theorem_statement": "theorem pending : True := by trivial",
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


def test_worker_rebuilds_only_api_authoritative_compile_failure_as_a_repair_seed() -> None:
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
                    "attempt": 1,
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
                        "diagnostics": [],
                        "elapsed_ms": 0,
                    },
                    "diagnostics": [],
                    "checkpoint_status": "published",
                    "repair_route": None,
                },
                "repairs_used": 0,
                "max_repair_attempts": 12,
                "verification_elapsed_ms": 0,
            },
        }
    )

    assert seed is not None
    assert seed.attempt == 1
    assert seed.repairs_used == 0
    assert seed.generated.lean_code.startswith("theorem old_candidate")
    assert [item.code for item in seed.verification.diagnostics] == [
        "verifier_compile_failed"
    ]


def test_worker_recognizes_an_api_owned_pending_verification_candidate() -> None:
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
            "diagnostics": [
                {
                    "severity": "error",
                    "message": "Lean verification failed.",
                    "code": "verifier_compile_failed",
                }
            ],
        }
    )


def test_worker_waits_for_api_candidate_reconciliation_before_regenerating() -> None:
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()),
        api_client=cast(Any, PendingCandidateApi()),
        pipeline=StructuringFailurePipeline(),
        explainer=ExplainerThatMustNotRun(),
    )

    acknowledged = worker.process_proof_job(
        "job-pending",
        claim_id="11111111-1111-4111-8111-111111111111",
        extend_visibility=lambda _seconds: None,
    )

    assert acknowledged is False


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
