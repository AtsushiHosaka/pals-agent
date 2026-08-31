from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, cast

from pals_agent.artifacts import (
    ATTEMPT_CHECKPOINT_SCHEMA_VERSION,
    ArtifactPersistenceError,
    ArtifactStore,
)
from pals_agent.draft_catalog import DraftCatalog, DraftSearchResult
from pals_agent.models import (
    DEFAULT_MAX_REPAIR_ATTEMPTS,
    BenchmarkProblem,
    Diagnostic,
    FormalStatementSource,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofDraft,
    ProofJobState,
    ProofRequest,
    ProofRunResult,
    RelatedDraftContext,
    RepairRoute,
    RepairRouteDecision,
    RepairRouteSelectionError,
    VerificationHarnessSource,
    VerificationResult,
)
from pals_agent.proof_flow_runtime import DraftRetrievalResult

_THEOREM_DECLARATION_RE = re.compile(
    r"\btheorem\s+(?P<name>[A-Za-z_][A-Za-z0-9_'.]*)(?P<signature>.*?)\s*:=",
    re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_TARGET_SPECIFIC_MATH_RE = re.compile(r"[=^|<>≤≥→ₗℝℕεδλ∈∑]")
_EPSILON_DELTA_REQUEST_RE = re.compile(
    r"イプシロン(?:\s|[・\-‐‑‒–—ー])*デルタ|"
    r"ε\s*[-‐‑‒–—ー]?\s*δ|"
    r"epsilon(?:\s|[-‐‑‒–—ー])*delta",
    re.IGNORECASE,
)
_EPSILON_DELTA_SHORTCUT_RE = re.compile(
    r"\b(?:"
    r"continuous_(?!iff\b)[A-Za-z0-9_']*(?:\s*\.\s*[A-Za-z0-9_']+)*|"
    r"Continuous(?:At|WithinAt|On)?\.[A-Za-z0-9_']+|"
    r"continuity"
    r")\b"
)
_EXACT_DRAFT_PROOF_METHODS: dict[str, Literal["epsilon_delta"]] = {
    "continuous_square": "epsilon_delta",
}
_NON_REPAIRABLE_DIAGNOSTIC_CODES = frozenset(
    {
        "lake.not_found",
        "lean.not_found",
        "lean.project_not_found",
    }
)

StatusCallback = Callable[
    [ProofJobState, list[Diagnostic], str | None, str | None, dict[str, Any]],
    None,
]
TerminationReason = Literal[
    "verified",
    "awaiting_api_reconciliation",
    "repair_budget_exhausted",
    "non_repairable_failure",
    "repair_generator_unavailable",
    "repair_route_selection_failed",
    "artifact_store_failure",
]


class LeanGenerator(Protocol):
    def generate(self, request: ProofRequest) -> GeneratedProof: ...


class RepairableLeanGenerator(Protocol):
    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof: ...


class RepairRouteSelector(Protocol):
    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision: ...


class StagedLeanGenerator(Protocol):
    def generate_draft(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedDraft: ...

    def generate_sketch(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedSketch: ...

    def generate_proof(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        sketch: GeneratedSketch,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedProof: ...


GeneratorPort = LeanGenerator | StagedLeanGenerator


class Verifier(Protocol):
    def verify(self, lean_code: str) -> VerificationResult: ...


class SketchVerifier(Protocol):
    def verify_sketch(self, lean_code: str) -> VerificationResult: ...


class SearchableDraftCatalog(Protocol):
    def search_by_statement(self, statement: str) -> DraftSearchResult | None: ...


class ProofFlowRetriever(Protocol):
    def retrieve(self, natural_statement: str) -> DraftRetrievalResult: ...


@dataclass(frozen=True, slots=True)
class RepairGeneration:
    generated: GeneratedProof
    route_decision: RepairRouteDecision


@dataclass(frozen=True, slots=True)
class ApiRepairSeed:
    """Durable API-verifier failure evidence used to resume a proof repair.

    The worker receives only the API-owned, content-safe compiler outcome.  It recreates
    the previous generated candidate from the persisted status context and hands it to
    the pipeline, which must select a route before it generates the next candidate.
    """

    generated: GeneratedProof
    verification: VerificationResult
    attempt: int
    repairs_used: int


@dataclass(frozen=True, slots=True)
class ProofPipeline:
    generator: GeneratorPort
    verifier: Verifier | None
    artifact_store: ArtifactStore
    draft_catalog: DraftCatalog | None = None
    proof_flow_retriever: ProofFlowRetriever | None = None
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS
    verification_mode: Literal["local", "api_reconcile"] = "local"

    def __post_init__(self) -> None:
        if (
            type(self.max_repair_attempts) is not int
            or not 1 <= self.max_repair_attempts <= 64
        ):
            raise ValueError("max_repair_attempts must be between 1 and 64")
        if self.verification_mode == "local" and self.verifier is None:
            raise ValueError("local verification requires a verifier")
        if self.verification_mode == "api_reconcile" and self.verifier is not None:
            raise ValueError("API reconciliation mode forbids a worker verifier")

    def run_problem(
        self,
        *,
        problem: BenchmarkProblem,
        proof_job_id: str | None = None,
        on_status: StatusCallback | None = None,
    ) -> ProofRunResult:
        request = self._request_for_statement(problem.prompt, problem_id=problem.id)
        return self._run_request(
            request=request,
            verification_harness=None,
            verification_harness_source=None,
            proof_job_id=proof_job_id,
            run_id=proof_job_id or problem.id,
            problem_id=problem.id,
            on_status=on_status,
        )

    def run_statement(
        self,
        *,
        statement: str,
        formal_statement: str | None = None,
        proof_job_id: str,
        on_status: StatusCallback | None = None,
        api_repair_seed: ApiRepairSeed | None = None,
    ) -> ProofRunResult:
        request = self._request_for_statement(
            statement,
            formal_statement=formal_statement,
        )
        return self._run_request(
            request=request,
            verification_harness=request.formal_statement,
            verification_harness_source=request.formal_statement_source,
            proof_job_id=proof_job_id,
            run_id=(
                f"{proof_job_id}.repair-{api_repair_seed.attempt + 1}"
                if api_repair_seed is not None
                else proof_job_id
            ),
            problem_id="custom_statement",
            on_status=on_status,
            api_repair_seed=api_repair_seed,
        )

    def _run_request(
        self,
        *,
        request: ProofRequest,
        verification_harness: str | None,
        verification_harness_source: VerificationHarnessSource | None,
        proof_job_id: str | None,
        run_id: str,
        problem_id: str,
        on_status: StatusCallback | None,
        api_repair_seed: ApiRepairSeed | None = None,
    ) -> ProofRunResult:
        diagnostics: list[Diagnostic]
        attempts: list[dict[str, Any]]
        failure_fingerprint_history: list[frozenset[str]]
        model_attempt_verification: VerificationResult | None
        current_repair_route: RepairRouteDecision | None

        if api_repair_seed is None:
            diagnostics = []
            attempts = []
            failure_fingerprint_history = []
            _emit(
                on_status,
                "retrieving_context",
                diagnostics,
                None,
                None,
                _request_context(request, problem_id=problem_id),
            )
            attempt = 1
            repairs_used = 0
            generated = self._generate_attempt(
                request=request,
                problem_id=problem_id,
                attempt=attempt,
                repairs_used=repairs_used,
                diagnostics=diagnostics,
                feedback=None,
                on_status=on_status,
            )
            model_attempt = generated
            model_attempt_verification = None
            current_repair_route = None
        else:
            _validate_api_repair_seed(
                api_repair_seed,
                max_repair_attempts=self.max_repair_attempts,
            )
            # Prior compiler diagnostics remain in the immutable attempt history and repair
            # prompt.  They must not be re-published as the current candidate's diagnostics,
            # otherwise a redelivered receipt would repair an already-pending replacement.
            diagnostics = []
            attempts = [
                _attempt_metadata(
                    attempt=api_repair_seed.attempt,
                    phase="compile",
                    generated=api_repair_seed.generated,
                    verification=api_repair_seed.verification,
                )
            ]
            attempts[0]["checkpoint_status"] = "published"
            failure_fingerprint_history = [
                _failure_fingerprint_set(api_repair_seed.verification.diagnostics)
            ]
            generated = api_repair_seed.generated
            model_attempt = generated
            model_attempt_verification = api_repair_seed.verification
            repair_generation = self._repair_after_failure(
                request=request,
                generated=generated,
                feedback_diagnostics=list(api_repair_seed.verification.diagnostics),
                cumulative_diagnostics=diagnostics,
                problem_id=problem_id,
                attempt=api_repair_seed.attempt,
                repairs_used=api_repair_seed.repairs_used,
                attempt_evidence=attempts[-1],
                on_status=on_status,
            )
            if repair_generation is None:
                return self._persist_and_emit(
                    request=request,
                    verification_harness_source=verification_harness_source,
                    proof_job_id=proof_job_id,
                    run_id=run_id,
                    problem_id=problem_id,
                    generated=generated,
                    model_attempt=model_attempt,
                    model_attempt_verification=model_attempt_verification,
                    verification=api_repair_seed.verification,
                    diagnostics=diagnostics,
                    attempts=attempts,
                    on_status=on_status,
                )
            generated = repair_generation.generated
            current_repair_route = repair_generation.route_decision
            attempt = api_repair_seed.attempt + 1
            repairs_used = api_repair_seed.repairs_used + 1
        while True:
            generation_diagnostic = _generation_diagnostic(generated)
            diagnostics.append(generation_diagnostic)

            preflight_diagnostics = validate_generated_lean(
                request,
                generated.lean_code,
                verification_harness=verification_harness,
            )
            if preflight_diagnostics:
                failure_diagnostics = [*generated.stage_diagnostics]
                if generation_diagnostic.severity == "error":
                    failure_diagnostics.append(generation_diagnostic)
                failure_diagnostics.extend(preflight_diagnostics)
                diagnostics.extend(preflight_diagnostics)
                verification = VerificationResult(
                    success=False,
                    diagnostics=failure_diagnostics,
                    stdout="",
                    stderr="",
                    elapsed_ms=0,
                )
                attempts.append(
                    _attempt_metadata(
                        attempt=attempt,
                        phase="preflight",
                        generated=generated,
                        verification=verification,
                        repair_route_decision=current_repair_route,
                    )
                )
                if model_attempt_verification is None:
                    model_attempt_verification = verification
                checkpoint_published = self._checkpoint_attempt(
                    run_id=run_id,
                    proof_job_id=proof_job_id,
                    problem_id=problem_id,
                    attempt=attempts[-1],
                    diagnostics=diagnostics,
                )
                if not checkpoint_published:
                    verification = _checkpoint_failure_verification(
                        verification=verification,
                        attempt=attempts[-1],
                        diagnostics=diagnostics,
                    )
                    if attempt == 1:
                        model_attempt_verification = verification
                    return self._persist_and_emit(
                        request=request,
                        verification_harness_source=verification_harness_source,
                        proof_job_id=proof_job_id,
                        run_id=run_id,
                        problem_id=problem_id,
                        generated=generated,
                        model_attempt=model_attempt,
                        model_attempt_verification=model_attempt_verification,
                        verification=verification,
                        diagnostics=diagnostics,
                        attempts=attempts,
                        on_status=on_status,
                        termination_reason_override="artifact_store_failure",
                    )

                repair_feedback_diagnostics = _with_repair_stagnation(
                    failure_diagnostics,
                    failure_fingerprint_history,
                )
                diagnostics.extend(
                    repair_feedback_diagnostics[len(failure_diagnostics) :]
                )
                repair_generation = self._repair_after_failure(
                    request=request,
                    generated=generated,
                    feedback_diagnostics=repair_feedback_diagnostics,
                    cumulative_diagnostics=diagnostics,
                    problem_id=problem_id,
                    attempt=attempt,
                    repairs_used=repairs_used,
                    attempt_evidence=attempts[-1],
                    on_status=on_status,
                )
                if repair_generation is None:
                    return self._persist_and_emit(
                        request=request,
                        verification_harness_source=verification_harness_source,
                        proof_job_id=proof_job_id,
                        run_id=run_id,
                        problem_id=problem_id,
                        generated=generated,
                        model_attempt=model_attempt,
                        model_attempt_verification=model_attempt_verification,
                        verification=verification,
                        diagnostics=diagnostics,
                        attempts=attempts,
                        on_status=on_status,
                    )

                generated = repair_generation.generated
                current_repair_route = repair_generation.route_decision
                attempt += 1
                repairs_used += 1
                continue

            _emit(
                on_status,
                "compiling",
                diagnostics,
                None,
                generated.lean_code,
                {
                    **_request_context(request, problem_id=problem_id),
                    "attempt": attempt,
                },
            )
            if self.verification_mode == "api_reconcile":
                verification = VerificationResult(
                    success=False,
                    diagnostics=[],
                    stdout="",
                    stderr="",
                    elapsed_ms=0,
                )
                attempts.append(
                    _attempt_metadata(
                        attempt=attempt,
                        phase="compile",
                        generated=generated,
                        verification=verification,
                        repair_route_decision=current_repair_route,
                    )
                )
                checkpoint_published = self._checkpoint_attempt(
                    run_id=run_id,
                    proof_job_id=proof_job_id,
                    problem_id=problem_id,
                    attempt=attempts[-1],
                    diagnostics=diagnostics,
                )
                if not checkpoint_published:
                    verification = _checkpoint_failure_verification(
                        verification=verification,
                        attempt=attempts[-1],
                        diagnostics=diagnostics,
                    )
                    return self._persist_and_emit(
                        request=request,
                        verification_harness_source=verification_harness_source,
                        proof_job_id=proof_job_id,
                        run_id=run_id,
                        problem_id=problem_id,
                        generated=generated,
                        model_attempt=model_attempt,
                        model_attempt_verification=model_attempt_verification,
                        verification=verification,
                        diagnostics=diagnostics,
                        attempts=attempts,
                        on_status=on_status,
                        termination_reason_override="artifact_store_failure",
                    )
                return self._persist_and_emit(
                    request=request,
                    verification_harness_source=verification_harness_source,
                    proof_job_id=proof_job_id,
                    run_id=run_id,
                    problem_id=problem_id,
                    generated=generated,
                    model_attempt=model_attempt,
                    model_attempt_verification=model_attempt_verification,
                    verification=verification,
                    diagnostics=diagnostics,
                    attempts=attempts,
                    on_status=on_status,
                    verification_pending=True,
                    termination_reason_override="awaiting_api_reconciliation",
                )

            verifier = self.verifier
            assert verifier is not None
            verification = verifier.verify(generated.lean_code)
            diagnostics = [*diagnostics, *verification.diagnostics]
            attempts.append(
                _attempt_metadata(
                    attempt=attempt,
                    phase="compile",
                    generated=generated,
                    verification=verification,
                    repair_route_decision=current_repair_route,
                )
            )
            if model_attempt_verification is None:
                model_attempt_verification = verification
            checkpoint_published = self._checkpoint_attempt(
                run_id=run_id,
                proof_job_id=proof_job_id,
                problem_id=problem_id,
                attempt=attempts[-1],
                diagnostics=diagnostics,
            )
            if not checkpoint_published:
                verification = _checkpoint_failure_verification(
                    verification=verification,
                    attempt=attempts[-1],
                    diagnostics=diagnostics,
                )
                if attempt == 1:
                    model_attempt_verification = verification
                return self._persist_and_emit(
                    request=request,
                    verification_harness_source=verification_harness_source,
                    proof_job_id=proof_job_id,
                    run_id=run_id,
                    problem_id=problem_id,
                    generated=generated,
                    model_attempt=model_attempt,
                    model_attempt_verification=model_attempt_verification,
                    verification=verification,
                    diagnostics=diagnostics,
                    attempts=attempts,
                    on_status=on_status,
                    termination_reason_override="artifact_store_failure",
                )

            if verification.success:
                return self._persist_and_emit(
                    request=request,
                    verification_harness_source=verification_harness_source,
                    proof_job_id=proof_job_id,
                    run_id=run_id,
                    problem_id=problem_id,
                    generated=generated,
                    model_attempt=model_attempt,
                    model_attempt_verification=model_attempt_verification,
                    verification=verification,
                    diagnostics=diagnostics,
                    attempts=attempts,
                    on_status=on_status,
                )

            repair_feedback_diagnostics = _with_repair_stagnation(
                verification.diagnostics,
                failure_fingerprint_history,
            )
            diagnostics.extend(
                repair_feedback_diagnostics[len(verification.diagnostics) :]
            )
            repair_generation = self._repair_after_failure(
                request=request,
                generated=generated,
                feedback_diagnostics=repair_feedback_diagnostics,
                cumulative_diagnostics=diagnostics,
                problem_id=problem_id,
                attempt=attempt,
                repairs_used=repairs_used,
                attempt_evidence=attempts[-1],
                on_status=on_status,
            )
            if repair_generation is None:
                return self._persist_and_emit(
                    request=request,
                    verification_harness_source=verification_harness_source,
                    proof_job_id=proof_job_id,
                    run_id=run_id,
                    problem_id=problem_id,
                    generated=generated,
                    model_attempt=model_attempt,
                    model_attempt_verification=model_attempt_verification,
                    verification=verification,
                    diagnostics=diagnostics,
                    attempts=attempts,
                    on_status=on_status,
                )

            generated = repair_generation.generated
            current_repair_route = repair_generation.route_decision
            attempt += 1
            repairs_used += 1

    def _generate_attempt(
        self,
        *,
        request: ProofRequest,
        problem_id: str,
        attempt: int,
        repairs_used: int,
        diagnostics: list[Diagnostic],
        feedback: GenerationFeedback | None,
        on_status: StatusCallback | None,
    ) -> GeneratedProof:
        repair_route = feedback.repair_route if feedback is not None else "draft"
        context: dict[str, Any] = {
            **_request_context(request, problem_id=problem_id),
            "attempt": attempt,
            "repair_attempt": repairs_used if feedback is not None else None,
            "repair_route": repair_route if feedback is not None else None,
            "repair_route_rationale": (
                feedback.repair_rationale if feedback is not None else None
            ),
            "max_repair_attempts": self.max_repair_attempts,
        }

        staged_generator = _staged_generator(self.generator)
        if staged_generator is not None:
            return _generate_staged_attempt(
                generator=staged_generator,
                request=request,
                feedback=feedback,
                repair_route=repair_route,
                diagnostics=diagnostics,
                context=context,
                on_status=on_status,
                verifier=self.verifier,
            )

        _emit(
            on_status,
            "proving",
            diagnostics,
            None,
            feedback.previous_lean_code if feedback is not None else None,
            {
                **context,
                "dsp_stage": "prove",
                "single_stage_generator": True,
                "model": getattr(self.generator, "model", None),
                "feedback_diagnostics": (
                    [diagnostic.to_api() for diagnostic in feedback.diagnostics]
                    if feedback is not None
                    else []
                ),
            },
        )

        if feedback is None:
            return cast(LeanGenerator, self.generator).generate(request)

        repaired = _repair_generated(self.generator, request, feedback)
        if repaired is None:
            raise RuntimeError("repair generation was requested for a non-repairable generator")
        return repaired

    def _repair_after_failure(
        self,
        *,
        request: ProofRequest,
        generated: GeneratedProof,
        feedback_diagnostics: list[Diagnostic],
        cumulative_diagnostics: list[Diagnostic],
        problem_id: str,
        attempt: int,
        repairs_used: int,
        attempt_evidence: dict[str, Any],
        on_status: StatusCallback | None,
    ) -> RepairGeneration | None:
        if any(
            diagnostic.code in _NON_REPAIRABLE_DIAGNOSTIC_CODES
            for diagnostic in feedback_diagnostics
        ):
            return None
        if repairs_used >= self.max_repair_attempts:
            cumulative_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="pals.repair_budget_exhausted",
                    message=(
                        "Lean repair stopped after using the configured budget of "
                        f"{self.max_repair_attempts} repair generations."
                    ),
                )
            )
            return None
        if not callable(getattr(self.generator, "repair", None)):
            cumulative_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="pals.repair_generator_unavailable",
                    message=(
                        "The configured generator cannot repair a failed Lean candidate."
                    ),
                )
            )
            return None

        base_feedback = GenerationFeedback(
            attempt=attempt,
            previous_lean_code=generated.lean_code,
            diagnostics=tuple(feedback_diagnostics),
            previous_draft=generated.draft,
            previous_sketch=generated.sketch,
        )
        try:
            route_decision = _select_repair_route(
                self.generator,
                request,
                base_feedback,
            )
        except RepairRouteSelectionError as exc:
            route_failure_metadata = {
                "prompt": exc.prompt,
                "model": exc.model,
                "provider": exc.provider,
                "elapsed_ms": exc.elapsed_ms,
                "attempt_outputs": list(exc.attempt_outputs),
                "selector_attempts": [
                    asdict(selector_attempt)
                    for selector_attempt in exc.selector_attempts
                ],
            }
            cumulative_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="pals.repair_route_selection_failed",
                    message=str(exc),
                    metadata=route_failure_metadata,
                )
            )
            _emit(
                on_status,
                "repairing",
                cumulative_diagnostics,
                None,
                generated.lean_code,
                {
                    **_request_context(request, problem_id=problem_id),
                    "failed_attempt": attempt,
                    "repair_attempt": repairs_used + 1,
                    "repair_route_selection_failed": True,
                    "repair_route_prompt": exc.prompt,
                    "repair_route_model": exc.model,
                    "repair_route_provider": exc.provider,
                    "repair_route_elapsed_ms": exc.elapsed_ms,
                    "repair_route_attempt_outputs": list(exc.attempt_outputs),
                    "selector_attempts": [
                        asdict(selector_attempt)
                        for selector_attempt in exc.selector_attempts
                    ],
                    "attempt_evidence": attempt_evidence,
                    "max_repair_attempts": self.max_repair_attempts,
                },
            )
            return None
        feedback = GenerationFeedback(
            attempt=base_feedback.attempt,
            previous_lean_code=base_feedback.previous_lean_code,
            diagnostics=base_feedback.diagnostics,
            repair_route=route_decision.route,
            repair_rationale=route_decision.rationale,
            previous_draft=base_feedback.previous_draft,
            previous_sketch=base_feedback.previous_sketch,
        )
        _emit(
            on_status,
            "repairing",
            cumulative_diagnostics,
            None,
            generated.lean_code,
            {
                **_request_context(request, problem_id=problem_id),
                "failed_attempt": attempt,
                "repair_attempt": repairs_used + 1,
                "repair_route": route_decision.route,
                "repair_route_rationale": route_decision.rationale,
                "repair_route_raw_model_output": route_decision.raw_model_output,
                "repair_route_prompt": route_decision.prompt,
                "repair_route_model": route_decision.model,
                "repair_route_provider": route_decision.provider,
                "repair_route_elapsed_ms": route_decision.elapsed_ms,
                "repair_route_attempt_outputs": list(route_decision.attempt_outputs),
                "selector_attempts": [
                    asdict(selector_attempt)
                    for selector_attempt in route_decision.selector_attempts
                ],
                "attempt_evidence": attempt_evidence,
                "max_repair_attempts": self.max_repair_attempts,
                "feedback_diagnostics": [
                    diagnostic.to_api() for diagnostic in feedback_diagnostics
                ],
            },
        )
        repaired = self._generate_attempt(
            request=request,
            problem_id=problem_id,
            attempt=attempt + 1,
            repairs_used=repairs_used + 1,
            diagnostics=cumulative_diagnostics,
            feedback=feedback,
            on_status=on_status,
        )
        return RepairGeneration(generated=repaired, route_decision=route_decision)

    def _checkpoint_attempt(
        self,
        *,
        run_id: str,
        proof_job_id: str | None,
        problem_id: str,
        attempt: dict[str, Any],
        diagnostics: list[Diagnostic],
    ) -> bool:
        attempt_number = attempt.get("attempt")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
            raise RuntimeError("Attempt metadata is missing its integer attempt number")
        attempt["checkpoint_status"] = "published"
        try:
            self.artifact_store.save_checkpoint(
                run_id=run_id,
                attempt=attempt_number,
                metadata={
                    "checkpoint_schema_version": ATTEMPT_CHECKPOINT_SCHEMA_VERSION,
                    "run_id": run_id,
                    "proof_job_id": proof_job_id,
                    "problem_id": problem_id,
                    "max_repair_attempts": self.max_repair_attempts,
                    "attempt": attempt,
                    "cumulative_diagnostics": [
                        diagnostic.to_api() for diagnostic in diagnostics
                    ],
                },
            )
        except Exception:
            attempt["checkpoint_status"] = "failed"
            attempt.pop("repair_route", None)
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="pals.artifact_checkpoint_failed",
                    message="The proof-attempt checkpoint could not be durably published.",
                )
            )
            return False
        return True

    def _persist_and_emit(
        self,
        *,
        request: ProofRequest,
        verification_harness_source: VerificationHarnessSource | None,
        proof_job_id: str | None,
        run_id: str,
        problem_id: str,
        generated: GeneratedProof,
        model_attempt: GeneratedProof,
        model_attempt_verification: VerificationResult | None,
        verification: VerificationResult,
        diagnostics: list[Diagnostic],
        attempts: list[dict[str, Any]],
        on_status: StatusCallback | None,
        verification_pending: bool = False,
        termination_reason_override: TerminationReason | None = None,
    ) -> ProofRunResult:
        repairs_used = max(0, len(attempts) - 1)
        termination_reason = (
            termination_reason_override
            if termination_reason_override is not None
            else _termination_reason(
                verification=verification,
                diagnostics=diagnostics,
                repairs_used=repairs_used,
                max_repair_attempts=self.max_repair_attempts,
            )
        )
        termination_event = _termination_event(
            termination_reason,
            attempt=len(attempts),
        )
        metadata = {
                "proof_job_id": proof_job_id,
                "problem_id": problem_id,
                "draft_id": request.id,
                "prompt": request.prompt,
                "formal_statement": request.formal_statement,
                "verification_harness": {
                    "source": verification_harness_source,
                    "hidden_from_generation": False,
                },
                "draft": _draft_metadata(request),
                "retrieval": _retrieval_metadata(request),
                "generated": asdict(generated),
                "model_attempt": asdict(model_attempt),
                "model_attempt_verification": (
                    asdict(model_attempt_verification)
                    if model_attempt_verification is not None
                    else None
                ),
                "verification": asdict(verification),
                "verification_pending": verification_pending,
                "post_runtime_evaluation": {
                    "sketch_adherence": _sketch_adherence(generated),
                },
                "attempts": attempts,
                "repairs_used": repairs_used,
                "max_repair_attempts": self.max_repair_attempts,
                "termination_reason": termination_reason,
                "termination_event": termination_event,
                "diagnostics": [diagnostic.to_api() for diagnostic in diagnostics],
            }
        try:
            artifact = self.artifact_store.save(
                run_id=run_id,
                lean_code=generated.lean_code,
                metadata=metadata,
            )
        except Exception as exc:
            raise ArtifactPersistenceError() from exc
        result = ProofRunResult(
            proof_job_id=proof_job_id,
            problem_id=problem_id,
            prompt=request.prompt,
            generated=generated,
            model_attempt=model_attempt,
            model_attempt_verification=model_attempt_verification,
            verification=verification,
            artifact=artifact,
            verification_pending=verification_pending,
        )
        _emit(
            on_status,
            result.state,
            diagnostics,
            artifact.uri,
            generated.lean_code or None,
            {
                **_request_context(request, problem_id=problem_id),
                "lean_artifact_uri": artifact.lean_uri,
                "verification_elapsed_ms": verification.elapsed_ms,
                "attempts": len(attempts),
                "repairs_used": repairs_used,
                "max_repair_attempts": self.max_repair_attempts,
                "termination_reason": termination_reason,
                "termination_event": termination_event,
                "attempt_evidence": attempts[-1],
            },
        )
        return result

    def _request_for_statement(
        self,
        statement: str,
        *,
        problem_id: str | None = None,
        formal_statement: str | None = None,
    ) -> ProofRequest:
        return _request_for_statement(
            statement,
            problem_id=problem_id,
            formal_statement=formal_statement,
            draft_catalog=self.draft_catalog,
            proof_flow_retriever=self.proof_flow_retriever,
        )


def validate_generated_lean(
    request: ProofRequest,
    lean_code: str,
    *,
    verification_harness: str | None = None,
    allow_theorem_name_variance: bool = False,
    defer_formal_harness: bool = False,
) -> list[Diagnostic]:
    if not lean_code.strip():
        return [
            Diagnostic(
                severity="error",
                code="pals.generation_empty",
                message="The model did not produce extractable Lean code.",
            )
        ]

    formal_statement = verification_harness or request.formal_statement

    if formal_statement and not defer_formal_harness:
        formal_diagnostics = _validate_formal_harness(
            formal_statement=formal_statement,
            lean_code=lean_code,
            allow_theorem_name_variance=allow_theorem_name_variance,
        )
        if formal_diagnostics:
            return formal_diagnostics
    return _validate_requested_proof_method(request, lean_code)


def _validate_requested_proof_method(
    request: ProofRequest,
    lean_code: str,
) -> list[Diagnostic]:
    """Reject a proof that ignores the learner or exact-retrieval ε–δ method."""
    if not _requires_epsilon_delta_method(request):
        return []

    executable_code = _strip_lean_comments_and_strings(lean_code)
    missing: list[str] = []
    if "Metric.continuous_iff" not in executable_code:
        missing.append("`Metric.continuous_iff`")
    if re.search(r"\bintro\b[^\n]*\bε\b", executable_code) is None:
        missing.append("an introduced `ε`")
    if re.search(r"\b(?:let|set)\s+(?:δ|delta)\b", executable_code) is None:
        missing.append("an explicit `δ` choice")

    shortcuts = sorted(set(_EPSILON_DELTA_SHORTCUT_RE.findall(executable_code)))
    if not missing and not shortcuts:
        return []

    details: list[str] = []
    if missing:
        details.append(f"missing {', '.join(missing)}")
    if shortcuts:
        details.append(f"uses continuity shortcut(s): {', '.join(shortcuts)}")
    return [
        Diagnostic(
            severity="error",
            code="pals.proof_method_mismatch",
            message=(
                "The selected epsilon-delta proof method requires generated Lean that "
                "must carry out that method rather than only establish continuity. "
                + "; ".join(details)
                + "."
            ),
        )
    ]


def _requires_epsilon_delta_method(request: ProofRequest) -> bool:
    if _EPSILON_DELTA_REQUEST_RE.search(request.prompt) is not None:
        return True
    return any(
        context.exact_equivalence
        and context.selected_proof_method == "epsilon_delta"
        for context in request.related_draft_contexts
    )


def _sketch_adherence(generated: GeneratedProof) -> bool | None:
    sketch = generated.sketch
    if sketch is None or not sketch.lean_code.strip() or not generated.lean_code.strip():
        return None
    return not _validate_proof_preserves_sketch(generated)


def _validate_proof_preserves_sketch(generated: GeneratedProof) -> list[Diagnostic]:
    sketch = generated.sketch
    if (
        sketch is None
        or not sketch.lean_code.strip()
        or not generated.lean_code.strip()
    ):
        return []

    scaffold = _sketch_scaffold_lines(sketch.lean_code)
    proof_lines = _lean_structural_lines(generated.lean_code)
    proof_index = 0
    for sketch_line in scaffold:
        while proof_index < len(proof_lines) and proof_lines[proof_index] != sketch_line:
            proof_index += 1
        if proof_index >= len(proof_lines):
            return [
                Diagnostic(
                    severity="error",
                    code="pals.sketch_contract_mismatch",
                    message=(
                        "The completed proof does not preserve the formal Sketch "
                        f"scaffold near: `{sketch_line}`"
                    ),
                )
            ]
        proof_index += 1
    return []


def _sketch_scaffold_lines(lean_code: str) -> list[str]:
    return _lean_structural_lines(lean_code)


def _lean_structural_lines(lean_code: str) -> list[str]:
    structural_prefixes = ("theorem ", "lemma ", "example ", "have ", "let ", "set ")
    lines = _normalized_lean_lines(_strip_lean_comments_and_strings(lean_code))
    structural_lines: list[str] = []
    for line in lines:
        if not line.startswith(structural_prefixes):
            continue
        if line.startswith(("theorem ", "lemma ", "example ", "have ")):
            signature = re.split(r"\s*:=", line, maxsplit=1)[0].strip()
        else:
            signature = line
        signature = re.split(r"\b(?:sorry|admit)\b", signature, maxsplit=1)[0].strip()
        if signature and "?_" not in signature:
            structural_lines.append(signature)
    return structural_lines


def _normalized_lean_lines(lean_code: str) -> list[str]:
    return [" ".join(line.split()) for line in lean_code.splitlines() if line.strip()]


def _repair_generated(
    generator: GeneratorPort,
    request: ProofRequest,
    feedback: GenerationFeedback,
) -> GeneratedProof | None:
    if not callable(getattr(generator, "repair", None)):
        return None
    return cast(RepairableLeanGenerator, generator).repair(request, feedback)


def _staged_generator(generator: GeneratorPort) -> StagedLeanGenerator | None:
    stage_methods = ("generate_draft", "generate_sketch", "generate_proof")
    if not all(callable(getattr(generator, method, None)) for method in stage_methods):
        return None
    return cast(StagedLeanGenerator, generator)


def _generate_staged_attempt(
    *,
    generator: StagedLeanGenerator,
    request: ProofRequest,
    feedback: GenerationFeedback | None,
    repair_route: RepairRoute,
    diagnostics: list[Diagnostic],
    context: dict[str, Any],
    on_status: StatusCallback | None,
    verifier: Verifier | None,
) -> GeneratedProof:
    draft = feedback.previous_draft if feedback is not None else None
    sketch = feedback.previous_sketch if feedback is not None else None

    if repair_route == "draft" or draft is None or not draft.text.strip():
        _emit(
            on_status,
            "drafting",
            diagnostics,
            None,
            None,
            {**context, "dsp_stage": "draft", "draft": _draft_metadata(request)},
        )
        draft = generator.generate_draft(request, feedback)
        sketch = None
        if not draft.text.strip():
            return _failed_staged_proof(draft=draft)

    if (
        repair_route in {"draft", "sketch"}
        or sketch is None
        or not sketch.lean_code.strip()
    ):
        _emit(
            on_status,
            "sketching",
            diagnostics,
            None,
            None,
            {
                **context,
                "dsp_stage": "sketch",
                "generated_draft": asdict(draft),
                "feedback_diagnostics": (
                    [diagnostic.to_api() for diagnostic in feedback.diagnostics]
                    if feedback is not None
                    else []
                ),
            },
        )
        sketch = generator.generate_sketch(request, draft, feedback)
        if not sketch.lean_code.strip():
            return _failed_staged_proof(draft=draft, sketch=sketch)
        sketch_verification = _verify_sketch(verifier, sketch.lean_code)
        if (
            sketch.has_gaps
            and sketch_verification is not None
            and not sketch_verification.success
        ):
            diagnostic_text = "\n".join(
                _format_diagnostic_for_trace(diagnostic)
                for diagnostic in sketch_verification.diagnostics
            )
            return _failed_staged_proof(
                draft=draft,
                sketch=sketch,
                error=(
                    "[generation-error] sketch Lean validation failed.\n"
                    f"{diagnostic_text}"
                ),
                stage_diagnostics=tuple(sketch_verification.diagnostics),
            )

    _emit(
        on_status,
        "proving",
        diagnostics,
        None,
        sketch.lean_code,
        {
            **context,
            "dsp_stage": "prove",
            "generated_draft": asdict(draft),
            "generated_sketch": asdict(sketch),
            "model": getattr(generator, "prove_model", None)
            or getattr(generator, "model", None),
        },
    )
    return generator.generate_proof(request, draft, sketch, feedback)


def _failed_staged_proof(
    *,
    draft: GeneratedDraft,
    sketch: GeneratedSketch | None = None,
    error: str | None = None,
    stage_diagnostics: tuple[Diagnostic, ...] = (),
) -> GeneratedProof:
    failed_stage = sketch if sketch is not None else draft
    return GeneratedProof(
        lean_code="",
        model=failed_stage.model,
        raw_model_output=error or failed_stage.raw_model_output,
        draft=draft,
        sketch=sketch,
        prompt=failed_stage.prompt,
        provider=failed_stage.provider,
        elapsed_ms=failed_stage.elapsed_ms,
        stage_diagnostics=stage_diagnostics,
    )


def _verify_sketch(
    verifier: Verifier | None,
    lean_code: str,
) -> VerificationResult | None:
    if verifier is None:
        return None
    verify_sketch = getattr(verifier, "verify_sketch", None)
    if not callable(verify_sketch):
        return None
    return cast(SketchVerifier, verifier).verify_sketch(lean_code)


def _format_diagnostic_for_trace(diagnostic: Diagnostic) -> str:
    location = f" line {diagnostic.line}" if diagnostic.line is not None else ""
    code = f" [{diagnostic.code}]" if diagnostic.code else ""
    return f"{diagnostic.severity}{location}{code}: {diagnostic.message}"


def _with_repair_stagnation(
    diagnostics: list[Diagnostic],
    failure_fingerprint_history: list[frozenset[str]],
) -> list[Diagnostic]:
    error_fingerprints = _failure_fingerprint_set(diagnostics)
    failure_fingerprint_history.append(error_fingerprints)
    if len(failure_fingerprint_history) < 3:
        return diagnostics

    persistent_fingerprints = set.intersection(
        *(set(fingerprints) for fingerprints in failure_fingerprint_history[-3:])
    )
    if not persistent_fingerprints:
        return diagnostics
    persistent_codes = sorted(
        {fingerprint.split("|", maxsplit=1)[0] for fingerprint in persistent_fingerprints}
    )
    stagnation = Diagnostic(
        severity="warning",
        code="pals.repair_stagnation",
        message=(
            "The following error codes persisted across the last 3 attempts: "
            + ", ".join(persistent_codes)
            + ". Reconsider whether repair should resume from sketch or draft instead "
            "of repeating the same local proof repair."
        ),
    )
    return [*diagnostics, stagnation]


def _repair_failure_fingerprint(diagnostic: Diagnostic) -> str:
    normalized_message = " ".join(diagnostic.message.casefold().split())
    return f"{diagnostic.code}|{normalized_message}"


def _failure_fingerprint_set(
    diagnostics: list[Diagnostic],
) -> frozenset[str]:
    return frozenset(
        _repair_failure_fingerprint(diagnostic)
        for diagnostic in diagnostics
        if diagnostic.severity == "error" and diagnostic.code
    )


def _validate_api_repair_seed(
    seed: ApiRepairSeed,
    *,
    max_repair_attempts: int,
) -> None:
    if (
        type(seed.attempt) is not int
        or type(seed.repairs_used) is not int
        or seed.attempt < 1
        or seed.repairs_used != seed.attempt - 1
        or seed.repairs_used >= max_repair_attempts
    ):
        raise ValueError("API repair seed has an invalid attempt or repair budget")
    if seed.verification.success:
        raise ValueError("API repair seed must represent a failed verification")
    if not seed.generated.lean_code.strip():
        raise ValueError("API repair seed requires nonblank prior Lean code")
    if not any(
        diagnostic.code == "verifier_compile_failed"
        and diagnostic.severity == "error"
        for diagnostic in seed.verification.diagnostics
    ):
        raise ValueError("API repair seed requires verifier_compile_failed evidence")


def _select_repair_route(
    generator: GeneratorPort,
    request: ProofRequest,
    feedback: GenerationFeedback,
) -> RepairRouteDecision:
    if callable(getattr(generator, "select_repair_route", None)):
        return cast(RepairRouteSelector, generator).select_repair_route(request, feedback)
    raise RepairRouteSelectionError(
        "Generator does not expose LLM DSP repair route selection."
    )


def _attempt_metadata(
    *,
    attempt: int,
    phase: str,
    generated: GeneratedProof,
    verification: VerificationResult,
    repair_route_decision: RepairRouteDecision | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "attempt": attempt,
        "phase": phase,
        "generated": asdict(generated),
        "verification": asdict(verification),
        "diagnostics": [diagnostic.to_api() for diagnostic in verification.diagnostics],
    }
    if repair_route_decision is not None:
        metadata["repair_route"] = asdict(repair_route_decision)
    serialized = json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    normalized = json.loads(serialized)
    if not isinstance(normalized, dict):
        raise RuntimeError("Attempt metadata did not serialize as an object")
    return cast(dict[str, Any], normalized)


def _checkpoint_failure_verification(
    *,
    verification: VerificationResult,
    attempt: dict[str, Any],
    diagnostics: list[Diagnostic],
) -> VerificationResult:
    checkpoint_diagnostic = next(
        (
            diagnostic
            for diagnostic in reversed(diagnostics)
            if diagnostic.code == "pals.artifact_checkpoint_failed"
        ),
        None,
    )
    if checkpoint_diagnostic is None:
        raise RuntimeError("Checkpoint failure diagnostic was not recorded")
    failed = VerificationResult(
        success=False,
        diagnostics=[*verification.diagnostics, checkpoint_diagnostic],
        stdout=verification.stdout,
        stderr=verification.stderr,
        elapsed_ms=verification.elapsed_ms,
    )
    attempt["verification"] = asdict(failed)
    attempt["diagnostics"] = [
        diagnostic.to_api() for diagnostic in failed.diagnostics
    ]
    return failed


def _termination_reason(
    *,
    verification: VerificationResult,
    diagnostics: list[Diagnostic],
    repairs_used: int,
    max_repair_attempts: int,
) -> TerminationReason:
    if verification.success:
        return "verified"

    codes = {diagnostic.code for diagnostic in diagnostics}
    if "pals.repair_route_selection_failed" in codes:
        return "repair_route_selection_failed"
    if "pals.repair_generator_unavailable" in codes:
        return "repair_generator_unavailable"
    if codes.intersection(_NON_REPAIRABLE_DIAGNOSTIC_CODES):
        return "non_repairable_failure"
    if (
        "pals.repair_budget_exhausted" in codes
        or repairs_used >= max_repair_attempts
    ):
        return "repair_budget_exhausted"
    raise RuntimeError(
        "Failed proof reached terminal persistence without an explicit termination reason"
    )


def _termination_event(
    reason: TerminationReason,
    *,
    attempt: int,
) -> dict[str, str | int]:
    sources = {
        "verified": "verification_success",
        "awaiting_api_reconciliation": "api_reconciliation",
        "repair_budget_exhausted": "repair_budget",
        "non_repairable_failure": "verifier_configuration",
        "repair_generator_unavailable": "repair_generator",
        "repair_route_selection_failed": "repair_route_selector",
        "artifact_store_failure": "artifact_store",
    }
    return {
        "reason": reason,
        "attempt": attempt,
        "source": sources[reason],
    }


def _generation_diagnostic(generated: GeneratedProof) -> Diagnostic:
    if generated.raw_model_output.startswith("[openai-error]"):
        return Diagnostic(
            severity="error",
            code="openai.error",
            message=generated.raw_model_output.removeprefix("[openai-error] ").strip(),
        )
    if generated.raw_model_output.startswith("[ollama-error]"):
        return Diagnostic(
            severity="error",
            code="ollama.error",
            message=generated.raw_model_output.removeprefix("[ollama-error] ").strip(),
        )
    if generated.raw_model_output.startswith("[generation-error]"):
        return Diagnostic(
            severity="error",
            code="llm.generation_failed",
            message=generated.raw_model_output.removeprefix("[generation-error] ").strip(),
        )
    if generated.lean_code.strip():
        return Diagnostic(
            severity="info",
            code="llm.generated",
            message=f"LLM produced a Lean candidate with model={generated.model}.",
        )
    return Diagnostic(
        severity="info",
        code="llm.empty",
        message=(
            "LLM did not produce extractable Lean code with "
            f"model={generated.model}."
        ),
    )


def _emit(
    callback: StatusCallback | None,
    state: ProofJobState,
    diagnostics: list[Diagnostic],
    result_artifact_uri: str | None,
    lean_code: str | None,
    context: dict[str, Any],
) -> None:
    if callback is None:
        return
    callback(state, diagnostics, result_artifact_uri, lean_code, context)


def _normalize_lean_text(text: str) -> str:
    return " ".join(text.split())


def _strip_lean_comments(text: str) -> str:
    return _strip_lean_comments_and_strings(text)


def _strip_lean_comments_and_strings(text: str) -> str:
    lines = []
    current: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    while index < len(text):
        current_pair = text[index : index + 2]
        char = text[index]

        if block_depth > 0:
            if current_pair == "/-":
                block_depth += 1
                index += 2
                continue
            if current_pair == "-/":
                block_depth -= 1
                index += 2
                continue
            if char == "\n":
                lines.append("".join(current))
                current = []
            index += 1
            continue

        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
            if char == "\n":
                lines.append("".join(current))
                current = []
            index += 1
            continue

        if current_pair == "/-":
            block_depth = 1
            index += 2
            continue

        if current_pair == "--":
            newline_index = text.find("\n", index)
            if newline_index == -1:
                break
            lines.append("".join(current))
            current = []
            index = newline_index + 1
            continue

        if char == '"':
            in_string = True
            current.append(" ")
            index += 1
            continue

        if char == "\n":
            lines.append("".join(current))
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    lines.append("".join(current))
    return "\n".join(lines)


def _validate_formal_harness(
    *,
    formal_statement: str,
    lean_code: str,
    allow_theorem_name_variance: bool = False,
) -> list[Diagnostic]:
    normalized_harness = _normalize_lean_text(formal_statement)
    normalized_code = _normalize_lean_text(_strip_lean_comments_and_strings(lean_code))
    if allow_theorem_name_variance:
        expected_signatures = _theorem_type_signatures(normalized_harness)
        generated_signatures = _theorem_type_signatures(normalized_code)
        if expected_signatures and any(
            signature in generated_signatures for signature in expected_signatures
        ):
            return []
    elif normalized_harness in normalized_code:
        return []

    return [
        Diagnostic(
            severity="error",
            code="lean.formal_harness_mismatch",
            message=(
                "Generated Lean code does not contain the fixed formal statement "
                "harness as Lean code."
            ),
        )
    ]


def _theorem_type_signatures(lean_code: str) -> tuple[str, ...]:
    return tuple(
        _normalize_lean_text(match.group("signature"))
        for match in _THEOREM_DECLARATION_RE.finditer(lean_code)
    )


def _draft_metadata(
    request: ProofRequest,
) -> dict[str, Any] | None:
    draft = request.draft
    if request.related_draft_contexts:
        return {
            "guidance_mode": "reranked_related_contexts",
            "related_contexts": [
                _related_draft_context_payload(context)
                for context in request.related_draft_contexts
            ],
        }
    if draft is None:
        return None
    if not request.exact_equivalence:
        return {
            "id": draft.id,
            "guidance_mode": "target_agnostic_related_context",
            "related_context": (
                _related_draft_context_payload(request.related_draft_context)
                if request.related_draft_context is not None
                else None
            ),
        }
    return {
        "id": draft.id,
        "guidance_mode": "exact_match_required_method",
        "matched_prompt": draft.matched_prompt,
        "openmath_xml": draft.openmath_xml,
        "proof_strategy": draft.proof_strategy,
        "sketch_steps": draft.sketch_steps,
    }


def _retrieval_metadata(request: ProofRequest) -> dict[str, Any]:
    draft = request.draft
    metadata: dict[str, Any] = {
        "query_openmath_xml": request.query_openmath_xml,
        "candidate_draft_id": draft.id if draft is not None else None,
        "candidate_openmath_xml": draft.openmath_xml if draft is not None else None,
        "scores": {
            "vector": request.vector_score,
            "structural": request.structural_score,
            "final": request.final_score,
        },
        "exact_equivalence": request.exact_equivalence,
        "formal_statement_source": request.formal_statement_source,
        "related_context": (
            _related_draft_context_payload(request.related_draft_context)
            if request.related_draft_context is not None
            else None
        ),
    }
    if request.related_draft_contexts:
        metadata["reranked_related_context_ids"] = [
            context.source_draft_id for context in request.related_draft_contexts
        ]
    if request.proof_flow_result is not None:
        metadata["proof_flow_result"] = request.proof_flow_result
    return metadata


def _related_draft_context_payload(context: RelatedDraftContext) -> dict[str, Any]:
    return {
        "source_draft_id": context.source_draft_id,
        "strategy_notes": list(context.strategy_notes),
        "sketch_steps": list(context.sketch_steps),
    }


def _request_context(request: ProofRequest, *, problem_id: str) -> dict[str, Any]:
    return {
        "problem_id": problem_id,
        "draft_id": request.id,
        "formal_statement": request.formal_statement,
        "retrieval": _retrieval_metadata(request),
    }


def _problem_for_statement(statement: str) -> BenchmarkProblem:
    return BenchmarkProblem(id="custom_statement", prompt=statement.strip())


def _request_for_statement(
    statement: str,
    *,
    problem_id: str | None = None,
    formal_statement: str | None = None,
    draft_catalog: DraftCatalog | None = None,
    proof_flow_retriever: ProofFlowRetriever | None = None,
) -> ProofRequest:
    normalized = statement.strip()
    formal = formal_statement.strip() if formal_statement else None
    if proof_flow_retriever is not None:
        retrieval = proof_flow_retriever.retrieve(normalized)
        return ProofRequest(
            id=problem_id or "custom_statement",
            prompt=normalized,
            formal_statement=formal,
            query_openmath_xml=retrieval.query_openmath,
            related_draft_contexts=tuple(
                _related_draft_context(
                    item.candidate.draft,
                    exact_equivalence=item.exact_equivalence,
                )
                for item in retrieval.contexts
            ),
            proof_flow_result=retrieval.as_json(),
            formal_statement_source="user" if formal is not None else None,
        )
    search_result: DraftSearchResult | None = None
    draft = None
    if draft_catalog is not None:
        search_method = getattr(draft_catalog, "search_by_statement", None)
        if callable(search_method):
            search_result = cast(
                SearchableDraftCatalog,
                draft_catalog,
            ).search_by_statement(normalized)
            draft = search_result.draft if search_result is not None else None
        else:
            draft = draft_catalog.find_by_statement(normalized)

    if draft is not None:
        exact_equivalence = (
            search_result.exact_equivalence if search_result is not None else False
        )
        formal_statement_source: FormalStatementSource | None = "user" if formal else None
        return ProofRequest(
            id=draft.id,
            prompt=normalized,
            formal_statement=formal,
            draft=draft,
            query_openmath_xml=(
                search_result.query_openmath_xml if search_result is not None else None
            ),
            vector_score=(
                search_result.vector_score if search_result is not None else None
            ),
            structural_score=(
                search_result.structural_score if search_result is not None else None
            ),
            final_score=(search_result.final_score if search_result is not None else None),
            exact_equivalence=exact_equivalence,
            related_draft_context=(
                _related_draft_context(draft) if not exact_equivalence else None
            ),
            formal_statement_source=formal_statement_source,
        )

    return ProofRequest(
        id=problem_id or "custom_statement",
        prompt=normalized,
        formal_statement=formal,
        formal_statement_source="user" if formal is not None else None,
    )


def _related_draft_context(
    draft: ProofDraft,
    *,
    exact_equivalence: bool = False,
) -> RelatedDraftContext:
    strategy_notes = tuple(
        note
        for sentence in _SENTENCE_BOUNDARY_RE.split(draft.proof_strategy)
        if (
            note := _sanitize_related_context_text(
                sentence,
                forbidden_fragments=(),
            )
        )
        is not None
    )
    sketch_steps = tuple(
        note
        for step in draft.sketch_steps
        if (
            note := _sanitize_related_context_text(
                step,
                forbidden_fragments=(),
            )
        )
        is not None
    )
    return RelatedDraftContext(
        source_draft_id=draft.id,
        strategy_notes=strategy_notes,
        sketch_steps=sketch_steps,
        exact_equivalence=exact_equivalence,
        selected_proof_method=(
            _EXACT_DRAFT_PROOF_METHODS.get(draft.id) if exact_equivalence else None
        ),
    )


def _sanitize_related_context_text(
    text: str,
    *,
    forbidden_fragments: tuple[str, ...],
) -> str | None:
    without_code = _INLINE_CODE_RE.sub("[candidate-specific detail omitted]", text)
    if _TARGET_SPECIFIC_MATH_RE.search(without_code):
        return None
    normalized = " ".join(without_code.split()).strip()
    normalized_for_comparison = normalized.casefold()
    if any(
        " ".join(fragment.split()).casefold() in normalized_for_comparison
        for fragment in forbidden_fragments
    ):
        return None
    return normalized or None
