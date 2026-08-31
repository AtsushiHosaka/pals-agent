from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY

import pytest
import rfc8785

from pals_agent.api_client import (
    PalsApiError,
    ProofJobNotFoundError,
    VerifierAttestation,
)
from pals_agent.artifacts import FileArtifactStore
from pals_agent.explanations import (
    ExplanationGenerationError,
    ExplanationSection,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReview,
    ProofSemanticReview,
)
from pals_agent.models import (
    Diagnostic,
    GeneratedProof,
    ProofDraft,
    ProofJobState,
    ProofRequest,
    VerificationResult,
)
from pals_agent.openmath import LLMStatementOpenMathStructurer
from pals_agent.pipeline import ApiRepairSeed, ProofPipeline
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, parse_agent_task

VERIFIED_LEAN_CODE = (Path(__file__).parents[1] / "fixtures" / "PalsX2Verified.lean").read_text(
    encoding="utf-8"
)
VERIFIED_LEAN_SHA256 = hashlib.sha256(VERIFIED_LEAN_CODE.encode("utf-8")).hexdigest()
VERIFIED_ARTIFACT_URI = f"s3://manual-fixtures/manual-fixtures/{VERIFIED_LEAN_SHA256}.lean"


class FakeApi:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []
        self.events: list[str] = []
        self.explanation_updates: list[dict[str, Any]] = []
        self.clarification_updates: list[dict[str, Any]] = []
        self.state = "queued"
        self.chat_id = "chat-1"
        self.output_language = "ja"
        self.theorem_statement = "x^2が連続であることを示せ"
        self.context: dict[str, Any] = {
            "fixture_provenance": {
                "kind": "manual_verified_fixture",
                "artifact_uri": VERIFIED_ARTIFACT_URI,
                "model_generated": False,
                "sha256": VERIFIED_LEAN_SHA256,
                "verification_success": True,
                "verifier": "isolated_mtls_http_lean_verifier",
            }
        }
        self.lean_code: str | None = None
        self.status_context: dict[str, Any] | None = None
        self.verification_candidates: list[dict[str, Any]] = []
        self.verification_candidate_id: str | None = None
        self.reconciliation_retries: list[tuple[str, str]] = []
        self.generation_session_id: str | None = None
        self.clarification_input: dict[str, Any] = {}
        self.explanation_existing_state: str | None = None

    def acquire_proof_generation_claim(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        required_lease_ms: int = 3_600_000,
    ) -> dict[str, Any]:
        assert claim_id
        assert required_lease_ms == 3_600_000
        self.events.append("proof_generation_claim")
        self.generation_session_id = claim_id
        return _claim_envelope(
            "acquired",
            3_600_000,
            resource_kind="proof_job",
            resource_id=proof_job_id,
        )

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        self.events.append("worker_input")
        return {
            "id": proof_job_id,
            "state": self.state,
            "chat_id": self.chat_id,
            "output_language": self.output_language,
            "theorem_statement": self.theorem_statement,
            "request_context": self.context,
            "lean_code": self.lean_code,
            "status_context": self.status_context,
            "verification_candidate_id": self.verification_candidate_id,
            "verification_candidate_state": (
                "compiling"
                if self.state == "compiling" and self.verification_candidate_id is not None
                else None
            ),
            "generation_session_id": self.generation_session_id,
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
        self.events.append(f"proof_update:{state}")
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
        self.status_context = context
        return {"id": proof_job_id, "state": state}

    def submit_verification_candidate(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append("verification_candidate")
        self.verification_candidates.append(kwargs)
        self.state = "semantic_review"
        self.lean_code = kwargs["lean_code"]
        self.verification_candidate_id = kwargs["candidate_id"]
        return {"candidate_status": "compiling"}

    def retry_verification_candidate_reconciliation(
        self,
        *,
        proof_job_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        self.reconciliation_retries.append((proof_job_id, candidate_id))
        return {"reconciliation": "accepted"}

    def settle_proof_semantic_review(
        self,
        *,
        proof_job_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self.events.append("semantic_review")
        self.state = "verified" if evidence["decision"] == "approved" else "failed"
        return {"id": proof_job_id, "state": self.state}


    def upsert_proof_explanation(
        self,
        *,
        proof_job_id: str,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        review_evidence: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]:
        if state == "generating" and self.explanation_existing_state == "completed":
            return _claim_envelope("terminal", None, resource_id=proof_job_id)
        update = {
            "proof_job_id": proof_job_id,
            "state": state,
            "claim_id": claim_id,
            "required_lease_ms": required_lease_ms,
            "content": content,
            "review_evidence": review_evidence,
            "diagnostics": diagnostics or [],
        }
        self.explanation_updates.append(update)
        return _claim_envelope(
            "acquired" if state == "generating" else "terminal",
            600_000 if state == "generating" else None,
            resource_id=proof_job_id,
        )

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]:
        return {
            "dispatch_schema_version": "pals.proof-clarification-dispatch.v1",
            "id": clarification_id,
            **self.clarification_input,
        }

    def update_proof_clarification(
        self,
        *,
        clarification_id: str,
        proof_job_id: str | None = None,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        review_evidence: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]:
        update = {
            "id": clarification_id,
            "proof_job_id": proof_job_id,
            "state": state,
            "claim_id": claim_id,
            "required_lease_ms": required_lease_ms,
            "content": content,
            "review_evidence": review_evidence,
            "diagnostics": diagnostics or [],
        }
        self.clarification_updates.append(update)
        return _claim_envelope(
            "acquired" if state == "generating" else "terminal",
            600_000 if state == "generating" else None,
            resource_kind="clarification",
            resource_id=clarification_id,
        )


class DelayedCandidateApi(FakeApi):
    def __init__(self, *, compiling_reads: int = 2) -> None:
        super().__init__()
        self.compiling_reads = compiling_reads
        self.candidate_reads = 0

    def submit_verification_candidate(self, **kwargs: Any) -> dict[str, Any]:
        response = super().submit_verification_candidate(**kwargs)
        self.state = "compiling"
        return response

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        if self.state == "compiling" and self.verification_candidate_id is not None:
            self.candidate_reads += 1
            if self.candidate_reads > self.compiling_reads:
                self.state = "semantic_review"
                self.status_context = {
                    "target_declaration": {
                        "kind": "theorem",
                        "name": "x2_continuous",
                        "proposition": "Continuous (fun y : ℝ => y ^ 2)",
                    }
                }
        payload = super().get_proof_job(proof_job_id)
        payload["diagnostics"] = (
            [
                {
                    "severity": "info",
                    "message": "Verification is pending.",
                    "code": "pals.verification_pending",
                }
            ]
            if self.state == "compiling"
            else []
        )
        return payload


class FakeExplainer:
    def __init__(self) -> None:
        self.explain_calls: list[dict[str, Any]] = []
        self.clarify_calls: list[dict[str, Any]] = []

    def explain(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        verified: bool,
        language: str = "ja",
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofExplanation:
        self.explain_calls.append(
            {
                "theorem_statement": theorem_statement,
                "lean_code": lean_code,
                "verified": verified,
                "language": language,
                "deadline": deadline,
                "timeout_seconds": timeout_seconds,
            }
        )
        return _proof_explanation(lean_code)

    def clarify(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        verified: bool,
        explanation: ProofExplanation,
        section_id: str,
        question: str,
        selected_text: str = "",
        after_clarification_id: str | None = None,
        language: str = "ja",
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofClarification:
        self.clarify_calls.append(
            {
                "theorem_statement": theorem_statement,
                "lean_code": lean_code,
                "verified": verified,
                "explanation": explanation,
                "section_id": section_id,
                "question": question,
                "selected_text": selected_text,
                "after_clarification_id": after_clarification_id,
                "language": language,
                "deadline": deadline,
                "timeout_seconds": timeout_seconds,
            }
        )
        return ProofClarification(
            section_id=section_id,
            question=question,
            answer=(
                "この行は既存定理を現在のゴールへ適用し、残っている証明目標を"
                "その場で直接解決する役割を持っています。"
            ),
            key_points=("既存定理を使います。", "現在のゴールを閉じます。"),
            references=explanation.sections[0].references,
            model="explain-model",
            provider="openai",
            prompt="private prompt",
            raw_model_output="private raw output",
            elapsed_ms=4,
        )


class FailingExplainer(FakeExplainer):
    def explain(self, **kwargs: Any) -> ProofExplanation:
        _ = kwargs
        raise ExplanationGenerationError(
            "invalid grounded output",
            attempt_outputs=("bad one", "bad two"),
        )

    def clarify(self, **kwargs: Any) -> ProofClarification:
        _ = kwargs
        raise ExplanationGenerationError(
            "invalid clarification",
            attempt_outputs=("bad one", "bad two"),
        )


class FakeOutputReviewer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.explanation_calls: list[dict[str, Any]] = []
        self.clarification_calls: list[dict[str, Any]] = []

    def review_explanation(self, **kwargs: Any) -> ProofOutputReview:
        self.explanation_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ProofOutputReview(
            kind="explanation",
            reviewer_provider="test-reviewer",
            reviewer_model="review-model",
            session_id="standalone-review-session",
            rationale="The explanation is grounded in the verified Lean source.",
        )

    def review_clarification(self, **kwargs: Any) -> ProofOutputReview:
        self.clarification_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return ProofOutputReview(
            kind="clarification",
            reviewer_provider="test-reviewer",
            reviewer_model="review-model",
            session_id="standalone-review-session",
            rationale="The clarification is grounded in the verified Lean source.",
        )


class FakeSemanticReviewer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def review_proof(self, **kwargs: Any) -> ProofSemanticReview:
        self.calls.append(kwargs)
        return ProofSemanticReview(
            decision="approved",
            rationale="The target and Lean proof match the learner request.",
            reviewer_provider="openai",
            reviewer_model="gpt-5.4-mini-2026-03-17",
            session_id="33333333-3333-4333-8333-333333333333",
        )


def _proof_explanation(lean_code: str) -> ProofExplanation:
    lines = lean_code.splitlines()
    line_number = len(lines)
    return ProofExplanation(
        overview="検証済み Lean 証明の概要です。",
        sections=(
            ExplanationSection(
                id="finish-proof",
                title="証明を閉じる",
                summary="最後の行でゴールを解きます。",
                references=(
                    LeanLineReference(
                        start_line=line_number,
                        end_line=line_number,
                        excerpt=lines[-1],
                    ),
                ),
            ),
        ),
        conclusion="証明が完了します。",
        model="explain-model",
        provider="openai",
        prompt="private prompt",
        raw_model_output="private raw output",
        elapsed_ms=3,
    )


class MissingJobApi(FakeApi):
    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        raise ProofJobNotFoundError(
            "PALS API returned HTTP 404",
            status_code=404,
            error_code="proof_job_not_found",
        )


class UnavailableApi(FakeApi):
    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        raise PalsApiError(
            "PALS API is temporarily unavailable",
            status_code=503,
            error_code="proof_persistence_failed",
        )


class CandidateImportUnavailableApi(FakeApi):
    def submit_verification_candidate(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append("verification_candidate")
        self.verification_candidates.append(kwargs)
        raise PalsApiError(
            "candidate import is temporarily unavailable",
            status_code=503,
            error_code="proof_verification_candidate_unavailable",
        )


class TerminalExplanationApi(FakeApi):
    def upsert_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        return _claim_envelope(
            "terminal",
            None,
            resource_id=str(kwargs["proof_job_id"]),
        )


class TerminalClarificationRaceApi(FakeApi):
    def __init__(self) -> None:
        super().__init__()
        self.fetch_count = 0

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]:
        self.fetch_count += 1
        return {
            "dispatch_schema_version": "pals.proof-clarification-dispatch.v1",
            "id": clarification_id,
            "state": "queued" if self.fetch_count == 1 else "completed",
        }

    def update_proof_clarification(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        raise PalsApiError(
            "terminal clarification",
            status_code=409,
            error_code="proof_clarification_transition_invalid",
        )


class FakePipeline:
    def __init__(self) -> None:
        self.formal_statement: str | None = None

    def run_statement(
        self,
        *,
        statement: str,
        formal_statement: str | None = None,
        proof_job_id: str,
        on_status: Any,
        api_repair_seed: ApiRepairSeed | None = None,
    ) -> Any:
        self.formal_statement = formal_statement
        assert api_repair_seed is None
        assert statement == "x^2が連続であることを示せ"
        on_status(
            "drafting",
            [],
            None,
            None,
            {"problem_id": "continuous_square", "dsp_stage": "draft"},
        )
        on_status(
            "sketching",
            [],
            None,
            None,
            {"problem_id": "continuous_square", "dsp_stage": "sketch"},
        )
        on_status(
            "proving",
            [],
            None,
            "import Mathlib\n\n-- proving",
            {"problem_id": "continuous_square"},
        )
        on_status(
            "compiling",
            [],
            VERIFIED_ARTIFACT_URI,
            VERIFIED_LEAN_CODE,
            {
                "lean_artifact_uri": "s3://bucket/proof-jobs/job-1/result.lean",
                "attempt_evidence": {
                    "attempt": 1,
                    "phase": "compile",
                    "generated": {
                        "lean_code": "theorem pals_continuous_square : True := by trivial",
                        "model": "fake-model",
                        "provider": "fake-provider",
                        "elapsed_ms": 1,
                        "draft": None,
                        "sketch": None,
                        "stage_diagnostics": [],
                    },
                    "verification": {
                        "success": False,
                        "diagnostics": [],
                        "elapsed_ms": 1,
                    },
                    "diagnostics": [],
                    "checkpoint_status": "published",
                    "repair_route": None,
                },
                "repairs_used": 0,
                "max_repair_attempts": 12,
                "verification_elapsed_ms": 1,
                "termination_reason": "awaiting_api_reconciliation",
                "termination_event": {
                    "reason": "awaiting_api_reconciliation",
                    "attempt": 1,
                    "source": "api_reconciliation",
                },
            },
        )
        return SimpleNamespace(verification_pending=True)


class ExplodingPipeline(FakePipeline):
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
        raise RuntimeError("pipeline failed")


class InvalidXMLClient:
    def generate(self, *, model: str, prompt: str) -> str:
        _ = (model, prompt)
        return "This is not OpenMath XML."


class InvalidOpenMathCatalog:
    def __init__(self) -> None:
        self.structurer = LLMStatementOpenMathStructurer(
            client=InvalidXMLClient(),
            model="qwen2.5:3b",
            provider="ollama",
        )

    def find_by_statement(self, statement: str) -> ProofDraft | None:
        self.structurer.structure(statement)
        return None

    def find_by_openmath(self, openmath_xml: str) -> ProofDraft | None:
        _ = openmath_xml
        return None

    def find_by_id(self, draft_id: str) -> ProofDraft | None:
        _ = draft_id
        return None


class CountingGenerator:
    model = "never-called"

    def __init__(self) -> None:
        self.calls: list[ProofRequest] = []

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self.calls.append(request)
        return GeneratedProof(lean_code="", model=self.model, raw_model_output="")


class CountingVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        return VerificationResult(
            success=False,
            diagnostics=[],
            stdout="",
            stderr="",
            elapsed_ms=0,
        )


class FakeSqsClient:
    def __init__(self, messages: list[dict[str, str]]) -> None:
        self.messages = messages
        self.deleted: list[dict[str, str]] = []
        self.visibility: list[dict[str, Any]] = []
        self.received_queue_url: str | None = None
        self.receive_kwargs: dict[str, Any] = {}

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        self.received_queue_url = str(kwargs["QueueUrl"])
        self.receive_kwargs = kwargs
        if not self.messages:
            return {}
        messages: list[dict[str, Any]] = []
        for position, supplied in enumerate(self.messages):
            message: dict[str, Any] = dict(supplied)
            body = message.get("Body")
            message.setdefault("MessageId", f"message-{position}")
            message.setdefault(
                "MessageAttributes",
                {}
                if isinstance(body, str) and body.startswith("{")
                else {
                    "proof_job_id": {
                        "DataType": "String",
                        "StringValue": str(body),
                    }
                },
            )
            messages.append(message)
        return {"Messages": messages}

    def delete_message(self, **kwargs: Any) -> None:
        self.deleted.append(
            {
                "QueueUrl": str(kwargs["QueueUrl"]),
                "ReceiptHandle": str(kwargs["ReceiptHandle"]),
            }
        )

    def change_message_visibility(self, **kwargs: Any) -> None:
        self.visibility.append(kwargs)


def _claim_envelope(
    status: str,
    lease_remaining_ms: int | None,
    *,
    resource_kind: str = "explanation",
    resource_id: str = "job-1",
) -> dict[str, Any]:
    if resource_kind == "proof_job":
        state = "queued" if status in {"acquired", "busy"} else "failed"
    else:
        state = "generating" if status in {"acquired", "busy"} else "failed"
    common: dict[str, Any] = {
        "state": state,
        "content": None,
        "created_at": "2026-07-14T00:00:00+00:00",
        "updated_at": "2026-07-14T00:00:00+00:00",
        "diagnostics": [],
    }
    if resource_kind == "proof_job":
        resource: dict[str, Any] = {
            "id": resource_id,
            "job_id": resource_id,
            "project_id": None,
            "chat_id": "chat-1",
            "output_language": "ja",
            "theorem_statement": "x^2が連続であることを示せ",
            "formal_statement": None,
            "state": state,
            "request_context": {},
            "status_context": None,
            "diagnostics": [],
            "result_artifact_uri": None,
            "lean_code": None,
            "verifier_attestation": None,
            "verification_candidate_id": None,
            "verification_candidate_state": None,
            "generation_session_id": None,
        }
    elif resource_kind == "explanation":
        resource = {"proof_job_id": resource_id, **common}
    else:
        resource = {
            "id": resource_id,
            "proof_job_id": "job-1",
            "section_id": "finish",
            "selected_text": "trivial",
            "after_clarification_id": None,
            "question": "なぜ trivial でよいのですか？",
            **common,
        }
    return {
        "claim_status": status,
        "lease_remaining_ms": lease_remaining_ms,
        "resource": resource,
    }


_TEST_CLAIM_ID = "11111111-1111-4111-8111-111111111111"


def _process_proof(worker: SqsProofWorker, proof_job_id: str) -> bool:
    return worker.process_proof_job(
        proof_job_id,
        claim_id=_TEST_CLAIM_ID,
        extend_visibility=lambda _seconds: None,
    )


def _process_clarification(worker: SqsProofWorker, clarification_id: str) -> bool:
    return worker.process_clarification(
        clarification_id,
        claim_id=_TEST_CLAIM_ID,
        extend_visibility=lambda _seconds: None,
    )


def _settings() -> AgentSettings:
    return AgentSettings(
        llm_provider="ollama",
        aws_region="ap-northeast-1",
        aws_endpoint_url="http://localstack:4566",
        proof_jobs_queue_url="http://localstack:4566/000000000000/q",
        artifacts_bucket="bucket",
        api_base_url="http://localhost:8000",
        worker_shared_secret="secret",
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        openai_api_key="",
        openai_model="gpt-5.4-nano",
        openai_base_url="https://api.openai.com/v1",
        openai_max_output_tokens=6000,
        prove_mlx_model_path=None,
        mlx_generate_binary="mlx_lm.generate",
        mlx_max_tokens=4096,
        mlx_timeout_seconds=600.0,
        mlx_temperature=0.0,
        draft_embedding_provider="openai",
        draft_embedding_model="text-embedding-3-small",
        draft_embedding_endpoint_identity=None,
        draft_embedding_deployment_identity=None,
        draft_embedding_revision="sha256:story-test",
        draft_embedding_dimension=384,
        draft_embedding_timeout_seconds=60.0,
        lean_binary="lean",
        lake_binary="lake",
        lean_project_dir=None,
    )


def _worker(
    *,
    api: FakeApi | None = None,
    pipeline: FakePipeline | None = None,
    explainer: FakeExplainer | None = None,
    output_reviewer: FakeOutputReviewer | None = None,
    proof_reviewer: FakeSemanticReviewer | None = None,
) -> SqsProofWorker:
    return SqsProofWorker(
        settings=_settings(),
        api_client=api or FakeApi(),
        pipeline=pipeline or FakePipeline(),
        explainer=explainer or FakeExplainer(),
        output_reviewer=output_reviewer or FakeOutputReviewer(),
        proof_reviewer=proof_reviewer or FakeSemanticReviewer(),
    )


def test_worker_processes_api_job_and_updates_progress() -> None:
    api = FakeApi()
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=FakePipeline(),
        explainer=FakeExplainer(),
        output_reviewer=FakeOutputReviewer(),
        proof_reviewer=FakeSemanticReviewer(),
    )

    assert _process_proof(worker, "job-1") is True

    assert api.events.index("proof_generation_claim") < api.events.index("proof_update:drafting")
    assert all(update["claim_id"] == _TEST_CLAIM_ID for update in api.updates)
    assert [update["state"] for update in api.updates] == [
        "drafting",
        "sketching",
        "proving",
        "compiling",
    ]
    assert all(update["verifier_attestation"] is None for update in api.updates)
    assert api.verification_candidates == [
        {
            "proof_job_id": "job-1",
            "claim_id": _TEST_CLAIM_ID,
            "candidate_id": ANY,
            "lean_code": VERIFIED_LEAN_CODE,
            "result_artifact_uri": VERIFIED_ARTIFACT_URI,
        }
    ]
    assert api.events.count("semantic_review") == 1
    assert [update["state"] for update in api.explanation_updates] == [
        "generating",
        "completed",
    ]
    assert api.explanation_updates[-1]["content"]["overview"].startswith("検証済み")
    assert "prompt" not in api.explanation_updates[-1]["content"]
    assert "raw_model_output" not in api.explanation_updates[-1]["content"]


def test_worker_waits_for_delayed_candidate_and_finishes_on_one_sqs_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient([{"Body": "job-1", "ReceiptHandle": "receipt-1"}])
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    api = DelayedCandidateApi(compiling_reads=2)
    sleeps: list[float] = []
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=FakePipeline(),
        explainer=FakeExplainer(),
        output_reviewer=FakeOutputReviewer(),
        proof_reviewer=FakeSemanticReviewer(),
        sleep=sleeps.append,
    )

    assert worker.run_once() is True

    assert sleeps == [1.0, 1.0]
    assert api.events.count("proof_generation_claim") == 1
    assert api.events.count("verification_candidate") == 1
    assert api.events.count("semantic_review") == 1
    assert [update["state"] for update in api.explanation_updates] == [
        "generating",
        "completed",
    ]
    assert sqs.deleted == [
        {
            "QueueUrl": "http://localstack:4566/000000000000/q",
            "ReceiptHandle": "receipt-1",
        }
    ]


def test_worker_retains_receipt_when_verification_candidate_import_is_unavailable() -> None:
    api = CandidateImportUnavailableApi()
    explainer = FakeExplainer()
    worker = _worker(api=api, explainer=explainer)

    assert _process_proof(worker, "job-1") is False

    assert api.events[-1] == "verification_candidate"
    assert len(api.verification_candidates) == 1
    assert explainer.explain_calls == []
    assert api.explanation_updates == []


def test_worker_run_once_receives_sqs_message_and_deletes_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient(
        [{"Body": "job-1", "ReceiptHandle": "receipt-1"}],
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    api = FakeApi()
    api.state = "semantic_review"
    api.lean_code = VERIFIED_LEAN_CODE
    api.verification_candidate_id = "22222222-2222-4222-8222-222222222222"
    api.generation_session_id = _TEST_CLAIM_ID
    api.status_context = {
        "target_declaration": {
            "kind": "theorem",
            "name": "x2_continuous",
            "proposition": "Continuous (fun y : ℝ => y ^ 2)",
        }
    }
    worker = _worker(api=api)

    assert worker.run_once() is True
    assert sqs.received_queue_url == "http://localstack:4566/000000000000/q"
    assert sqs.receive_kwargs["MessageAttributeNames"] == ["All"]
    assert sqs.receive_kwargs["MessageSystemAttributeNames"] == ["All"]
    assert sqs.receive_kwargs["WaitTimeSeconds"] == 20
    assert sqs.deleted == [
        {
            "QueueUrl": "http://localstack:4566/000000000000/q",
            "ReceiptHandle": "receipt-1",
        }
    ]


def test_worker_run_once_returns_false_without_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient([])
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    worker = _worker()

    assert worker.run_once() is False
    assert sqs.deleted == []


def test_agent_task_parser_supports_legacy_proof_and_structured_clarification() -> None:
    assert parse_agent_task("job-1").kind == "proof"
    assert parse_agent_task("job-1").id == "job-1"
    task = parse_agent_task('{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}')
    assert task.kind == "clarification"
    assert task.id == "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "{not-json",
        "[]",
        '{"kind":"proof","id":"job-1"}',
        ' {"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}',
        '{"id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1","kind":"clarification"}',
        '{"kind":"clarification","id":"8BF36A9A-5D98-4E19-8F70-7F07DFC881A1"}',
    ],
)
def test_agent_task_parser_rejects_malformed_structured_tasks(body: str) -> None:
    with pytest.raises(ValueError):
        parse_agent_task(body)


def test_worker_run_once_does_not_delete_message_after_processing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient(
        [{"Body": "job-1", "ReceiptHandle": "receipt-1"}],
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    worker = _worker(pipeline=ExplodingPipeline())

    with pytest.raises(RuntimeError, match="pipeline failed"):
        worker.run_once()

    assert sqs.deleted == []


def test_worker_run_once_retains_malformed_message_for_sqs_redrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient(
        [{"Body": "{not-json", "ReceiptHandle": "receipt-1"}],
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)

    worker = _worker()

    assert worker.run_once() is True
    assert sqs.deleted == []


def test_worker_processes_structured_clarification_task_and_hides_private_model_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lean_code = "example : True := by\n  trivial"
    summary = _proof_explanation(lean_code)
    api = FakeApi()
    api.state = "verified"
    api.theorem_statement = "True を示せ"
    api.lean_code = lean_code
    api.clarification_input = {
        "proof_job_id": "job-1",
        "state": "queued",
        "output_language": "ja",
        "theorem_statement": "True を示せ",
        "lean_code": lean_code,
        "section_id": "finish-proof",
        "question": "trivial は何をしているの？",
        "summary": {
            "overview": summary.overview,
            "sections": [
                {
                    "id": summary.sections[0].id,
                    "title": summary.sections[0].title,
                    "summary": summary.sections[0].summary,
                    "references": [
                        {
                            "start_line": 2,
                            "end_line": 2,
                            "excerpt": "  trivial",
                        }
                    ],
                }
            ],
            "conclusion": summary.conclusion,
            "model": summary.model,
            "provider": summary.provider,
            "elapsed_ms": summary.elapsed_ms,
        },
    }
    explainer = FakeExplainer()
    sqs = FakeSqsClient(
        [
            {
                "Body": ('{"kind":"clarification","id":"8bf36a9a-5d98-4e19-8f70-7f07dfc881a1"}'),
                "ReceiptHandle": "receipt-1",
            }
        ]
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    worker = _worker(api=api, explainer=explainer)

    assert worker.run_once() is True

    assert [update["state"] for update in api.clarification_updates] == [
        "generating",
        "completed",
    ]
    completed_update = api.clarification_updates[-1]
    completed = completed_update["content"]
    assert completed["question"] == "trivial は何をしているの？"
    assert "prompt" not in completed
    assert "raw_model_output" not in completed
    parent_output = {
        "output_kind": "explanation",
        "proof_job_id": "job-1",
        "content": api.clarification_input["summary"],
    }
    parent_sha256 = hashlib.sha256(rfc8785.dumps(parent_output)).hexdigest()
    clarification_output = {
        "output_kind": "clarification",
        "clarification_id": "8bf36a9a-5d98-4e19-8f70-7f07dfc881a1",
        "proof_job_id": "job-1",
        "content": completed,
        "parent_explanation_sha256": parent_sha256,
    }
    evidence = completed_update["review_evidence"]
    assert evidence["output_kind"] == "clarification"
    assert evidence["output_sha256"] == hashlib.sha256(
        rfc8785.dumps(clarification_output)
    ).hexdigest()
    assert evidence["parent_explanation_sha256"] == parent_sha256
    assert evidence["evidence_sha256"] == hashlib.sha256(
        rfc8785.dumps(
            {key: value for key, value in evidence.items() if key != "evidence_sha256"}
        )
    ).hexdigest()
    assert len(explainer.clarify_calls) == 1
    assert sqs.deleted[0]["ReceiptHandle"] == "receipt-1"


def test_worker_records_clarification_generation_failure_without_placeholder() -> None:
    lean_code = "example : True := by\n  trivial"
    summary = _proof_explanation(lean_code)
    api = FakeApi()
    api.state = "verified"
    api.theorem_statement = "True を示せ"
    api.lean_code = lean_code
    api.clarification_input = {
        "proof_job_id": "job-1",
        "state": "queued",
        "output_language": "ja",
        "theorem_statement": "True を示せ",
        "lean_code": lean_code,
        "section_id": "finish-proof",
        "question": "ここがわからない",
        "summary": {
            "overview": summary.overview,
            "sections": [
                {
                    "id": "finish-proof",
                    "title": "証明を閉じる",
                    "summary": "最後の行です。",
                    "references": [{"start_line": 2, "end_line": 2, "excerpt": "  trivial"}],
                }
            ],
            "conclusion": summary.conclusion,
            "model": summary.model,
            "provider": summary.provider,
            "elapsed_ms": 1,
        },
    }
    worker = _worker(api=api, explainer=FailingExplainer())

    _process_clarification(worker, "clarification-1")

    assert [update["state"] for update in api.clarification_updates] == [
        "generating",
        "failed",
    ]
    failed = api.clarification_updates[-1]
    assert failed["content"] is None
    assert failed["diagnostics"][0].code == "pals.clarification_failed"
    assert failed["diagnostics"][0].message == "追加回答の生成に失敗しました。"


@pytest.mark.parametrize("state", ["completed", "failed", "dispatch_uncertain"])
def test_worker_skips_terminal_clarification_redelivery(state: str) -> None:
    api = FakeApi()
    api.clarification_input = {"state": state}
    explainer = FakeExplainer()
    worker = _worker(api=api, explainer=explainer)

    _process_clarification(worker, "clarification-1")

    assert api.clarification_updates == []
    assert explainer.clarify_calls == []


def test_worker_treats_concurrent_terminal_clarification_as_idempotent() -> None:
    api = TerminalClarificationRaceApi()
    explainer = FakeExplainer()
    worker = _worker(api=api, explainer=explainer)

    _process_clarification(worker, "clarification-1")

    assert api.fetch_count == 1
    assert explainer.clarify_calls == []


def test_worker_deletes_message_after_invalid_openmath_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sqs = FakeSqsClient(
        [{"Body": "job-1", "ReceiptHandle": "receipt-1"}],
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    api = FakeApi()
    generator = CountingGenerator()
    verifier = CountingVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=InvalidOpenMathCatalog(),
    )
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=pipeline,
        explainer=FakeExplainer(),
        output_reviewer=FakeOutputReviewer(),
    )

    assert worker.run_once() is True

    assert generator.calls == []
    assert verifier.calls == []
    assert len(api.updates) == 1
    update = api.updates[0]
    assert update["state"] == "failed"
    assert update["diagnostics"][0].code == "pals.openmath_structuring_failed"
    assert update["context"]["stage"] == "failed"
    assert update["context"]["schema_version"] == "pals.proof-status-context.v1"
    assert update["context"]["termination_reason"] == "non_repairable_failure"
    assert sqs.deleted == [
        {
            "QueueUrl": "http://localstack:4566/000000000000/q",
            "ReceiptHandle": "receipt-1",
        }
    ]


def test_worker_run_once_retains_stale_message_when_api_job_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient(
        [{"Body": "missing-job", "ReceiptHandle": "receipt-1"}],
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    worker = _worker(api=MissingJobApi())

    assert worker.run_once() is True

    assert sqs.deleted == []


def test_worker_retains_receipt_when_api_is_temporarily_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqs = FakeSqsClient(
        [{"Body": "job-1", "ReceiptHandle": "receipt-1"}],
    )
    monkeypatch.setattr("pals_agent.worker.boto3.client", lambda *_args, **_kwargs: sqs)
    worker = _worker(api=UnavailableApi())

    assert worker.run_once() is True

    assert sqs.deleted == []


def test_worker_adds_missing_explanation_to_verified_job_without_rerunning_proof() -> None:
    api = FakeApi()
    api.state = "verified"
    api.lean_code = "example : True := by\n  trivial"
    pipeline = FakePipeline()
    explainer = FakeExplainer()
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=pipeline,
        explainer=explainer,
        output_reviewer=FakeOutputReviewer(),
    )

    _process_proof(worker, "job-1")

    assert api.updates == []
    assert len(explainer.explain_calls) == 1
    assert api.explanation_updates[-1]["state"] == "completed"


def test_worker_skips_terminal_explanation_redelivery_conflict() -> None:
    api = TerminalExplanationApi()
    api.state = "verified"
    api.lean_code = "example : True := by\n  trivial"
    pipeline = FakePipeline()
    explainer = FakeExplainer()
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=pipeline,
        explainer=explainer,
        output_reviewer=FakeOutputReviewer(),
    )

    _process_proof(worker, "job-1")

    assert pipeline.formal_statement is None
    assert explainer.explain_calls == []


def test_worker_does_not_regenerate_completed_summary() -> None:
    api = FakeApi()
    api.state = "verified"
    api.lean_code = "example : True := by\n  trivial"
    api.explanation_existing_state = "completed"
    explainer = FakeExplainer()
    worker = _worker(api=api, explainer=explainer)

    _process_proof(worker, "job-1")

    assert explainer.explain_calls == []
    assert api.explanation_updates == []


def test_worker_records_summary_generation_failure_without_placeholder() -> None:
    api = FakeApi()
    api.state = "verified"
    api.lean_code = "example : True := by\n  trivial"
    worker = _worker(api=api, explainer=FailingExplainer())

    _process_proof(worker, "job-1")

    assert [update["state"] for update in api.explanation_updates] == [
        "generating",
        "failed",
    ]
    failed = api.explanation_updates[-1]
    assert failed["content"] is None
    assert failed["diagnostics"][0].code == "pals.explanation_failed"


def test_worker_passes_formal_statement_context_to_pipeline() -> None:
    api = FakeApi()
    api.context["formal_statement"] = "example : Continuous fun x : ℝ => x ^ 2 := by"
    pipeline = FakePipeline()
    worker = SqsProofWorker(
        settings=_settings(),
        api_client=api,
        pipeline=pipeline,
        explainer=FakeExplainer(),
        output_reviewer=FakeOutputReviewer(),
    )

    _process_proof(worker, "job-1")

    assert pipeline.formal_statement == "example : Continuous fun x : ℝ => x ^ 2 := by"
