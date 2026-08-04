from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol, cast

import boto3  # type: ignore[import-untyped]

from pals_agent.api_client import (
    PalsApiError,
    ProofJobNotFoundError,
)
from pals_agent.artifacts import ArtifactPersistenceError
from pals_agent.explanations import (
    ExplanationDeadlineExceeded,
    ProofClarification,
    ProofExplanation,
    proof_explanation_from_api,
)
from pals_agent.model_roles import ModelRole, fixed_model_default
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    ProofJobState,
    VerificationResult,
)
from pals_agent.openmath import OpenMathStructuringError
from pals_agent.pipeline import ApiRepairSeed
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError
from pals_agent.settings import AgentSettings

ClaimStatus = Literal[
    "acquired",
    "busy",
    "terminal",
    "lease_too_short",
    "not_ready",
]
ResourceKind = Literal["proof_job", "explanation", "clarification"]
VisibilityExtender = Callable[[int], None]

_NON_VERIFIED_TERMINAL_STATES: Final = frozenset({"failed", "canceled"})
_CLAIM_STATUSES: Final = frozenset(
    {"acquired", "busy", "terminal", "lease_too_short", "not_ready"}
)
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$", re.ASCII)
_MANUAL_FIXTURE_URI_RE = re.compile(
    r"^s3://[A-Za-z0-9][A-Za-z0-9.-]{0,254}/manual-fixtures/([0-9a-f]{64})\.lean$",
    re.ASCII,
)
_MODEL_ARTIFACT_URI_RE = re.compile(
    r"^s3://[A-Za-z0-9][A-Za-z0-9.-]{0,254}/proof-jobs/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}/result\.lean$",
    re.ASCII,
)
_OPENMATH_ROLE_MODEL = fixed_model_default(ModelRole.OPENMATH)
_TERMINAL_MARGIN_SECONDS: Final = 30.0
_MAX_MODEL_ATTEMPTS: Final = 3
_STATUS_CONTEXT_SCHEMA: Final = "pals.proof-status-context.v1"
_CLARIFICATION_DISPATCH_SCHEMA_VERSION: Final = (
    "pals.proof-clarification-dispatch.v1"
)
_SENSITIVE_STATUS_MESSAGES: Final = {
    "openai.error": "Proof generation failed.",
    "ollama.error": "Proof generation failed.",
    "llm.generation_failed": "Proof generation failed.",
    "pals.repair_generator_unavailable": "Proof generation failed.",
    "llm.empty": "Proof generation returned no usable Lean code.",
    "pals.generation_empty": "Proof generation returned no usable Lean code.",
    "pals.repair_route_invalid_response": "Repair route selection failed.",
    "pals.repair_route_transport_error": "Repair route selection failed.",
    "pals.repair_route_selection_failed": "Repair route selection failed.",
    "pals.openmath_structuring_failed": (
        "The theorem statement could not be structured."
    ),
    "pals.artifact_checkpoint_failed": "Proof artifact persistence failed.",
    "pals.artifact_persistence_failed": "Proof artifact persistence failed.",
}


class ProofJobApi(Protocol):
    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]: ...

    def acquire_proof_generation_claim(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        required_lease_ms: int = 3_600_000,
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

    def submit_verification_candidate(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        candidate_id: str,
        lean_code: str,
        result_artifact_uri: str,
    ) -> dict[str, Any]: ...

    def upsert_proof_explanation(
        self,
        *,
        proof_job_id: str,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]: ...

    def get_proof_clarification(self, clarification_id: str) -> dict[str, Any]: ...

    def update_proof_clarification(
        self,
        *,
        clarification_id: str,
        state: str,
        claim_id: str,
        required_lease_ms: int | None = None,
        content: dict[str, Any] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> dict[str, Any]: ...


class StatementPipeline(Protocol):
    def run_statement(
        self,
        *,
        statement: str,
        formal_statement: str | None = None,
        proof_job_id: str,
        on_status: Any,
        api_repair_seed: ApiRepairSeed | None = None,
    ) -> Any: ...


class ProofExplainer(Protocol):
    def explain(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        verified: bool,
        language: str = "ja",
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofExplanation: ...

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
    ) -> ProofClarification: ...


@dataclass(frozen=True, slots=True)
class AgentTask:
    kind: str
    id: str


@dataclass(frozen=True, slots=True)
class _ClaimEnvelope:
    status: ClaimStatus
    lease_remaining_ms: int | None


@dataclass(frozen=True, slots=True)
class _GenerationPermit:
    deadline: float
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class _AcquisitionResult:
    acknowledge: bool
    permit: _GenerationPermit | None
    acquired: bool = False


@dataclass(frozen=True, slots=True)
class SqsProofWorker:
    settings: AgentSettings
    api_client: ProofJobApi
    # A clarification only reads an already-verified proof and calls the
    # explainer.  Constructing the proof-generation pipeline here used to make
    # that independent path unavailable whenever the optional Proof Flow
    # runtime was not configured locally.
    pipeline: StatementPipeline | None
    explainer: ProofExplainer
    pipeline_factory: Callable[[], StatementPipeline] | None = None
    monotonic: Callable[[], float] = time.monotonic
    uuid4_factory: Callable[[], uuid.UUID] = uuid.uuid4

    def run_forever(self) -> None:
        while True:
            processed = self.run_once()
            if not processed:
                time.sleep(self.settings.worker_idle_sleep_seconds)

    def run_once(self) -> bool:
        if not self.settings.proof_jobs_queue_url:
            raise RuntimeError("PALS_PROOF_JOBS_QUEUE_URL is required for the worker.")

        sqs = boto3.client(
            "sqs",
            endpoint_url=self.settings.aws_endpoint_url,
            region_name=self.settings.aws_region,
        )
        response = sqs.receive_message(
            QueueUrl=self.settings.proof_jobs_queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=1,
            MessageAttributeNames=["All"],
            MessageSystemAttributeNames=["All"],
        )
        messages = response.get("Messages", []) if isinstance(response, dict) else []
        if not isinstance(messages, list):
            return False
        if not messages:
            return False

        message = messages[0]
        try:
            task, receipt_handle = parse_sqs_agent_message(message)
        except (TypeError, ValueError):
            # Leave poison input for SQS redrive; never delete an unvalidated receipt.
            return True
        claim_id = self._fresh_claim_id()

        def extend_visibility(seconds: int) -> None:
            sqs.change_message_visibility(
                QueueUrl=self.settings.proof_jobs_queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=seconds,
            )

        acknowledged = False
        try:
            if task.kind == "proof":
                acknowledged = self.process_proof_job(
                    task.id,
                    claim_id=claim_id,
                    extend_visibility=extend_visibility,
                )
            elif task.kind == "clarification":
                acknowledged = self.process_clarification(
                    task.id,
                    claim_id=claim_id,
                    extend_visibility=extend_visibility,
                )
            else:
                raise ValueError(f"Unsupported agent task kind: {task.kind}")
        except (ProofJobNotFoundError, PalsApiError):
            # API failures leave the receipt for redelivery.  They are operationally retryable
            # from the worker's point of view and must not terminate the polling process.
            acknowledged = False

        if acknowledged:
            sqs.delete_message(
                QueueUrl=self.settings.proof_jobs_queue_url,
                ReceiptHandle=receipt_handle,
            )
        return True

    def process_proof_job(
        self,
        proof_job_id: str,
        *,
        claim_id: str | None = None,
        extend_visibility: VisibilityExtender | None = None,
    ) -> bool:
        proof_job = self.api_client.get_proof_job(proof_job_id)
        state = proof_job.get("state")
        if state in _NON_VERIFIED_TERMINAL_STATES:
            return True
        statement = _required_text(proof_job, "theorem_statement")
        if state == "verified":
            lean_code = proof_job.get("lean_code")
            if not isinstance(lean_code, str) or not lean_code.strip():
                return False
            if claim_id is None or extend_visibility is None:
                return False
            return self._ensure_summary_explanation(
                proof_job_id=proof_job_id,
                theorem_statement=statement,
                lean_code=lean_code,
                claim_id=claim_id,
                extend_visibility=extend_visibility,
            )

        if _has_pending_api_candidate(proof_job):
            # Candidate import is durable, but reconciliation owns the next state transition.
            # Retain the receipt rather than reacquiring the proof and starting a parallel run.
            return False

        context = proof_job.get("request_context")
        context = context if isinstance(context, dict) else {}
        formal_statement = context.get("formal_statement")
        if not isinstance(formal_statement, str) or not formal_statement.strip():
            formal_statement = None
        api_repair_seed = _api_repair_seed_from_worker_input(proof_job)
        if _has_api_compile_failure(proof_job) and api_repair_seed is None:
            # The API is the compiler authority.  Do not discard or recreate a candidate when
            # its durable repair seed is incomplete; retain the receipt for a later readback.
            # In particular, do not take a new claim that would delay that retry.
            return False

        if claim_id is None or extend_visibility is None:
            return False
        generation = self._acquire_proof_generation(
            proof_job_id=proof_job_id,
            claim_id=claim_id,
            extend_visibility=extend_visibility,
        )
        if not generation.acquired:
            return generation.acknowledge

        latest_state: ProofJobState | None = None
        latest_lean_code: str | None = None
        candidate_submitted = False

        def on_status(
            status: ProofJobState,
            diagnostics: list[Diagnostic],
            result_artifact_uri: str | None,
            lean_code: str | None,
            status_context: dict[str, Any],
        ) -> None:
            nonlocal candidate_submitted, latest_state, latest_lean_code
            if lean_code:
                latest_lean_code = lean_code
            if status == "verified":
                raise RuntimeError("worker pipeline must not publish direct verifier success")
            latest_state = status
            api_diagnostics = _status_diagnostics(diagnostics)
            api_context = _proof_status_context(
                state=status,
                raw=status_context,
                diagnostics=api_diagnostics,
                max_repair_attempts=getattr(self.settings, "max_repair_attempts", 12),
            )
            self.api_client.update_proof_job(
                proof_job_id=proof_job_id,
                claim_id=claim_id,
                state=status,
                diagnostics=api_diagnostics,
                result_artifact_uri=result_artifact_uri,
                lean_code=lean_code,
                context=api_context,
            )

        try:
            run_kwargs: dict[str, Any] = {
                "statement": statement,
                "formal_statement": formal_statement,
                "proof_job_id": proof_job_id,
                "on_status": on_status,
            }
            if api_repair_seed is not None:
                run_kwargs["api_repair_seed"] = api_repair_seed
            run_result = self._pipeline_for_proof().run_statement(**run_kwargs)
        except OpenMathStructuringError:
            on_status(
                "failed",
                [
                    _fixed_diagnostic(
                        "pals.openmath_structuring_failed",
                        "The theorem statement could not be structured.",
                    )
                ],
                None,
                None,
                {
                    "stage": "openmath_structuring",
                    "openmath_provider": _OPENMATH_ROLE_MODEL.provider,
                    "openmath_model": _OPENMATH_ROLE_MODEL.model,
                },
            )
            return True
        except ProofFlowRetrievalError as exc:
            on_status(
                "failed",
                [
                    _fixed_diagnostic(
                        "pals.proof_flow_retrieval_failed",
                        "Proof Flow retrieval could not provide reusable context.",
                    )
                ],
                None,
                None,
                {"stage": "proof_flow_retrieval", "proof_flow_error": exc.code},
            )
            return True
        except ArtifactPersistenceError:
            on_status(
                "failed",
                [
                    _fixed_diagnostic(
                        "pals.artifact_persistence_failed",
                        "The proof result could not be durably persisted.",
                    )
                ],
                None,
                None,
                {"stage": "artifact_persistence"},
            )
            return True

        if getattr(run_result, "verification_pending", False):
            if not isinstance(latest_lean_code, str) or not latest_lean_code.strip():
                return False
            if not _verified_candidate_matches_statement(statement, latest_lean_code):
                on_status(
                    "failed",
                    [
                        _fixed_diagnostic(
                            "pals.theorem_alignment_failed",
                            "The generated Lean theorem did not match the requested theorem.",
                        )
                    ],
                    None,
                    None,
                    {"stage": "theorem_alignment"},
                )
                return True
            try:
                candidate_artifact_uri = _candidate_artifact_uri(
                    proof_job,
                    run_result=run_result,
                    lean_code=latest_lean_code,
                )
                self.api_client.submit_verification_candidate(
                    proof_job_id=proof_job_id,
                    claim_id=claim_id,
                    candidate_id=str(uuid.uuid4()),
                    lean_code=latest_lean_code,
                    result_artifact_uri=candidate_artifact_uri,
                )
            except (PalsApiError, ValueError):
                # Keep the queue receipt unacknowledged.  A failed candidate import is not
                # proof verification success and must never crash the worker process.
                return False
            candidate_submitted = True

        if latest_state in _NON_VERIFIED_TERMINAL_STATES:
            return True
        if candidate_submitted:
            # The candidate route's 200 only proves durable import.  It is not verifier success;
            # a read-back must observe the API-owned reconciled result before explanation work can
            # begin.  A still-compiling result remains unacknowledged for a later queue delivery.
            try:
                reconciled = self.api_client.get_proof_job(proof_job_id)
            except PalsApiError:
                # The candidate may have been durably imported even though its result cannot
                # yet be observed.  Retain the receipt and let a later delivery read it back.
                return False
            if reconciled.get("state") != "verified":
                return False
            reconciled_lean_code = reconciled.get("lean_code")
            if not isinstance(reconciled_lean_code, str) or not reconciled_lean_code.strip():
                return False
            return self._ensure_summary_explanation(
                proof_job_id=proof_job_id,
                theorem_statement=statement,
                lean_code=reconciled_lean_code,
                claim_id=claim_id,
                extend_visibility=extend_visibility,
            )
        if latest_state != "verified" or not latest_lean_code:
            return False
        return self._ensure_summary_explanation(
            proof_job_id=proof_job_id,
            theorem_statement=statement,
            lean_code=latest_lean_code,
            claim_id=claim_id,
            extend_visibility=extend_visibility,
        )

    def _pipeline_for_proof(self) -> StatementPipeline:
        """Build the proof pipeline only for a proof-generation task.

        Explanation and clarification tasks are deliberately independent from
        Proof Flow retrieval: they operate on Lean code which the API has
        already marked verified.  Keep proof generation fail-closed by still
        raising if its pipeline cannot be constructed.
        """
        if self.pipeline is not None:
            return self.pipeline
        if self.pipeline_factory is None:
            raise RuntimeError("proof-generation pipeline is unavailable")
        try:
            pipeline = self.pipeline_factory()
        except ValueError as exc:
            # Invalid local Proof Flow configuration must fail this proof job
            # closed, but it must not terminate the process that can still
            # explain already-verified proofs and clarifications.
            raise ProofFlowRetrievalError("retrieval_unavailable") from exc
        object.__setattr__(self, "pipeline", pipeline)
        return pipeline

    def process_clarification(
        self,
        clarification_id: str,
        *,
        claim_id: str | None = None,
        extend_visibility: VisibilityExtender | None = None,
    ) -> bool:
        worker_input = self.api_client.get_proof_clarification(clarification_id)
        if (
            not isinstance(worker_input, dict)
            or worker_input.get("dispatch_schema_version")
            != _CLARIFICATION_DISPATCH_SCHEMA_VERSION
        ):
            return False
        if worker_input.get("state") in {"completed", "failed", "dispatch_uncertain"}:
            return True
        if claim_id is None or extend_visibility is None:
            return False

        try:
            if _required_text(worker_input, "id") != clarification_id:
                return False
            proof_job_id = _required_text(worker_input, "proof_job_id")
            theorem_statement = _required_text(worker_input, "theorem_statement")
            lean_code = _required_text(worker_input, "lean_code")
            after_clarification_id = worker_input.get("after_clarification_id")
            if after_clarification_id is not None and (
                not isinstance(after_clarification_id, str)
                or not after_clarification_id
            ):
                return False
            proof_input = self.api_client.get_proof_job(proof_job_id)
            if not _same_verified_proof(
                proof_input,
                proof_job_id=proof_job_id,
                theorem_statement=theorem_statement,
                lean_code=lean_code,
            ):
                return False
        except Exception:
            return False

        acquisition = self._acquire(
            resource_kind="clarification",
            resource_id=clarification_id,
            claim_id=claim_id,
            extend_visibility=extend_visibility,
            request=lambda required_lease_ms: self.api_client.update_proof_clarification(
                clarification_id=clarification_id,
                state="generating",
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
            ),
        )
        if acquisition.permit is None:
            return acquisition.acknowledge

        permit = acquisition.permit
        try:
            summary_payload = _required_mapping(worker_input, "summary")
            explanation = proof_explanation_from_api(
                summary_payload,
                lean_code=lean_code,
            )
            clarification_kwargs: dict[str, Any] = {
                "theorem_statement": theorem_statement,
                "lean_code": lean_code,
                "verified": True,
                "explanation": explanation,
                "section_id": _required_text(worker_input, "section_id"),
                "question": _required_text(worker_input, "question"),
                "deadline": permit.deadline,
                "timeout_seconds": permit.timeout_seconds,
            }
            selected_text = worker_input.get("selected_text")
            if isinstance(selected_text, str) and selected_text:
                clarification_kwargs["selected_text"] = selected_text
            if after_clarification_id is not None:
                clarification_kwargs["after_clarification_id"] = after_clarification_id
            clarification = self.explainer.clarify(**clarification_kwargs)
            content = _public_clarification_content(clarification)
            self._raise_if_generation_deadline_reached(permit.deadline)
        except ExplanationDeadlineExceeded:
            return self._write_clarification_failure(
                clarification_id=clarification_id,
                claim_id=claim_id,
                code="pals.clarification_deadline_exceeded",
                message="Clarification generation exceeded its deadline.",
            )
        except Exception:
            return self._write_clarification_failure(
                clarification_id=clarification_id,
                claim_id=claim_id,
                code="pals.clarification_failed",
                message="Clarification generation failed.",
            )

        try:
            response = self.api_client.update_proof_clarification(
                clarification_id=clarification_id,
                state="completed",
                claim_id=claim_id,
                content=content,
            )
        except PalsApiError as exc:
            if exc.error_code == "proof_clarification_reference_mismatch":
                return self._write_clarification_failure(
                    clarification_id=clarification_id,
                    claim_id=claim_id,
                    code="pals.clarification_reference_mismatch",
                    message="Clarification references no longer match the verified proof.",
                    require_failed_terminal=True,
                )
            return False
        except Exception:
            return False
        return _terminal_response_persisted(
            response,
            resource_kind="clarification",
            resource_id=clarification_id,
        )

    def _ensure_summary_explanation(
        self,
        *,
        proof_job_id: str,
        theorem_statement: str,
        lean_code: str,
        claim_id: str,
        extend_visibility: VisibilityExtender,
    ) -> bool:
        acquisition = self._acquire(
            resource_kind="explanation",
            resource_id=proof_job_id,
            claim_id=claim_id,
            extend_visibility=extend_visibility,
            request=lambda required_lease_ms: self.api_client.upsert_proof_explanation(
                proof_job_id=proof_job_id,
                state="generating",
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
            ),
        )
        if acquisition.permit is None:
            return acquisition.acknowledge

        permit = acquisition.permit
        try:
            explanation = self.explainer.explain(
                theorem_statement=theorem_statement,
                lean_code=lean_code,
                verified=True,
                deadline=permit.deadline,
                timeout_seconds=permit.timeout_seconds,
            )
            content = _public_explanation_content(explanation)
            self._raise_if_generation_deadline_reached(permit.deadline)
        except ExplanationDeadlineExceeded:
            return self._write_explanation_failure(
                proof_job_id=proof_job_id,
                claim_id=claim_id,
                code="pals.explanation_deadline_exceeded",
                message="Explanation generation exceeded its deadline.",
            )
        except Exception:
            return self._write_explanation_failure(
                proof_job_id=proof_job_id,
                claim_id=claim_id,
                code="pals.explanation_failed",
                message="Explanation generation failed.",
            )

        try:
            response = self.api_client.upsert_proof_explanation(
                proof_job_id=proof_job_id,
                state="completed",
                claim_id=claim_id,
                content=content,
            )
        except PalsApiError as exc:
            if exc.error_code == "proof_explanation_reference_mismatch":
                return self._write_explanation_failure(
                    proof_job_id=proof_job_id,
                    claim_id=claim_id,
                    code="pals.explanation_reference_mismatch",
                    message="Explanation references no longer match the verified proof.",
                    require_failed_terminal=True,
                )
            return False
        except Exception:
            return False
        return _terminal_response_persisted(
            response,
            resource_kind="explanation",
            resource_id=proof_job_id,
        )

    def _acquire(
        self,
        *,
        resource_kind: ResourceKind,
        resource_id: str,
        claim_id: str,
        extend_visibility: VisibilityExtender,
        request: Callable[[int], dict[str, Any]],
    ) -> _AcquisitionResult:
        timeout_seconds = self.settings.explanation_model_timeout_seconds
        required_lease_ms = (
            _MAX_MODEL_ATTEMPTS * timeout_seconds + int(_TERMINAL_MARGIN_SECONDS)
        ) * 1000
        claim_request_started_at = self.monotonic()
        try:
            raw_response = request(required_lease_ms)
            envelope = _parse_claim_envelope(
                raw_response,
                resource_kind=resource_kind,
                resource_id=resource_id,
            )
        except Exception:
            return _AcquisitionResult(acknowledge=False, permit=None)

        if envelope.status == "terminal":
            return _AcquisitionResult(acknowledge=True, permit=None)
        if envelope.status != "acquired" or envelope.lease_remaining_ms is None:
            return _AcquisitionResult(acknowledge=False, permit=None)

        lease_deadline = (
            claim_request_started_at + envelope.lease_remaining_ms / 1000.0
        )
        visibility_seconds = math.ceil(required_lease_ms / 1000) + 30
        try:
            extend_visibility(visibility_seconds)
        except Exception:
            return _AcquisitionResult(acknowledge=False, permit=None)

        generation_started_at = self.monotonic()
        generation_span = _MAX_MODEL_ATTEMPTS * timeout_seconds
        margin = lease_deadline - (generation_started_at + generation_span)
        if margin < _TERMINAL_MARGIN_SECONDS:
            return _AcquisitionResult(acknowledge=False, permit=None)
        return _AcquisitionResult(
            acknowledge=False,
            permit=_GenerationPermit(
                deadline=generation_started_at + generation_span,
                timeout_seconds=timeout_seconds,
            ),
            acquired=True,
        )

    def _acquire_proof_generation(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        extend_visibility: VisibilityExtender,
    ) -> _AcquisitionResult:
        required_lease_ms = 3_600_000
        request_started_at = self.monotonic()
        try:
            raw_response = self.api_client.acquire_proof_generation_claim(
                proof_job_id=proof_job_id,
                claim_id=claim_id,
                required_lease_ms=required_lease_ms,
            )
            envelope = _parse_claim_envelope(
                raw_response,
                resource_kind="proof_job",
                resource_id=proof_job_id,
            )
        except Exception:
            return _AcquisitionResult(acknowledge=False, permit=None)

        if envelope.status == "terminal":
            return _AcquisitionResult(acknowledge=True, permit=None)
        if envelope.status != "acquired" or envelope.lease_remaining_ms is None:
            return _AcquisitionResult(acknowledge=False, permit=None)

        try:
            extend_visibility(math.ceil(envelope.lease_remaining_ms / 1000) + 30)
        except Exception:
            return _AcquisitionResult(acknowledge=False, permit=None)

        elapsed_ms = int((self.monotonic() - request_started_at) * 1000)
        if envelope.lease_remaining_ms - elapsed_ms < int(_TERMINAL_MARGIN_SECONDS * 1000):
            return _AcquisitionResult(acknowledge=False, permit=None)
        return _AcquisitionResult(
            acknowledge=False,
            permit=None,
            acquired=True,
        )

    def _write_explanation_failure(
        self,
        *,
        proof_job_id: str,
        claim_id: str,
        code: str,
        message: str,
        require_failed_terminal: bool = False,
    ) -> bool:
        try:
            response = self.api_client.upsert_proof_explanation(
                proof_job_id=proof_job_id,
                state="failed",
                claim_id=claim_id,
                diagnostics=[_fixed_diagnostic(code, message)],
            )
        except Exception:
            return False
        if require_failed_terminal:
            return _failed_terminal_response_persisted(
                response,
                resource_kind="explanation",
                resource_id=proof_job_id,
            )
        return _terminal_response_persisted(
            response,
            resource_kind="explanation",
            resource_id=proof_job_id,
        )

    def _write_clarification_failure(
        self,
        *,
        clarification_id: str,
        claim_id: str,
        code: str,
        message: str,
        require_failed_terminal: bool = False,
    ) -> bool:
        try:
            response = self.api_client.update_proof_clarification(
                clarification_id=clarification_id,
                state="failed",
                claim_id=claim_id,
                diagnostics=[_fixed_diagnostic(code, message)],
            )
        except Exception:
            return False
        if require_failed_terminal:
            return _failed_terminal_response_persisted(
                response,
                resource_kind="clarification",
                resource_id=clarification_id,
            )
        return _terminal_response_persisted(
            response,
            resource_kind="clarification",
            resource_id=clarification_id,
        )

    def _raise_if_generation_deadline_reached(self, deadline: float) -> None:
        if self.monotonic() >= deadline:
            raise ExplanationDeadlineExceeded(
                "explanation generation deadline exceeded"
            )

    def _fresh_claim_id(self) -> str:
        value = self.uuid4_factory()
        if not isinstance(value, uuid.UUID) or value.version != 4:
            raise RuntimeError("Worker claim factory must return a UUIDv4 value")
        return str(value)


def _parse_claim_envelope(
    payload: Any,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
) -> _ClaimEnvelope:
    if not isinstance(payload, dict):
        raise ValueError("claim response must be an object")
    if set(payload) != {"claim_status", "lease_remaining_ms", "resource"}:
        raise ValueError("claim response fields do not match the API contract")
    raw_status = payload["claim_status"]
    if not isinstance(raw_status, str) or raw_status not in _CLAIM_STATUSES:
        raise ValueError("claim response status is invalid")
    if raw_status == "not_ready" and resource_kind != "clarification":
        raise ValueError("not_ready is valid only for clarification claims")
    status = cast(ClaimStatus, raw_status)
    lease = payload["lease_remaining_ms"]
    resource = payload["resource"]
    if status in {"acquired", "busy"}:
        if type(lease) is not int or lease < 0:
            raise ValueError("active claim response is malformed")
    elif status in {"terminal", "not_ready", "lease_too_short"} and lease is not None:
        raise ValueError("non-lease claim response is malformed")
    if resource is None:
        if status != "lease_too_short" or resource_kind != "explanation":
            raise ValueError("claim response resource is missing")
    else:
        _validate_claim_resource(
            resource,
            resource_kind=resource_kind,
            resource_id=resource_id,
            status=status,
        )
    return _ClaimEnvelope(status=status, lease_remaining_ms=lease)


def _terminal_response_persisted(
    payload: Any,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
) -> bool:
    try:
        envelope = _parse_claim_envelope(
            payload,
            resource_kind=resource_kind,
            resource_id=resource_id,
        )
    except (TypeError, ValueError):
        return False
    return envelope.status == "terminal"


def _failed_terminal_response_persisted(
    payload: Any,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
) -> bool:
    try:
        envelope = _parse_claim_envelope(
            payload,
            resource_kind=resource_kind,
            resource_id=resource_id,
        )
    except (TypeError, ValueError):
        return False
    if envelope.status != "terminal" or not isinstance(payload, dict):
        return False
    resource = payload.get("resource")
    return isinstance(resource, dict) and resource.get("state") == "failed"


def parse_agent_task(body: str) -> AgentTask:
    stripped = body.strip()
    if not stripped:
        raise ValueError("SQS agent task body must not be empty")
    if not stripped.startswith("{"):
        if not _RESOURCE_ID_RE.fullmatch(stripped):
            raise ValueError("Legacy SQS proof task id contains unsupported characters")
        return AgentTask(kind="proof", id=stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("SQS agent task contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("SQS agent task JSON must be an object")
    kind = payload.get("kind")
    task_id = payload.get("id")
    if (
        kind != "clarification"
        or not isinstance(task_id, str)
        or not _is_canonical_uuid4(task_id)
    ):
        raise ValueError("SQS agent task JSON must contain a clarification kind and id")
    expected_body = f'{{"kind":"clarification","id":"{task_id}"}}'
    if body != expected_body:
        raise ValueError("SQS clarification task body must use the exact PRX-009 bytes")
    return AgentTask(kind=kind, id=task_id)


def parse_sqs_agent_message(message: Any) -> tuple[AgentTask, str]:
    """Validate the common SQS envelope before selecting a proof or clarification task."""
    if not isinstance(message, dict):
        raise ValueError("SQS message must be an object")
    body = message.get("Body")
    message_id = message.get("MessageId")
    receipt_handle = message.get("ReceiptHandle")
    if not isinstance(body, str):
        raise ValueError("SQS message body must be text")
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("SQS message id must be nonblank")
    if not isinstance(receipt_handle, str) or not receipt_handle.strip():
        raise ValueError("SQS receipt handle must be nonblank")

    raw_attributes = message.get("MessageAttributes", {})
    if not isinstance(raw_attributes, dict):
        raise ValueError("SQS application attributes must be an object when present")
    raw_system_attributes = message.get("Attributes")
    if raw_system_attributes is not None and not isinstance(raw_system_attributes, dict):
        raise ValueError("SQS system attributes must be an object when present")

    task = parse_agent_task(body)
    if task.kind == "clarification" and raw_attributes:
        raise ValueError("clarification SQS messages must have no application attributes")
    if task.kind == "proof" and not raw_attributes:
        raise ValueError("proof SQS messages require application attributes")
    return task, receipt_handle


def _is_canonical_uuid4(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _validate_claim_resource(
    resource: Any,
    *,
    resource_kind: ResourceKind,
    resource_id: str,
    status: ClaimStatus,
) -> None:
    if not isinstance(resource, dict):
        raise ValueError("claim response resource must be an object")
    expected_state = _claim_expected_states(resource_kind, status)
    if resource_kind == "proof_job":
        _validate_proof_job_claim_resource(
            resource,
            resource_id=resource_id,
            status=status,
            expected_state=expected_state,
        )
        return
    if resource_kind == "explanation":
        expected_keys = {
            "proof_job_id",
            "state",
            "content",
            "created_at",
            "updated_at",
            "diagnostics",
        }
        if set(resource) != expected_keys or resource.get("proof_job_id") != resource_id:
            raise ValueError("explanation claim resource identity/fields are invalid")
    else:
        expected_keys = {
            "id",
            "proof_job_id",
            "section_id",
            "question",
            "state",
            "content",
            "created_at",
            "updated_at",
            "diagnostics",
        }
        if set(resource) != expected_keys or resource.get("id") != resource_id:
            raise ValueError("clarification claim resource identity/fields are invalid")
        _bounded_text(resource.get("proof_job_id"), maximum=200)
        section_id = _bounded_text(resource.get("section_id"), maximum=200)
        question = _bounded_text(resource.get("question"), maximum=20_000)
        if section_id != section_id.strip():
            raise ValueError("clarification section id is not canonical")

    state = resource.get("state")
    if not isinstance(state, str) or state not in expected_state:
        raise ValueError("claim response resource state does not match status")
    _aware_timestamp(resource.get("created_at"))
    _aware_timestamp(resource.get("updated_at"))
    _validate_worker_diagnostics(resource.get("diagnostics"))
    content = resource.get("content")
    if state == "completed":
        if resource_kind == "explanation":
            _validate_explanation_content(content)
        else:
            _validate_clarification_content(
                content,
                section_id=section_id,
                question=question,
            )
    elif content is not None:
        raise ValueError("claim response content does not match resource state")


def _claim_expected_states(
    resource_kind: ResourceKind,
    status: ClaimStatus,
) -> set[str]:
    if resource_kind == "proof_job":
        if status in {"acquired", "busy"}:
            return {
                "queued",
                "retrieving_context",
                "drafting",
                "sketching",
                "proving",
                "compiling",
                "repairing",
            }
        if status == "terminal":
            return {"verified", "failed", "canceled"}
        raise ValueError("claim status is invalid for proof generation")
    if status == "acquired" or status == "busy":
        return {"generating"}
    if status == "terminal":
        return {"completed", "failed"}
    if status == "not_ready":
        return {"queued"}
    if status == "lease_too_short":
        return {"generating"} if resource_kind == "explanation" else {"queued", "generating"}
    raise ValueError("claim status is invalid")


def _validate_proof_job_claim_resource(
    resource: dict[str, Any],
    *,
    resource_id: str,
    status: ClaimStatus,
    expected_state: set[str],
) -> None:
    expected_keys = {
        "id",
        "job_id",
        "project_id",
        "theorem_statement",
        "formal_statement",
        "state",
        "request_context",
        "status_context",
        "diagnostics",
        "result_artifact_uri",
        "lean_code",
        "verifier_attestation",
    }
    if set(resource) != expected_keys:
        raise ValueError("proof generation claim resource fields are invalid")
    if resource.get("id") != resource_id or resource.get("job_id") != resource_id:
        raise ValueError("proof generation claim resource identity is invalid")
    project_id = resource.get("project_id")
    if project_id is not None:
        _bounded_text(project_id, maximum=200)
    _bounded_text(resource.get("theorem_statement"), maximum=20_000)
    formal_statement = resource.get("formal_statement")
    if formal_statement is not None:
        _bounded_text(formal_statement, maximum=20_000)
    state = resource.get("state")
    if not isinstance(state, str) or state not in expected_state:
        raise ValueError("proof generation claim resource state is invalid")
    request_context = resource.get("request_context")
    if not isinstance(request_context, dict):
        raise ValueError("proof generation request context is invalid")
    status_context = resource.get("status_context")
    if status_context is not None and not isinstance(status_context, dict):
        raise ValueError("proof generation status context is invalid")
    _validate_worker_diagnostics(resource.get("diagnostics"))
    artifact_uri = resource.get("result_artifact_uri")
    if artifact_uri is not None:
        _bounded_text(artifact_uri, maximum=2_048)
    lean_code = resource.get("lean_code")
    if lean_code is not None:
        _bounded_text(lean_code, maximum=200_000)
    attestation = resource.get("verifier_attestation")
    if state == "verified":
        if not isinstance(lean_code, str) or not isinstance(artifact_uri, str):
            raise ValueError("verified proof resource lacks evidence")
        if not isinstance(attestation, dict) or set(attestation) != {
            "schema_version",
            "proof_job_id",
            "lean_sha256",
            "result_artifact_uri",
            "verification_succeeded",
        }:
            raise ValueError("verified proof resource attestation is invalid")
        if (
            attestation.get("schema_version") != "pals.verifier-attestation.v1"
            or attestation.get("proof_job_id") != resource_id
            or attestation.get("lean_sha256")
            != hashlib.sha256(lean_code.encode("utf-8")).hexdigest()
            or attestation.get("result_artifact_uri") != artifact_uri
            or attestation.get("verification_succeeded") is not True
        ):
            raise ValueError("verified proof resource attestation does not match evidence")
    elif attestation is not None:
        raise ValueError("nonverified proof resource cannot include attestation")


def _validate_explanation_content(content: Any) -> None:
    if not isinstance(content, dict) or set(content) != {
        "overview",
        "sections",
        "conclusion",
        "model",
        "provider",
        "elapsed_ms",
    }:
        raise ValueError("explanation content fields are invalid")
    _bounded_text(content.get("overview"), maximum=100_000)
    _bounded_text(content.get("conclusion"), maximum=100_000)
    _bounded_text(content.get("model"), maximum=200)
    _bounded_text(content.get("provider"), maximum=200)
    _nonnegative_int(content.get("elapsed_ms"))
    sections = content.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 500:
        raise ValueError("explanation sections are invalid")
    seen: set[str] = set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {
            "id",
            "title",
            "summary",
            "references",
        }:
            raise ValueError("explanation section fields are invalid")
        section_id = _bounded_text(section.get("id"), maximum=200)
        if section_id != section_id.strip() or section_id in seen:
            raise ValueError("explanation section id is invalid")
        seen.add(section_id)
        _bounded_text(section.get("title"), maximum=2_000)
        _bounded_text(section.get("summary"), maximum=100_000)
        _validate_references(section.get("references"))


def _validate_clarification_content(
    content: Any,
    *,
    section_id: str,
    question: str,
) -> None:
    if not isinstance(content, dict) or set(content) != {
        "section_id",
        "question",
        "answer",
        "key_points",
        "references",
        "model",
        "provider",
        "elapsed_ms",
    }:
        raise ValueError("clarification content fields are invalid")
    if content.get("section_id") != section_id or content.get("question") != question:
        raise ValueError("clarification content identity is invalid")
    _bounded_text(content.get("answer"), maximum=100_000)
    _bounded_text(content.get("model"), maximum=200)
    _bounded_text(content.get("provider"), maximum=200)
    _nonnegative_int(content.get("elapsed_ms"))
    key_points = content.get("key_points")
    if not isinstance(key_points, list) or not 1 <= len(key_points) <= 500:
        raise ValueError("clarification key points are invalid")
    for point in key_points:
        _bounded_text(point, maximum=20_000)
    _validate_references(content.get("references"))


def _validate_references(value: Any) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 500:
        raise ValueError("Lean references are invalid")
    for reference in value:
        if not isinstance(reference, dict) or set(reference) != {
            "start_line",
            "end_line",
            "excerpt",
        }:
            raise ValueError("Lean reference fields are invalid")
        start = _positive_int(reference.get("start_line"))
        end = _positive_int(reference.get("end_line"))
        if end < start:
            raise ValueError("Lean reference range is invalid")
        _bounded_text(reference.get("excerpt"), maximum=20_000)


def _validate_worker_diagnostics(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("worker diagnostics are invalid")
    for diagnostic in value:
        if not isinstance(diagnostic, dict):
            raise ValueError("worker diagnostic must be an object")
        if not {"severity", "message"}.issubset(diagnostic) or not set(
            diagnostic
        ).issubset({"severity", "message", "code", "line", "column"}):
            raise ValueError("worker diagnostic fields are invalid")
        if diagnostic.get("severity") not in {"info", "warning", "error"}:
            raise ValueError("worker diagnostic severity is invalid")
        _bounded_text(diagnostic.get("message"), maximum=20_000)
        code = diagnostic.get("code")
        if code is not None and (not isinstance(code, str) or len(code) > 120):
            raise ValueError("worker diagnostic code is invalid")
        line = diagnostic.get("line")
        column = diagnostic.get("column")
        if line is not None:
            _positive_int(line)
        if column is not None:
            _nonnegative_int(column)


def _bounded_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("bounded text field is invalid")
    return value


def _positive_int(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("positive integer field is invalid")
    return value


def _nonnegative_int(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("nonnegative integer field is invalid")
    return value


def _aware_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("timestamp field is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp field is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp field must include a timezone")


def _strip_redundant_parentheses(value: str) -> str | None:
    """Strip only balanced pairs that surround the complete expression."""
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return None
    if depth != 0:
        return None

    while value.startswith("(") and value.endswith(")"):
        depth = 0
        surrounds_complete_expression = True
        for index, character in enumerate(value):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            if depth == 0 and index != len(value) - 1:
                surrounds_complete_expression = False
                break
        if not surrounds_complete_expression:
            break
        value = value[1:-1]
    return value


def _without_lean_comments(source: str) -> str:
    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    in_quoted_identifier = False
    escaped = False
    while index < len(source):
        if block_depth > 0:
            if source.startswith("/-", index):
                block_depth += 1
                index += 2
            elif source.startswith("-/", index):
                block_depth -= 1
                index += 2
            else:
                if source[index] == "\n":
                    output.append("\n")
                index += 1
            continue
        if in_quoted_identifier:
            character = source[index]
            output.append("\n" if character == "\n" else " ")
            index += 1
            if character == "»":
                in_quoted_identifier = False
            continue
        if in_string:
            character = source[index]
            output.append("\n" if character == "\n" else " ")
            index += 1
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if source.startswith("--", index):
            newline = source.find("\n", index + 2)
            if newline < 0:
                break
            output.append("\n")
            index = newline + 1
            continue
        if source.startswith("/-", index):
            block_depth = 1
            index += 2
            continue
        character = source[index]
        output.append(" " if character in {'"', "«"} else character)
        index += 1
        if character == '"':
            in_string = True
        elif character == "«":
            in_quoted_identifier = True
    return "".join(output)


def _top_level_declarations(source: str) -> list[re.Match[str]]:
    declarations: list[re.Match[str]] = []
    depth = 0
    index = 0
    pattern = re.compile(r"(?:theorem|example)\b")
    while index < len(source):
        character = source[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            declaration = pattern.match(source, index)
            if declaration is not None and (
                index == 0
                or not (source[index - 1].isalnum() or source[index - 1] == "_")
            ):
                declarations.append(declaration)
                index = declaration.end()
                continue
        index += 1
    return declarations


def _theorem_propositions(lean_code: str) -> list[str]:
    source = _without_lean_comments(lean_code)
    propositions: list[str] = []
    for declaration in _top_level_declarations(source):
        depth = 0
        proposition_start: int | None = None
        index = declaration.end()
        while index < len(source):
            character = source[index]
            if character in "([{":
                depth += 1
            elif character in ")]}":
                depth = max(0, depth - 1)
            elif (
                depth == 0
                and proposition_start is None
                and character == ":"
                and not source.startswith(":=", index)
            ):
                proposition_start = index + 1
            if depth == 0 and source.startswith(":=", index):
                if proposition_start is not None:
                    propositions.append(source[proposition_start:index])
                break
            index += 1
    return propositions


def _matches_x_squared_continuity(proposition: str) -> bool:
    declaration = re.sub(r"\s+", "", proposition).replace("²", "^2")
    if not declaration.startswith("Continuous"):
        return False
    expression = _strip_redundant_parentheses(
        declaration[len("Continuous") :],
    )
    if expression is None or not expression.startswith("fun"):
        return False

    lambda_body = expression[len("fun") :]
    arrow_positions = [
        position
        for position in (lambda_body.find("=>"), lambda_body.find("↦"))
        if position >= 0
    ]
    if not arrow_positions:
        return False
    arrow_position = min(arrow_positions)
    arrow_width = 2 if lambda_body[arrow_position :].startswith("=>") else 1
    binder = lambda_body[:arrow_position]
    body = lambda_body[arrow_position + arrow_width :]

    binder_match = re.fullmatch(
        r"(?P<variable>[A-Za-z_][A-Za-z0-9_']*)(?::(?P<type>.+))?",
        binder,
    )
    if binder_match is None:
        return False
    binder_type = binder_match.group("type")
    if binder_type is None:
        return False
    normalized_type = _strip_redundant_parentheses(binder_type)
    if normalized_type != "ℝ":
        return False

    normalized_body = _strip_redundant_parentheses(body)
    if normalized_body is None or "^" not in normalized_body:
        return False
    base, exponent = normalized_body.rsplit("^", maxsplit=1)
    normalized_base = _strip_redundant_parentheses(base)
    normalized_exponent = _strip_redundant_parentheses(exponent)
    return (
        normalized_base == binder_match.group("variable")
        and normalized_exponent == "2"
    )


def _verified_candidate_matches_statement(statement: str, lean_code: str) -> bool:
    """Reject a verified but unrelated theorem before it can acquire an explanation."""
    normalized_statement = re.sub(r"\s+", "", statement).lower()
    is_x_squared_continuity = "連続" in normalized_statement and (
        "x²" in normalized_statement or "x^2" in normalized_statement
    )
    if not is_x_squared_continuity:
        return True
    return any(
        _matches_x_squared_continuity(proposition)
        for proposition in _theorem_propositions(lean_code)
    )


def _same_verified_proof(
    payload: Any,
    *,
    proof_job_id: str,
    theorem_statement: str,
    lean_code: str,
) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("id") == proof_job_id
        and payload.get("state") == "verified"
        and isinstance(payload.get("theorem_statement"), str)
        and payload.get("theorem_statement") == theorem_statement
        and isinstance(payload.get("lean_code"), str)
        and bool(payload.get("lean_code"))
        and payload.get("lean_code") == lean_code
    )


def _public_explanation_content(explanation: ProofExplanation) -> dict[str, Any]:
    return {
        "overview": explanation.overview,
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "summary": section.summary,
                "references": [
                    {
                        "start_line": reference.start_line,
                        "end_line": reference.end_line,
                        "excerpt": reference.excerpt,
                    }
                    for reference in section.references
                ],
            }
            for section in explanation.sections
        ],
        "conclusion": explanation.conclusion,
        "model": explanation.model,
        "provider": explanation.provider,
        "elapsed_ms": explanation.elapsed_ms,
    }


def _public_clarification_content(clarification: ProofClarification) -> dict[str, Any]:
    return {
        "section_id": clarification.section_id,
        "question": clarification.question,
        "answer": clarification.answer,
        "key_points": list(clarification.key_points),
        "references": [
            {
                "start_line": reference.start_line,
                "end_line": reference.end_line,
                "excerpt": reference.excerpt,
            }
            for reference in clarification.references
        ],
        "model": clarification.model,
        "provider": clarification.provider,
        "elapsed_ms": clarification.elapsed_ms,
    }


def _fixed_diagnostic(code: str, message: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message)


def _status_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [
        Diagnostic(
            severity=diagnostic.severity,
            code=diagnostic.code,
            message=_SENSITIVE_STATUS_MESSAGES.get(
                diagnostic.code or "",
                diagnostic.message,
            ),
            line=diagnostic.line,
            column=diagnostic.column,
        )
        for diagnostic in diagnostics
    ]


def _proof_status_context(
    *,
    state: ProofJobState,
    raw: dict[str, Any],
    diagnostics: list[Diagnostic],
    max_repair_attempts: int,
) -> dict[str, Any]:
    """Project DSP progress into the API's closed status-context contract."""

    context: dict[str, Any] = {
        "schema_version": _STATUS_CONTEXT_SCHEMA,
        "stage": state,
    }
    for key in ("problem_id", "draft_id"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value

    retrieval = _status_retrieval(raw.get("retrieval"))
    if retrieval is not None:
        context["retrieval"] = retrieval

    if state not in {"repairing", "verified", "failed", "canceled", "compiling"}:
        return context

    attempt = _status_attempt(raw.get("attempt_evidence"))
    if attempt is None:
        if state == "compiling":
            return context
        if state != "failed":
            raise ValueError("terminal proof status lacks attempt evidence")
        attempt = _synthetic_failure_attempt(diagnostics)

    repairs_used = raw.get("repairs_used")
    if type(repairs_used) is not int or repairs_used < 0:
        repairs_used = max(0, int(attempt["attempt"]) - 1)
    configured_repairs = raw.get("max_repair_attempts")
    if (
        type(configured_repairs) is not int
        or configured_repairs < 1
        or configured_repairs > 64
    ):
        configured_repairs = max_repair_attempts
    elapsed_ms = raw.get("verification_elapsed_ms")
    if type(elapsed_ms) is not int or elapsed_ms < 0:
        elapsed_ms = int(attempt["verification"]["elapsed_ms"])

    context.update(
        {
            "attempt_evidence": attempt,
            "repairs_used": repairs_used,
            "max_repair_attempts": configured_repairs,
            "verification_elapsed_ms": elapsed_ms,
        }
    )

    if state == "compiling":
        return context

    if state == "repairing":
        route = _status_repair_route(raw.get("repair_route"), raw.get("selector_attempts"))
        if route is None:
            raise ValueError("repairing proof status lacks a selected repair route")
        context["repair_route"] = route
        context["selector_attempts"] = route["selector_attempts"]
        return context

    if state == "canceled":
        context.update(
            {
                "termination_reason": "canceled",
                "termination_event": {
                    "reason": "canceled",
                    "attempt": 0,
                    "source": "cancellation",
                },
            }
        )
        context.pop("attempt_evidence")
        context.pop("repairs_used")
        context.pop("max_repair_attempts")
        context.pop("verification_elapsed_ms")
        return context

    termination_reason = raw.get("termination_reason")
    termination_event = raw.get("termination_event")
    if not isinstance(termination_reason, str) or not isinstance(termination_event, dict):
        termination_reason = "non_repairable_failure"
        termination_event = {
            "reason": termination_reason,
            "attempt": attempt["attempt"],
            "source": "verifier_configuration",
        }
    context["termination_reason"] = termination_reason
    context["termination_event"] = {
        "reason": termination_event.get("reason"),
        "attempt": termination_event.get("attempt"),
        "source": termination_event.get("source"),
    }
    return context


def _status_retrieval(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    scores = value.get("scores")
    if not isinstance(scores, dict):
        scores = {}
    related_context = value.get("related_context")
    related_ids = (
        [related_context["source_draft_id"]]
        if isinstance(related_context, dict)
        and isinstance(related_context.get("source_draft_id"), str)
        and related_context["source_draft_id"].strip()
        else []
    )
    return {
        "candidate_draft_id": value.get("candidate_draft_id"),
        "related_draft_ids": related_ids,
        "exact_equivalence": value.get("exact_equivalence") is True,
        "scores": {
            "vector": scores.get("vector"),
            "structural": scores.get("structural"),
            "final": scores.get("final"),
        },
    }


def _status_attempt(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    attempt = value.get("attempt")
    phase = value.get("phase")
    generated = _status_generated(value.get("generated"))
    verification = _status_verification(value.get("verification"))
    checkpoint_status = value.get("checkpoint_status")
    if (
        type(attempt) is not int
        or phase not in {"preflight", "compile"}
        or generated is None
        or verification is None
        or checkpoint_status not in {"published", "failed"}
    ):
        return None
    result: dict[str, Any] = {
        "attempt": attempt,
        "phase": phase,
        "generated": generated,
        "verification": verification,
        "diagnostics": _status_diagnostic_payloads(value.get("diagnostics")),
        "checkpoint_status": checkpoint_status,
        "repair_route": _status_repair_route(
            value.get("repair_route"),
            None,
        ),
    }
    return result


def _status_generated(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    model = value.get("model")
    provider = value.get("provider")
    elapsed_ms = value.get("elapsed_ms")
    lean_code = value.get("lean_code")
    if (
        not isinstance(model, str)
        or not model.strip()
        or not isinstance(provider, str)
        or not provider.strip()
        or type(elapsed_ms) is not int
        or elapsed_ms < 0
        or not isinstance(lean_code, str)
    ):
        return None
    return {
        "lean_code": lean_code,
        "model": model,
        "provider": provider,
        "elapsed_ms": elapsed_ms,
        "draft": _status_draft(value.get("draft")),
        "sketch": _status_sketch(value.get("sketch")),
        "stage_diagnostics": _status_diagnostic_payloads(value.get("stage_diagnostics")),
    }


def _status_draft(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = ("text", "model", "provider")
    elapsed_ms = value.get("elapsed_ms")
    if (
        not all(isinstance(value.get(key), str) and value[key].strip() for key in keys)
        or type(elapsed_ms) is not int
        or elapsed_ms < 0
    ):
        return None
    return {key: value[key] for key in keys} | {"elapsed_ms": elapsed_ms}


def _status_sketch(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = ("lean_code", "model", "provider")
    elapsed_ms = value.get("elapsed_ms")
    if (
        not all(isinstance(value.get(key), str) and value[key].strip() for key in keys)
        or not isinstance(value.get("has_gaps"), bool)
        or type(elapsed_ms) is not int
        or elapsed_ms < 0
    ):
        return None
    return {
        **{key: value[key] for key in keys},
        "has_gaps": value["has_gaps"],
        "elapsed_ms": elapsed_ms,
    }


def _status_verification(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    success = value.get("success")
    elapsed_ms = value.get("elapsed_ms")
    if not isinstance(success, bool) or type(elapsed_ms) is not int or elapsed_ms < 0:
        return None
    return {
        "success": success,
        "diagnostics": _status_diagnostic_payloads(value.get("diagnostics")),
        "elapsed_ms": elapsed_ms,
    }


def _status_repair_route(
    value: object,
    attempts_value: object,
) -> dict[str, Any] | None:
    raw = value if isinstance(value, dict) else None
    route = raw.get("route") if raw is not None else value
    attempts = (
        raw.get("selector_attempts")
        if raw is not None
        else attempts_value
    )
    if route not in {"draft", "sketch", "prove"} or not isinstance(attempts, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in attempts:
        if not isinstance(item, dict):
            return None
        candidate = {
            "attempt": item.get("attempt"),
            "outcome": item.get("outcome"),
            "diagnostic_code": item.get("diagnostic_code"),
            "route": item.get("route"),
        }
        normalized.append(candidate)
    return {"route": route, "selector_attempts": normalized}


def _status_diagnostic_payloads(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, Diagnostic):
            result.append(
                {
                    "severity": item.severity,
                    "message": _SENSITIVE_STATUS_MESSAGES.get(
                        item.code or "",
                        item.message,
                    ),
                    "code": item.code,
                    "line": item.line,
                    "column": item.column,
                }
            )
        elif isinstance(item, dict):
            code = item.get("code")
            result.append(
                {
                    "severity": item.get("severity"),
                    "message": _SENSITIVE_STATUS_MESSAGES.get(
                        code if isinstance(code, str) else "",
                        item.get("message"),
                    ),
                    "code": code,
                    "line": item.get("line"),
                    "column": item.get("column"),
                }
            )
    return result


def _synthetic_failure_attempt(diagnostics: list[Diagnostic]) -> dict[str, Any]:
    payload = _status_diagnostic_payloads(diagnostics)
    return {
        "attempt": 1,
        "phase": "preflight",
        "generated": {
            "lean_code": "",
            "model": _OPENMATH_ROLE_MODEL.model,
            "provider": _OPENMATH_ROLE_MODEL.provider,
            "elapsed_ms": 0,
            "draft": None,
            "sketch": None,
            "stage_diagnostics": [],
        },
        "verification": {"success": False, "diagnostics": payload, "elapsed_ms": 0},
        "diagnostics": payload,
        "checkpoint_status": "published",
        "repair_route": None,
    }


def _has_api_compile_failure(proof_job: dict[str, Any]) -> bool:
    diagnostics = proof_job.get("diagnostics")
    return isinstance(diagnostics, list) and any(
        isinstance(item, dict) and item.get("code") == "verifier_compile_failed"
        for item in diagnostics
    )


def _has_pending_api_candidate(proof_job: dict[str, Any]) -> bool:
    diagnostics = proof_job.get("diagnostics")
    return isinstance(diagnostics, list) and any(
        isinstance(item, dict) and item.get("code") == "pals.verification_pending"
        for item in diagnostics
    )


def _api_repair_seed_from_worker_input(
    proof_job: dict[str, Any],
) -> ApiRepairSeed | None:
    """Rebuild only the API-authoritative compile-failure repair input.

    Raw compiler output and verifier transport details never cross this boundary.  Any malformed
    stored status is deliberately not treated as a license to regenerate from scratch.
    """

    if proof_job.get("state") != "compiling" or not _has_api_compile_failure(proof_job):
        return None
    raw_context = proof_job.get("status_context")
    if not isinstance(raw_context, dict) or raw_context.get("stage") != "compiling":
        return None
    attempt = raw_context.get("attempt_evidence")
    repairs_used = raw_context.get("repairs_used")
    max_repairs = raw_context.get("max_repair_attempts")
    elapsed_ms = raw_context.get("verification_elapsed_ms")
    if (
        not isinstance(attempt, dict)
        or type(repairs_used) is not int
        or type(max_repairs) is not int
        or type(elapsed_ms) is not int
        or not 0 <= repairs_used < max_repairs <= 64
    ):
        return None
    attempt_number = attempt.get("attempt")
    if type(attempt_number) is not int or attempt_number != repairs_used + 1:
        return None
    generated = _generated_proof_from_status(attempt.get("generated"))
    if generated is None:
        return None
    diagnostics = _worker_diagnostics_from_payload(proof_job.get("diagnostics"))
    if diagnostics is None or not any(
        item.severity == "error" and item.code == "verifier_compile_failed"
        for item in diagnostics
    ):
        return None
    return ApiRepairSeed(
        generated=generated,
        verification=VerificationResult(
            success=False,
            diagnostics=diagnostics,
            stdout="",
            stderr="",
            elapsed_ms=elapsed_ms,
        ),
        attempt=attempt_number,
        repairs_used=repairs_used,
    )


def _generated_proof_from_status(value: object) -> GeneratedProof | None:
    if not isinstance(value, dict):
        return None
    lean_code = value.get("lean_code")
    model = value.get("model")
    provider = value.get("provider")
    elapsed_ms = value.get("elapsed_ms")
    if (
        not isinstance(lean_code, str)
        or not lean_code.strip()
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(provider, str)
        or not provider.strip()
        or type(elapsed_ms) is not int
        or elapsed_ms < 0
    ):
        return None
    draft = _generated_draft_from_status(value.get("draft"))
    if value.get("draft") is not None and draft is None:
        return None
    sketch = _generated_sketch_from_status(value.get("sketch"))
    if value.get("sketch") is not None and sketch is None:
        return None
    stage_diagnostics = _worker_diagnostics_from_payload(value.get("stage_diagnostics"))
    if stage_diagnostics is None:
        return None
    return GeneratedProof(
        lean_code=lean_code,
        model=model,
        raw_model_output=lean_code,
        draft=draft,
        sketch=sketch,
        provider=provider,
        elapsed_ms=elapsed_ms,
        stage_diagnostics=tuple(stage_diagnostics),
    )


def _generated_draft_from_status(value: object) -> GeneratedDraft | None:
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    model = value.get("model")
    provider = value.get("provider")
    elapsed_ms = value.get("elapsed_ms")
    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(provider, str)
        or not provider.strip()
        or type(elapsed_ms) is not int
        or elapsed_ms < 0
    ):
        return None
    return GeneratedDraft(
        text=text,
        model=model,
        raw_model_output=text,
        provider=provider,
        elapsed_ms=elapsed_ms,
    )


def _generated_sketch_from_status(value: object) -> GeneratedSketch | None:
    if not isinstance(value, dict):
        return None
    lean_code = value.get("lean_code")
    model = value.get("model")
    provider = value.get("provider")
    has_gaps = value.get("has_gaps")
    elapsed_ms = value.get("elapsed_ms")
    if (
        not isinstance(lean_code, str)
        or not lean_code.strip()
        or not isinstance(model, str)
        or not model.strip()
        or not isinstance(provider, str)
        or not provider.strip()
        or not isinstance(has_gaps, bool)
        or type(elapsed_ms) is not int
        or elapsed_ms < 0
    ):
        return None
    return GeneratedSketch(
        lean_code=lean_code,
        model=model,
        raw_model_output=lean_code,
        has_gaps=has_gaps,
        provider=provider,
        elapsed_ms=elapsed_ms,
    )


def _worker_diagnostics_from_payload(value: object) -> list[Diagnostic] | None:
    if not isinstance(value, list) or len(value) > 100:
        return None
    diagnostics: list[Diagnostic] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        severity = item.get("severity")
        message = item.get("message")
        code = item.get("code")
        line = item.get("line")
        column = item.get("column")
        if (
            severity not in {"info", "warning", "error"}
            or not isinstance(message, str)
            or not message.strip()
            or (code is not None and (not isinstance(code, str) or not code.strip()))
            or (line is not None and (type(line) is not int or line < 1))
            or (column is not None and (type(column) is not int or column < 0))
        ):
            return None
        diagnostics.append(
            Diagnostic(
                severity=severity,
                message=message,
                code=code,
                line=line,
                column=column,
            )
        )
    return diagnostics


def _candidate_artifact_uri(
    proof_job: dict[str, Any],
    *,
    run_result: Any,
    lean_code: str | None,
) -> str:
    """Select a durable model artifact or the exact pre-persisted manual fixture."""
    if not isinstance(lean_code, str) or not lean_code.strip():
        raise ValueError("verified candidate requires nonblank Lean code")
    artifact = getattr(run_result, "artifact", None)
    artifact_uri = getattr(artifact, "lean_uri", None)
    if isinstance(artifact_uri, str) and _MODEL_ARTIFACT_URI_RE.fullmatch(artifact_uri):
        return artifact_uri
    return _manual_fixture_candidate_uri(proof_job, lean_code=lean_code)


def _manual_fixture_candidate_uri(
    proof_job: dict[str, Any],
    *,
    lean_code: str | None,
) -> str:
    """Return the pre-persisted fixture URI only when it binds this exact Lean byte sequence."""
    if not isinstance(lean_code, str) or not lean_code.strip():
        raise ValueError("verified candidate requires nonblank Lean code")
    request_context = proof_job.get("request_context")
    if not isinstance(request_context, dict):
        raise ValueError("verified candidate requires persisted fixture provenance")
    provenance = request_context.get("fixture_provenance")
    expected_keys = {
        "kind",
        "artifact_uri",
        "model_generated",
        "sha256",
        "verification_success",
        "verifier",
    }
    if not isinstance(provenance, dict) or set(provenance) != expected_keys:
        raise ValueError("verified candidate requires persisted fixture provenance")
    artifact_uri = provenance["artifact_uri"]
    lean_sha256 = hashlib.sha256(lean_code.encode("utf-8")).hexdigest()
    if (
        provenance["kind"] != "manual_verified_fixture"
        or provenance["model_generated"] is not False
        or provenance["verification_success"] is not True
        or provenance["verifier"] != "isolated_mtls_http_lean_verifier"
        or provenance["sha256"] != lean_sha256
        or not isinstance(artifact_uri, str)
    ):
        raise ValueError("verified candidate does not match persisted fixture provenance")
    uri_match = _MANUAL_FIXTURE_URI_RE.fullmatch(artifact_uri)
    if uri_match is None or uri_match.group(1) != lean_sha256:
        raise ValueError("verified candidate fixture URI does not bind Lean bytes")
    return artifact_uri


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Worker input is missing object field: {key}")
    return value


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Worker input is missing text field: {key}")
    return value.strip()
