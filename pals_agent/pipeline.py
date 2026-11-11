from __future__ import annotations

import contextlib
import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import asdict, dataclass, replace
from typing import Any, Final, Literal, Protocol, cast

from pals_agent import quality_events, step_timing, t2_lane
from pals_agent.artifacts import (
    ATTEMPT_CHECKPOINT_SCHEMA_VERSION,
    ArtifactPersistenceError,
    ArtifactStore,
)
from pals_agent.draft_catalog import DraftCatalog, DraftSearchResult
from pals_agent.explanations import target_matches_statement
from pals_agent.lean_profiles import LibraryProfileNotEnabled, ProfileRoutedVerifier
from pals_agent.lean_source_policy import (
    strip_lean_comments_and_strings as _strip_lean_comments_and_strings,
)
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.lean_templates import template_proof_for_request, template_proof_for_sketch
from pals_agent.lemma_repair import (
    LemmaAliasTable,
    LemmaRepairRun,
    default_lemma_alias_table,
    patch_unknown_lemmas,
    repair_metadata,
    repair_unknown_lemmas,
    statement_fingerprint,
)
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
    RepairRouteAttemptEvidence,
    RepairRouteDecision,
    RepairRouteSelectionError,
    VerificationHarnessSource,
    VerificationResult,
)
from pals_agent.natural_draft_evidence import NaturalDraftRetrievalResult
from pals_agent.proof_fastpaths import (
    _HARNESS_MISMATCH_CODE,
    _MODEL_DECIDES_CODES,
    deterministic_repair_route,
    splice_formal_harness,
)
from pals_agent.proof_flow_evidence import DraftEvidence
from pals_agent.proof_flow_runtime import DraftRetrievalResult
from pals_agent.runtime_latency import latency_stage
from pals_agent.sketch_repair import repair_sketch

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
_LEMMA_REPAIR_ID = "pals-lemma-alias-v1"
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
    "repair_stopped_repeated_statement_mismatch",
    "non_repairable_failure",
    "repair_generator_unavailable",
    "repair_route_selection_failed",
    "artifact_store_failure",
]
# Stable names of the early stop. The reason is a termination reason in the artifact; the code
# is the diagnostic that records it. Neither carries a statistic, a statement or Lean text.
EARLY_STOP_REASON: Final = "repair_stopped_repeated_statement_mismatch"
EARLY_STOP_DIAGNOSTIC_CODE: Final = "pals.repair_stopped_repeated_statement_mismatch"
EARLY_STOP_RULE: Final = "repeated_statement_mismatch"


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
    def retrieve(
        self, natural_statement: str
    ) -> DraftRetrievalResult | NaturalDraftRetrievalResult: ...


@dataclass(frozen=True, slots=True)
class _RacedCandidate:
    generated: GeneratedProof
    verification: VerificationResult | None
    # Compile-free race (API reconciliation): how many preflight errors the candidate has.
    # ``None`` means the candidate was cancelled before it was checked.
    preflight_errors: int | None = None


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
    repair_route: dict[str, Any] | None = None
    # Oldest first, excluding this seed's current failure. Populated only after
    # the worker validates the API's candidate-bound consecutive history.
    prior_failure_fingerprints: tuple[frozenset[str], ...] = ()


@dataclass(frozen=True, slots=True)
class ProofPipeline:
    generator: GeneratorPort
    verifier: Verifier | None
    artifact_store: ArtifactStore
    draft_catalog: DraftCatalog | None = None
    proof_flow_retriever: ProofFlowRetriever | None = None
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS
    verification_mode: Literal["local", "api_reconcile"] = "local"
    natural_draft_retriever: ProofFlowRetriever | None = None
    request_linked_typed_retriever: ProofFlowRetriever | None = None
    # Local mode only. Absent, a request can only be verified by ``verifier`` (the default profile).
    profile_verifiers: ProfileRoutedVerifier | None = None
    # Opt-in latency shortcuts, both off by default; see pals_agent/proof_fastpaths.py.
    # ``harness_splice`` restores a fixed formal statement the model re-typed with only
    # layout differences instead of paying for a model-driven restart.
    harness_splice: bool = False
    # ``deterministic_repair_route`` skips the route-selection model call when the user
    # fixed the statement, and never restarts the prose Draft for a statement mismatch.
    deterministic_repair_route: bool = False
    # ``sketch_failure_proceeds_to_prove`` keeps a Sketch that fails its Lean check inside
    # the same attempt: Prove receives the Sketch and its diagnostics at once, instead of
    # the attempt failing, consuming a repair, and the next attempt resuming at Prove.
    sketch_failure_proceeds_to_prove: bool = False
    # ``sketch_mechanical_repair`` repairs a Sketch that failed its Lean check without a model:
    # focused imports become ``import Mathlib``, scoped notation gets its ``open``, and failing
    # proof blocks become ``sorry`` gaps (pals_agent/sketch_repair.py). The repaired Sketch is
    # re-checked by Lean before Prove sees it; a failure keeps the existing path.
    sketch_mechanical_repair: bool = False
    # ``sketch_parallel`` > 1 asks for that many Sketches at once and keeps the first one that
    # passes its Lean check (or the first to finish when none does). It costs the extra Sketch
    # tokens and, on the same wall clock, raises the chance that one Sketch is usable.
    sketch_parallel: int = 1
    # ``stop_on_repeated_harness_mismatch`` ends a run whose last two attempts both failed only
    # with ``lean.formal_harness_mismatch``. ``stop_on_repeated_statement_mismatch`` widens the
    # same rule to ``lean.statement_mismatch`` (mixed pairs count) and subsumes the first when
    # both are on. A stop ends the run with the dedicated ``EARLY_STOP_REASON`` and
    # ``EARLY_STOP_DIAGNOSTIC_CODE`` (never ``repair_budget_exhausted``, which means the whole
    # budget was used). Both flags are off by default.
    stop_on_repeated_harness_mismatch: bool = False
    stop_on_repeated_statement_mismatch: bool = False
    # ``observe_repeated_statement_mismatch`` evaluates the widened rule but never stops: it only
    # emits a ``repair_early_stop`` quality event (mode ``observed``) and the run goes on. Joined
    # with the job's final outcome by ``request_hash``, it counts the runs a stop would have
    # wrongly ended (those that still verified). Ignored where a stop flag already fires.
    observe_repeated_statement_mismatch: bool = False
    # Consecutive failing attempts the rule needs. The API hands a resumed worker at most the
    # two previous failures, so 3 is the largest window that works in api_reconcile mode.
    repeated_mismatch_window: int = 2
    # First attempts for requests that exactly match a verified template (the continuity of x²)
    # are rendered without a model call. The result is compiled like any candidate; a failure
    # repairs through the model as usual.
    deterministic_templates: bool = False
    # A request-linked first attempt whose wording alone selects such a template does not need the
    # Draft retrieval (three sequential model/API steps) that would only feed a model prompt the
    # template replaces. The template, its compile, the semantic review and the explanation
    # review are unchanged; a request the wording does not select still retrieves.
    template_skips_retrieval: bool = False
    # When Lean reports a name from the lemma-alias table as unknown, the source is patched with
    # the right name and recompiled before any model repair (see pals_agent.lemma_repair). The
    # table defaults to the packaged one.
    lemma_alias_repair: bool = False
    lemma_alias_table: LemmaAliasTable | None = None
    # T2 lane (pals_agent/t2_lane.py; each part has its own default-off environment switch).
    # ``explainer`` is only used by the parallel-explanation switch: an object with the
    # ``LeanProofExplainer.explain`` signature, called beside verification.
    explainer: Any = None
    explanation_language: str = "ja"
    # Used only by PALS_T2_PARALLEL_REVIEW_ENABLED: an object with the
    # ``LeanProofSemanticReviewer.review_proof`` signature.
    reviewer: Any = None
    # Seconds ``_run_request`` waits, after the result is ready, for calls the T2 lane left running
    # (a race loser's model call, an unused Draft). Default 0: the answer must not wait for work
    # nobody uses. The caller then MUST call ``result.background.drain(...)`` after the answer is
    # released and before its usage scope ends; a positive value makes the pipeline wait instead
    # (and delays the answer by up to that long).
    accounting_wait_seconds: float = 0.0

    def __post_init__(self) -> None:
        t2_lane.validate_flags()  # a malformed T2 switch fails here, not mid-job after spend
        if (
            t2_lane.lean_process_slots() > 0
            and self.verifier is not None
            and not isinstance(self.verifier, t2_lane.SlottedVerifier)
        ):
            # Every compile this pipeline makes (final, Sketch check, lemma repair, race) shares
            # the process-wide cap; a pipeline derived with ``replace`` re-wraps a raw verifier.
            object.__setattr__(self, "verifier", t2_lane.SlottedVerifier(self.verifier))
        if self.request_linked_typed_retriever is not None and self.natural_draft_retriever is None:
            raise ValueError("Request-linked typed retrieval must retain the natural Draft route")
        if (
            type(self.max_repair_attempts) is not int
            or not 1 <= self.max_repair_attempts <= 64
        ):
            raise ValueError("max_repair_attempts must be between 1 and 64")
        if (
            type(self.repeated_mismatch_window) is not int
            or not 2 <= self.repeated_mismatch_window <= 3
        ):
            raise ValueError("repeated_mismatch_window must be 2 or 3")
        if self.verification_mode == "local" and self.verifier is None:
            raise ValueError("local verification requires a verifier")
        if self.verification_mode == "api_reconcile" and self.verifier is not None:
            raise ValueError("API reconciliation mode forbids a worker verifier")

    def for_library_profile(self, name: str | None) -> ProofPipeline:
        """This pipeline bound to the verifier of one library profile.

        ``None`` is this pipeline unchanged. A named profile needs local verification with that
        profile served; otherwise ``LibraryProfileNotEnabled`` is raised and nothing is verified
        against the default library instead.
        """
        if name is None:
            return self
        if self.verification_mode != "local" or self.profile_verifiers is None:
            raise LibraryProfileNotEnabled("this pipeline does not route library profiles")
        return replace(
            self, verifier=self.profile_verifiers.verifier_for(name), profile_verifiers=None
        )

    def run_problem(
        self,
        *,
        problem: BenchmarkProblem,
        proof_job_id: str | None = None,
        on_status: StatusCallback | None = None,
        library_profile: str | None = None,
    ) -> ProofRunResult:
        if library_profile is not None:
            return self.for_library_profile(library_profile).run_problem(
                problem=problem, proof_job_id=proof_job_id, on_status=on_status
            )
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
        prepared_request: ProofRequest | None = None,
        request_linked: bool = False,
        library_profile: str | None = None,
        routine: bool = False,
    ) -> ProofRunResult:
        if library_profile is not None:
            return self.for_library_profile(library_profile).run_statement(
                statement=statement,
                formal_statement=formal_statement,
                proof_job_id=proof_job_id,
                on_status=on_status,
                api_repair_seed=api_repair_seed,
                prepared_request=prepared_request,
                request_linked=request_linked,
                routine=routine,
            )
        if prepared_request is not None:
            request = prepared_request
        elif request_linked:
            if self.natural_draft_retriever is None:
                from pals_agent.proof_flow_runtime import ProofFlowRetrievalError

                raise ProofFlowRetrievalError("retrieval_unavailable")
            # API repairs already have the durable generated Draft/Sketch/Lean; never
            # re-query a mutable catalog over that compiler failure and its repair seed.
            retriever = (
                (self.request_linked_typed_retriever or self.natural_draft_retriever)
                if api_repair_seed is None else None
            )
            bare: ProofRequest | None = None
            if (
                retriever is not None
                and self.deterministic_templates
                and self.template_skips_retrieval
            ):
                bare = _request_for_statement(
                    statement, formal_statement=formal_statement, proof_flow_retriever=None,
                )
                # The same function decides the first attempt, so a request it accepts here is
                # rendered from the template there whatever retrieval would have returned.
                if template_proof_for_request(bare) is None:
                    bare = None
            request = bare if bare is not None else _request_for_statement(
                statement, formal_statement=formal_statement, proof_flow_retriever=retriever,
            )
        else:
            request = self.prepare_statement(statement=statement, formal_statement=formal_statement)
        if request.prompt != statement.strip() or request.formal_statement != (
            formal_statement.strip() if formal_statement else None
        ):
            raise ValueError("Prepared proof request does not match the submitted statement")
        if routine and not request.routine:
            request = replace(request, routine=True)  # the assessment's routine signal
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

    def prepare_statement(
        self, *, statement: str, formal_statement: str | None = None
    ) -> ProofRequest:
        """Retrieve once before Recipe selection; model generation consumes this same result."""
        return self._request_for_statement(statement, formal_statement=formal_statement)

    def _run_request(self, **arguments: Any) -> ProofRunResult:
        explain = getattr(self.explainer, "explain", None)
        run_request = cast(ProofRequest, arguments["request"])
        review = _speculative_review_call(self.reviewer, run_request.formal_statement)
        harness = arguments.get("verification_harness")

        def preflight(lean_code: str) -> list[Diagnostic]:
            # The race's candidates are checked exactly as the main loop checks them.
            return validate_generated_lean(
                run_request,
                lean_code,
                verification_harness=harness,
                require_single_target=self.verification_mode == "api_reconcile",
            )

        with (
            step_timing.run_scope(arguments.get("proof_job_id")),
            t2_lane.preflight_scope(preflight),
            t2_lane.t2_run_scope(explain, self.explanation_language, review) as (
                _memo,
                explanation_run,
            ),
        ):
            try:
                result = self._run_request_steps(**arguments)
            except BaseException as exc:
                # Calls this run left running (a race loser, an unused Draft, speculative
                # explanation/review) still bill: discard the speculative ones, wait the bounded
                # time, and hand the caller the rest so it can drain before its usage scope ends.
                review_on_error = t2_lane.current_review_run()
                for speculative_run in (explanation_run, review_on_error):
                    if speculative_run is not None and speculative_run.active:
                        speculative_run.finish(verified=False, statement="", lean_code="")
                background = t2_lane.current_background()
                if background is not None:
                    background.drain(self.accounting_wait_seconds)
                    with contextlib.suppress(Exception):
                        exc.t2_background = background  # type: ignore[attr-defined]
                raise
            review_run = t2_lane.current_review_run()
            explanation = review_handle = None
            for run, setter in ((explanation_run, "explanation"), (review_run, "review")):
                if run is None or not run.active:
                    continue
                handle = run.finish(
                    # A candidate waiting for the API's compile is the one to keep: the worker
                    # adopts the handle only when the API accepts exactly this source.
                    verified=result.verification.success or result.verification_pending,
                    statement=result.prompt,
                    lean_code=result.generated.lean_code,
                )
                if setter == "explanation":
                    explanation = handle
                else:
                    review_handle = handle
            background = t2_lane.current_background()
            if background is not None:
                background.drain(self.accounting_wait_seconds)
            return replace(
                result,
                speculative_explanation=explanation,
                speculative_review=review_handle,
                background=background,
            )

    def _run_request_steps(
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
        pending_lemma_note: dict[str, Any] | None = None

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
            # Retain the API-owned selector receipt for this already-generated
            # attempt. A later failed attempt cannot be represented as attempt one.
            attempts[0]["repair_route"] = api_repair_seed.repair_route
            failure_fingerprint_history = list(api_repair_seed.prior_failure_fingerprints)
            repair_feedback_diagnostics = _with_repair_stagnation(
                list(api_repair_seed.verification.diagnostics),
                failure_fingerprint_history,
            )
            generated = api_repair_seed.generated
            model_attempt = generated
            model_attempt_verification = api_repair_seed.verification
            lemma_repair = self._lemma_repair_after_api_failure(
                request=request,
                seed=api_repair_seed,
                verification_harness=verification_harness,
                problem_id=problem_id,
                cumulative_diagnostics=diagnostics,
                attempt_evidence=attempts[-1],
                on_status=on_status,
            )
            repair_generation: RepairGeneration | None
            if lemma_repair is not None:
                repair_generation, pending_lemma_note = lemma_repair
            else:
                repair_generation = self._repair_after_failure(
                    request=request,
                    generated=generated,
                    feedback_diagnostics=repair_feedback_diagnostics,
                    cumulative_diagnostics=diagnostics,
                    problem_id=problem_id,
                    attempt=api_repair_seed.attempt,
                    repairs_used=api_repair_seed.repairs_used,
                    attempt_evidence=attempts[-1],
                    failure_history=failure_fingerprint_history,
                    proof_job_id=proof_job_id,
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
                require_single_target=self.verification_mode == "api_reconcile",
            )
            preflight_diagnostics = _attribute_empty_generation(
                preflight_diagnostics, generation_diagnostic
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
                pending_lemma_note = _annotate_lemma_repair(attempts[-1], pending_lemma_note)
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
                    failure_history=failure_fingerprint_history,
                    proof_job_id=proof_job_id,
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
                # The API compiles this candidate from here on. Its explanation and semantic
                # review do not depend on that compile, so they start now; the worker adopts
                # them only if the API then accepts exactly this source (a start is deduplicated
                # per source, and ``_run_request`` drops the rest).
                for speculative_run in (
                    t2_lane.current_explanation_run(),
                    t2_lane.current_review_run(),
                ):
                    if speculative_run is not None:
                        speculative_run.start(
                            statement=request.prompt, lean_code=generated.lean_code
                        )
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
                pending_lemma_note = _annotate_lemma_repair(attempts[-1], pending_lemma_note)
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
            step_timing.set_attempt(attempt)
            for speculative_run in (
                t2_lane.current_explanation_run(),
                t2_lane.current_review_run(),
            ):
                if speculative_run is not None:
                    speculative_run.start(
                        statement=request.prompt, lean_code=generated.lean_code
                    )
            # A racing first attempt was already compiled (timed as lean_check) by its own thread.
            memoised = t2_lane.take_memoised(generated.lean_code)
            if memoised is not None:
                verification = memoised
            else:
                with (
                    latency_stage("lean_compile_local"),
                    step_timing.step("lean_check") as timing,
                ):
                    verification = verifier.verify(generated.lean_code)
                    if timing is not None:
                        timing.set_lean(verification.success, verification.diagnostics)
            diagnostics = [*diagnostics, *verification.diagnostics]
            if not verification.success and self.lemma_alias_repair:
                lemma_run = self._lemma_repair_in_attempt(
                    request=request,
                    lean_code=generated.lean_code,
                    verification=verification,
                    verification_harness=verification_harness,
                    verifier=verifier,
                    problem_id=problem_id,
                    attempt=attempt,
                    diagnostics=diagnostics,
                    on_status=on_status,
                )
                if lemma_run is not None:
                    # The model's own result stays the first attempt's verdict; the patched source
                    # is what this attempt now stands for, and a failure repairs from it.
                    if model_attempt_verification is None:
                        model_attempt_verification = verification
                    for lemma_round in lemma_run.rounds:
                        diagnostics.extend(lemma_round.verification.diagnostics)
                    generated = replace(generated, lean_code=lemma_run.lean_code)
                    verification = lemma_run.verification
                    pending_lemma_note = repair_metadata(lemma_run)
            attempts.append(
                _attempt_metadata(
                    attempt=attempt,
                    phase="compile",
                    generated=generated,
                    verification=verification,
                    repair_route_decision=current_repair_route,
                )
            )
            pending_lemma_note = _annotate_lemma_repair(attempts[-1], pending_lemma_note)
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
                failure_history=failure_fingerprint_history,
                proof_job_id=proof_job_id,
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
        step_timing.set_attempt(attempt)
        generated = self._generate_attempt_unspliced(
            request=request,
            problem_id=problem_id,
            attempt=attempt,
            repairs_used=repairs_used,
            diagnostics=diagnostics,
            feedback=feedback,
            on_status=on_status,
        )
        if not self.harness_splice or not request.formal_statement:
            return generated
        if not generated.lean_code.strip() or _validate_formal_harness(
            formal_statement=request.formal_statement,
            lean_code=generated.lean_code,
        ) == []:
            return generated
        spliced = splice_formal_harness(generated.lean_code, request.formal_statement)
        if spliced is None or _validate_formal_harness(
            formal_statement=request.formal_statement,
            lean_code=spliced,
        ):
            return generated
        return replace(generated, lean_code=spliced)

    def _generate_attempt_unspliced(
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

        if feedback is None and self.deterministic_templates:
            template = template_proof_for_request(request)
            if template is not None:
                _emit(
                    on_status,
                    "proving",
                    diagnostics,
                    None,
                    None,
                    {
                        **context,
                        "dsp_stage": "prove",
                        "deterministic_template": template.prover_id,
                    },
                )
                return GeneratedProof(
                    lean_code=template.lean_code,
                    model=template.prover_id,
                    raw_model_output=f"[template] {template.prover_id}",
                    provider="pals-template",
                )

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
                sketch_failure_proceeds_to_prove=self.sketch_failure_proceeds_to_prove,
                sketch_mechanical_repair=self.sketch_mechanical_repair,
                sketch_parallel=self.sketch_parallel,
                deterministic_templates=self.deterministic_templates,
                race=(
                    (lambda prove_once: self._race_first_attempt(request, prove_once))
                    if feedback is None
                    and t2_lane.parallel_candidates_enabled()
                    and (
                        (self.verification_mode == "local" and self.verifier is not None)
                        or self.verification_mode == "api_reconcile"
                    )
                    else None
                ),
                draft_beside_proof=self.verification_mode == "local",
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

    def _early_stop_or_observe(
        self,
        history: list[frozenset[str]],
        *,
        cumulative_diagnostics: list[Diagnostic],
        proof_job_id: str | None,
        attempt: int,
        repairs_used: int,
    ) -> bool:
        """True when the run must end here because of a repeated statement mismatch.

        Called only while repair budget remains, so a stop never replaces the budget reason.
        In observe mode the rule only emits an event and the run goes on.
        """
        stop_codes = None
        if self.stop_on_repeated_statement_mismatch:
            stop_codes = _repeated_mismatch_codes(
                history, _STATEMENT_MISMATCH_CODES, self.repeated_mismatch_window
            )
        elif self.stop_on_repeated_harness_mismatch:
            stop_codes = _repeated_mismatch_codes(
                history, _HARNESS_MISMATCH_CODES, self.repeated_mismatch_window
            )
        observed_codes = None
        if stop_codes is None and self.observe_repeated_statement_mismatch:
            observed_codes = _repeated_mismatch_codes(
                history, _STATEMENT_MISMATCH_CODES, self.repeated_mismatch_window
            )
            # Only the first match counts: a stop would have ended the job there, so a longer
            # streak must not be counted once per extra failure. A resumed worker sees at most
            # three failures, so for window 3 a streak past four can repeat; consumers keep the
            # first event per ``request_hash``.
            if observed_codes is not None and _repeated_mismatch_codes(
                history[:-1], _STATEMENT_MISMATCH_CODES, self.repeated_mismatch_window
            ) is not None:
                observed_codes = None
        codes = stop_codes or observed_codes
        if codes is None:
            return False
        stopped = stop_codes is not None
        if quality_events.enabled():
            quality_events.record_repair_early_stop(
                mode="stopped" if stopped else "observed",
                codes=sorted(codes),
                window=self.repeated_mismatch_window,
                attempts=attempt,
                repairs_used=repairs_used,
                repairs_remaining=self.max_repair_attempts - repairs_used,
                request_id=proof_job_id,
            )
        if stopped:
            cumulative_diagnostics.append(
                Diagnostic(
                    severity="error",
                    code=EARLY_STOP_DIAGNOSTIC_CODE,
                    message=(
                        "Lean repair stopped early: each of the last "
                        f"{self.repeated_mismatch_window} attempts failed only on the fixed "
                        "formal statement check ("
                        + ", ".join(sorted(codes))
                        + ")."
                    ),
                )
            )
        return stopped

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
        failure_history: list[frozenset[str]] | None = None,
        proof_job_id: str | None = None,
    ) -> RepairGeneration | None:
        if any(
            diagnostic.code in _NON_REPAIRABLE_DIAGNOSTIC_CODES
            for diagnostic in feedback_diagnostics
        ):
            return None
        step_timing.set_attempt(attempt + 1)  # the repair generates the next attempt
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
        if self._early_stop_or_observe(
            failure_history or [],
            cumulative_diagnostics=cumulative_diagnostics,
            proof_job_id=proof_job_id,
            attempt=attempt,
            repairs_used=repairs_used,
        ):
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
        alternate = self._try_alternate_candidate(
            request=request,
            feedback=base_feedback,
            cumulative_diagnostics=cumulative_diagnostics,
            problem_id=problem_id,
            attempt=attempt,
            repairs_used=repairs_used,
            attempt_evidence=attempt_evidence,
            on_status=on_status,
        )
        if alternate is not None:
            return alternate
        if t2_lane.patch_repair_enabled():
            patched = self._try_patch_repair(
                request=request,
                feedback=base_feedback,
                cumulative_diagnostics=cumulative_diagnostics,
                problem_id=problem_id,
                attempt=attempt,
                repairs_used=repairs_used,
                attempt_evidence=attempt_evidence,
                on_status=on_status,
            )
            if patched is not None:
                return patched
        try:
            route_decision = (
                deterministic_repair_route(request, base_feedback)
                if self.deterministic_repair_route
                else None
            ) or _select_repair_route(
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

    def _try_alternate_candidate(
        self,
        *,
        request: ProofRequest,
        feedback: GenerationFeedback,
        cumulative_diagnostics: list[Diagnostic],
        problem_id: str,
        attempt: int,
        repairs_used: int,
        attempt_evidence: dict[str, Any],
        on_status: StatusCallback | None,
    ) -> RepairGeneration | None:
        """T2 heterogeneous race: the other candidate of the first attempt, instead of a repair.

        The API compile of the submitted candidate failed. The race kept the candidate that did
        not win (it passed the same preflight); submitting it is the next attempt, counted as one
        repair exactly like a model repair, with no model call. Only for a plain compile failure
        and only once per delivery; a source identical to the failed one, a still-running call that
        misses the wait, or no alternate falls through to the ordinary repair.
        """
        slot = t2_lane.repair_alternate()
        if slot is None or not feedback.previous_lean_code.strip():
            return None
        codes = {d.code for d in feedback.diagnostics if d.severity == "error" and d.code}
        if (
            codes & _MODEL_DECIDES_CODES
            or _HARNESS_MISMATCH_CODE in codes
            or any(code.startswith("pals.") for code in codes)
        ):
            return None
        started = time.monotonic()
        held = slot.take(t2_lane.ALTERNATE_WAIT_SECONDS)
        if (
            held is None
            or not held.lean_code.strip()
            or held.lean_code == feedback.previous_lean_code
        ):
            return None
        _emit(
            on_status,
            "repairing",
            cumulative_diagnostics,
            None,
            feedback.previous_lean_code,
            {
                **_request_context(request, problem_id=problem_id),
                "failed_attempt": attempt,
                "repair_attempt": repairs_used + 1,
                "repair_route": "prove",
                "t2_alternate_candidate": True,
                "attempt_evidence": attempt_evidence,
                "max_repair_attempts": self.max_repair_attempts,
            },
        )
        decision = RepairRouteDecision(
            route="prove",
            rationale="T2 heterogeneous race: the held second candidate.",
            raw_model_output="",
            model=held.model,
            provider="pals-t2-alternate",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return RepairGeneration(generated=held, route_decision=decision)

    def _try_patch_repair(
        self,
        *,
        request: ProofRequest,
        feedback: GenerationFeedback,
        cumulative_diagnostics: list[Diagnostic],
        problem_id: str,
        attempt: int,
        repairs_used: int,
        attempt_evidence: dict[str, Any],
        on_status: StatusCallback | None,
    ) -> RepairGeneration | None:
        """T2: a minimal edit of the failed source, without route selection or a handoff call.

        Used for the first ``PATCH_REPAIR_MAX_ROUNDS`` repairs of plain Lean failures only.
        Anything the model would have to route (statement/harness mismatches, preflight
        failures, repeated failures) and any patch that cannot be applied goes through the
        ordinary repair path, so this changes how fast a repair is made, not whether one is.
        """
        patcher = getattr(self.generator, "generate_patch", None)
        if (
            not callable(patcher)
            or repairs_used >= t2_lane.PATCH_REPAIR_MAX_ROUNDS
            or not feedback.previous_lean_code.strip()
        ):
            return None
        errors = [d for d in feedback.diagnostics if d.severity == "error"]
        codes = {d.code for d in errors if d.code}
        if (
            not errors
            or codes & _MODEL_DECIDES_CODES
            or _HARNESS_MISMATCH_CODE in codes
            or any(code.startswith("pals.") for code in codes)
        ):
            return None
        _emit(
            on_status,
            "repairing",
            cumulative_diagnostics,
            None,
            feedback.previous_lean_code,
            {
                **_request_context(request, problem_id=problem_id),
                "failed_attempt": attempt,
                "repair_attempt": repairs_used + 1,
                "repair_route": "prove",
                "t2_patch_repair": True,
                "attempt_evidence": attempt_evidence,
                "max_repair_attempts": self.max_repair_attempts,
            },
        )
        patched = patcher(request, feedback)
        if patched is None or not patched.lean_code.strip():
            return None
        decision = RepairRouteDecision(
            route="prove",
            rationale="T2 patch repair from a sanitised failure summary.",
            raw_model_output="",
            model=patched.model,
            provider="pals-t2-patch",
            elapsed_ms=patched.elapsed_ms,
        )
        return RepairGeneration(generated=patched, route_decision=decision)

    def _race_first_attempt(
        self, request: ProofRequest, prove_once: Callable[[], GeneratedProof]
    ) -> GeneratedProof:
        """T2: ``CANDIDATE_COUNT`` first-attempt proofs generated and compiled concurrently.

        The first candidate that passes preflight and Lean wins; the others are cancelled before
        they compile (a model call already sent still bills, and is counted by the race). Its Lean
        result is memoised so the main loop does not compile it again. When nobody compiles, the
        candidate with the fewest errors is returned and repaired as an ordinary failure.
        """
        verifier = self.verifier
        memo = t2_lane.current_memo()
        preflight = t2_lane.current_preflight() or (
            lambda lean_code: validate_generated_lean(request, lean_code)
        )
        if verifier is None:
            return self._race_without_compile(request, prove_once, preflight)
        # Lean capacity for racing compiles. A candidate takes a slot, then checks the cancel
        # event *after* acquiring it: a loser that was queued behind the winner never compiles.
        slots = threading.BoundedSemaphore(t2_lane.lean_slots())

        def task(cancel: threading.Event) -> _RacedCandidate:
            generated = prove_once()
            code = generated.lean_code
            if not code.strip() or preflight(code) or cancel.is_set():
                return _RacedCandidate(generated, None)
            with slots:
                if cancel.is_set():
                    return _RacedCandidate(generated, None)
                # Only a candidate that has entered Lean starts its explanation and review: one
                # queued behind the winner and cancelled never costs a call.
                for speculative_run in (
                    t2_lane.current_explanation_run(),
                    t2_lane.current_review_run(),
                ):
                    if speculative_run is not None:
                        speculative_run.start(statement=request.prompt, lean_code=code)
                with step_timing.step("lean_check") as timing:
                    verification = verifier.verify(code)
                    if timing is not None:
                        timing.set_lean(verification.success, verification.diagnostics)
                if verification.success:
                    # Decided while still holding the slot, so a queued loser sees the cancel.
                    cancel.set()
            if memo is not None:
                memo.put(code, verification)
            return _RacedCandidate(generated, verification)

        def rank(value: _RacedCandidate) -> float:
            if value.verification is None:
                return 1_000.0
            return float(sum(d.severity == "error" for d in value.verification.diagnostics))

        result = t2_lane.race_candidates(
            [task] * t2_lane.CANDIDATE_COUNT,
            is_win=lambda value: value.verification is not None and value.verification.success,
            rank=rank,
        )
        if result.best is None:
            errors = [c.error for c in result.candidates if c.error is not None]
            raise errors[0] if errors else RuntimeError("no first-attempt candidate finished")
        assert result.best.value is not None
        return result.best.value.generated

    def _race_without_compile(
        self,
        request: ProofRequest,
        prove_once: Callable[[], GeneratedProof],
        preflight: Callable[[str], list[Diagnostic]],
    ) -> GeneratedProof:
        """T2 under API reconciliation: ``CANDIDATE_COUNT`` proofs generated at once, the first
        that passes the worker's own preflight (statement/target checks) is the one submitted.

        This process has no Lean, so a candidate is never ranked by a compile and the second one
        cannot raise the chance the compile passes: what the race buys is the faster of two model
        calls and a second chance at a preflight failure (which would otherwise cost a model
        repair). A loser's model call is already billed; it is tracked by the run's background
        set and its usage is forwarded when it ends. Raising the pass rate needs the API to
        compile an alternate candidate (docs/t2-lane-followups.md).
        """
        decided = threading.Lock()
        claimed = False
        background = t2_lane.current_background()
        slot: t2_lane.AlternateSlot | None = None
        if t2_lane.hetero_race_enabled() and background is not None:
            # The candidate that does not win is kept: a failed API compile submits it instead of
            # asking the model for a repair.
            slot = background.alternate = t2_lane.AlternateSlot(t2_lane.CANDIDATE_COUNT)

        def task(cancel: threading.Event) -> _RacedCandidate:
            nonlocal claimed
            try:
                generated = prove_once()
                code = generated.lean_code
                if not code.strip():
                    return _RacedCandidate(generated, None, preflight_errors=1_000)
                errors = sum(d.severity == "error" for d in preflight(code))
                if errors == 0 and not _aligned_with_request(request.prompt, code):
                    # A statement the worker would reject after the API compile (for example
                    # `True` for an x²-continuity request) is a loser, so a correct rival can
                    # still win.
                    errors = 1
                if errors == 0:
                    with decided:
                        if claimed or cancel.is_set():
                            if slot is not None:
                                slot.offer(generated)
                            return _RacedCandidate(generated, None, preflight_errors=0)
                        claimed = True
                        cancel.set()
                return _RacedCandidate(generated, None, preflight_errors=errors)
            finally:
                if slot is not None:
                    slot.finished_one()

        result = t2_lane.race_candidates(
            [task] * t2_lane.CANDIDATE_COUNT,
            is_win=lambda value: value.preflight_errors == 0,
            rank=lambda value: float(value.preflight_errors or 0),
        )
        if result.best is None:
            errors_raised = [c.error for c in result.candidates if c.error is not None]
            raise errors_raised[0] if errors_raised else RuntimeError("no candidate finished")
        assert result.best.value is not None
        return result.best.value.generated

    def _lemma_alias_table(self) -> LemmaAliasTable:
        return self.lemma_alias_table or default_lemma_alias_table()

    def _lemma_repair_in_attempt(
        self,
        *,
        request: ProofRequest,
        lean_code: str,
        verification: VerificationResult,
        verification_harness: str | None,
        verifier: Verifier,
        problem_id: str,
        attempt: int,
        diagnostics: list[Diagnostic],
        on_status: StatusCallback | None,
    ) -> LemmaRepairRun | None:
        """Patch known wrong lemma names inside the attempt that just failed to compile.

        A patched source goes through the same preflight and the same verifier as a model-written
        one. It stays within this attempt, so it neither costs a repair nor a new checkpoint.
        """

        def verify(patched: str) -> VerificationResult:
            with latency_stage("lean_compile_local"):
                return verifier.verify(patched)

        def announce(patch: Any) -> None:
            _emit(
                on_status,
                "compiling",
                diagnostics,
                None,
                patch.lean_code,
                {
                    **_request_context(request, problem_id=problem_id),
                    "attempt": attempt,
                    "deterministic_lemma_repair": [
                        {"reported": reported, "replacement": replacement}
                        for reported, replacement in patch.replacements
                    ],
                },
            )

        return repair_unknown_lemmas(
            lean_code,
            verification,
            verify=verify,
            table=self._lemma_alias_table(),
            accept=lambda patched: not validate_generated_lean(
                request, patched, verification_harness=verification_harness
            ),
            same_statement=_statements_unchanged,
            on_round=announce,
        )

    def _lemma_repair_after_api_failure(
        self,
        *,
        request: ProofRequest,
        seed: ApiRepairSeed,
        verification_harness: str | None,
        problem_id: str,
        cumulative_diagnostics: list[Diagnostic],
        attempt_evidence: dict[str, Any],
        on_status: StatusCallback | None,
    ) -> tuple[RepairGeneration, dict[str, Any]] | None:
        """Replace the model repair after an API compile failure by a deterministic patch.

        The API compiles, so the patched source is a new candidate: it takes the next attempt
        number, which the API requires to equal repairs_used + 1, so the API's own budget count
        includes it even though no model runs. One repair slot is always kept for the model.
        """
        if not self.lemma_alias_repair or seed.repairs_used + 1 >= self.max_repair_attempts:
            return None
        patch = patch_unknown_lemmas(
            seed.generated.lean_code,
            seed.verification.diagnostics,
            self._lemma_alias_table(),
            same_statement=_statements_unchanged,
        )
        if patch is None or validate_generated_lean(
            request, patch.lean_code, verification_harness=verification_harness
        ):
            return None
        generated = GeneratedProof(
            lean_code=patch.lean_code,
            model=_LEMMA_REPAIR_ID,
            raw_model_output=f"[deterministic] {_LEMMA_REPAIR_ID}",
            draft=seed.generated.draft,
            sketch=seed.generated.sketch,
            provider="pals-deterministic",
        )
        route = RepairRouteDecision(
            route="prove",
            rationale="Deterministic substitution of a known wrong Mathlib lemma name.",
            raw_model_output="",
            model=_LEMMA_REPAIR_ID,
            provider="pals-deterministic",
            selector_attempts=(
                RepairRouteAttemptEvidence(
                    attempt=1, outcome="selected", diagnostic_code=None, route="prove"
                ),
            ),
        )
        note = {
            "replacements": [
                {"reported": reported, "replacement": replacement}
                for reported, replacement in patch.replacements
            ],
            "rounds": 1,
            "verified": None,
            "original_lean_code": seed.generated.lean_code,
        }
        context = {
            **_request_context(request, problem_id=problem_id),
            "deterministic_lemma_repair": note["replacements"],
            "max_repair_attempts": self.max_repair_attempts,
        }
        _emit(
            on_status,
            "repairing",
            cumulative_diagnostics,
            None,
            seed.generated.lean_code,
            {
                **context,
                "failed_attempt": seed.attempt,
                "repair_attempt": seed.repairs_used + 1,
                "repair_route": route.route,
                "repair_route_rationale": route.rationale,
                "repair_route_model": route.model,
                "repair_route_provider": route.provider,
                "selector_attempts": [asdict(item) for item in route.selector_attempts],
                "attempt_evidence": attempt_evidence,
                "feedback_diagnostics": [
                    diagnostic.to_api() for diagnostic in seed.verification.diagnostics
                ],
            },
        )
        _emit(
            on_status,
            "proving",
            cumulative_diagnostics,
            None,
            None,
            {
                **context,
                "attempt": seed.attempt + 1,
                "repair_attempt": seed.repairs_used + 1,
                "dsp_stage": "prove",
            },
        )
        return RepairGeneration(generated=generated, route_decision=route), note

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
        # A resumed run retains only the API-owned previous attempt plus its new
        # work. Their absolute attempt numbers, not this partial history's length,
        # determine the consumed repair budget and termination receipt.
        latest_attempt = int(attempts[-1]["attempt"])
        repairs_used = max(0, latest_attempt - 1)
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
            attempt=latest_attempt,
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
        if termination_reason == EARLY_STOP_REASON:
            # Counts only: the codes are in the stop diagnostic, never a statement or Lean text.
            metadata["early_stop"] = {
                "rule": EARLY_STOP_RULE,
                "window": self.repeated_mismatch_window,
                "stopped_after_attempt": latest_attempt,
                "repairs_used": repairs_used,
                "repairs_remaining": self.max_repair_attempts - repairs_used,
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
        step_timing.note_run(
            state=result.state, termination_reason=termination_reason,
            attempts=latest_attempt, repairs_used=repairs_used,
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
                "attempts": latest_attempt,
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


def _speculative_review_call(reviewer: Any, formal_statement: str | None) -> Any:
    """The semantic review as an ``explain``-shaped call, for ``SpeculativeExplanation``."""
    review_proof = getattr(reviewer, "review_proof", None)
    if not callable(review_proof):
        return None

    def review(
        *,
        theorem_statement: str,
        lean_code: str,
        verified: bool,
        language: str,
        deadline: float,
        timeout_seconds: float,
    ) -> Any:
        target = extract_single_target_declaration(lean_code)
        if target is None:
            raise ValueError("no single target declaration to review")
        return review_proof(
            theorem_statement=theorem_statement,
            formal_statement=formal_statement,
            target_declaration=target,
            lean_code=lean_code,
            timeout_seconds=timeout_seconds,
        )

    return review


def validate_generated_lean(
    request: ProofRequest,
    lean_code: str,
    *,
    verification_harness: str | None = None,
    allow_theorem_name_variance: bool = False,
    defer_formal_harness: bool = False,
    require_single_target: bool = False,
) -> list[Diagnostic]:
    if not lean_code.strip():
        return [
            Diagnostic(
                severity="error",
                code="pals.generation_empty",
                message="The model did not produce extractable Lean code.",
            )
        ]

    # The worker protocol requires one unambiguous target for independent semantic
    # review. Repair its source shape here, within the existing bounded DSP loop,
    # instead of discovering it only in the worker's final submission guard.
    # Local verifier tooling retains its existing multi-declaration contract.
    if require_single_target and extract_single_target_declaration(lean_code) is None:
        return [Diagnostic(
            severity="error",
            code="pals.target_declaration_invalid",
            message=(
                "API verification requires exactly one parseable top-level theorem, lemma or "
                "example target. Preserve the complete requested claim, assumptions and any "
                "exact supplied harness. Move auxiliary proof declarations into local `have` "
                "statements inside that target, even if the previous Sketch used global helpers. "
                "Do not select one of several conclusions, discard obligations or weaken the "
                "proposition to satisfy this source-shape requirement."
            ),
        )]

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
    sketch_failure_proceeds_to_prove: bool = False,
    sketch_mechanical_repair: bool = False,
    sketch_parallel: int = 1,
    deterministic_templates: bool = False,
    race: Callable[[Callable[[], GeneratedProof]], GeneratedProof] | None = None,
    draft_beside_proof: bool = True,
) -> GeneratedProof:
    draft = feedback.previous_draft if feedback is not None else None
    sketch = feedback.previous_sketch if feedback is not None else None

    direct = getattr(generator, "generate_direct_proof", None)
    if (
        feedback is None
        and callable(direct)
        and t2_lane.no_draft_enabled()
        and not (deterministic_templates and template_proof_for_request(request) is not None)
    ):
        # T2 no-Draft: the proof is written from the request. A routine request never needs a
        # Draft; any other runs it beside the proof and keeps it only to seed a repair.
        # Only where this process compiles: under API reconciliation nothing here learns the
        # compile result, so waiting for a Draft that only a failed attempt would use would put
        # the Draft back on the answer's path. A repair after an API failure writes one then.
        draft_call = (
            None
            if request.routine or not draft_beside_proof
            else t2_lane.BackgroundCall(lambda: generator.generate_draft(request, None))
        )
        _emit(
            on_status,
            "proving",
            diagnostics,
            None,
            None,
            {**context, "dsp_stage": "prove", "t2_no_draft": True, "t2_routine": request.routine},
        )

        direct_proof = cast(Callable[[ProofRequest, None], GeneratedProof], direct)

        def direct_from_request() -> GeneratedProof:
            return direct_proof(request, None)

        proof = race(direct_from_request) if race is not None else direct_from_request()
        verified = t2_lane.peek_memoised(proof.lean_code)
        if draft_call is not None and not (verified is not None and verified.success):
            late_draft = draft_call.value()
            if late_draft is not None and late_draft.text.strip():
                proof = replace(proof, draft=late_draft)
        return proof

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

    direct = getattr(generator, "generate_direct_proof", None)
    if (
        feedback is None
        and callable(direct)
        and t2_lane.no_sketch_enabled()
        and not (deterministic_templates and template_proof_for_request(request) is not None)
    ):
        # T2: the Sketch stage is skipped; one call writes the whole proof from the Draft.
        _emit(
            on_status,
            "proving",
            diagnostics,
            None,
            None,
            {
                **context,
                "dsp_stage": "prove",
                "t2_no_sketch": True,
                "generated_draft": asdict(draft),
                "model": getattr(generator, "prove_model", None)
                or getattr(generator, "model", None),
            },
        )

        def direct_once() -> GeneratedProof:
            return cast(GeneratedProof, direct(request, draft))

        return race(direct_once) if race is not None else direct_once()

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
        sketch, sketch_verification = _sketch_and_check(
            generator,
            request,
            draft,
            feedback,
            verifier,
            mechanical_repair=sketch_mechanical_repair,
            parallel=sketch_parallel,
        )
        if not sketch.lean_code.strip():
            return _failed_staged_proof(draft=draft, sketch=sketch)
        if feedback is None and deterministic_templates:
            # The Sketch's Lean statement is language independent: when it is exactly the
            # continuity of x², the verified template replaces the prove stage.
            template = template_proof_for_sketch(request, sketch.lean_code)
            if template is not None:
                _emit(
                    on_status,
                    "proving",
                    diagnostics,
                    None,
                    None,
                    {
                        **context,
                        "dsp_stage": "prove",
                        "deterministic_template": template.prover_id,
                        "template_source": "sketch_statement",
                    },
                )
                return GeneratedProof(
                    lean_code=template.lean_code,
                    model=template.prover_id,
                    raw_model_output=f"[template] {template.prover_id}",
                    draft=draft,
                    provider="pals-template",
                )
        if (
            sketch.has_gaps
            and sketch_verification is not None
            and not sketch_verification.success
        ):
            if sketch_failure_proceeds_to_prove:
                feedback = GenerationFeedback(
                    attempt=feedback.attempt if feedback is not None else 0,
                    previous_lean_code=sketch.lean_code,
                    diagnostics=tuple(sketch_verification.diagnostics),
                    repair_route="prove",
                    repair_rationale=(
                        "The Sketch failed its Lean check; correct it while completing "
                        "the proof."
                    ),
                    previous_draft=draft,
                    previous_sketch=sketch,
                )
            else:
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

    def prove_once() -> GeneratedProof:
        return generator.generate_proof(request, draft, sketch, feedback)

    if race is not None and feedback is None:
        return race(prove_once)
    return prove_once()


def _sketch_and_check(
    generator: StagedLeanGenerator,
    request: ProofRequest,
    draft: GeneratedDraft,
    feedback: GenerationFeedback | None,
    verifier: Verifier | None,
    *,
    mechanical_repair: bool,
    parallel: int,
) -> tuple[GeneratedSketch, VerificationResult | None]:
    """One Sketch with its Lean check, or the first usable one of ``parallel`` Sketches."""

    def one() -> tuple[GeneratedSketch, VerificationResult | None]:
        sketch = generator.generate_sketch(request, draft, feedback)
        if not sketch.lean_code.strip():
            return sketch, None
        verification = _verify_sketch(verifier, sketch.lean_code)
        if (
            mechanical_repair
            and sketch.has_gaps
            and verification is not None
            and not verification.success
        ):
            repaired = repair_sketch(
                sketch.lean_code,
                verification,
                lambda code: cast(SketchVerifier, verifier).verify_sketch(code),
            )
            if repaired is not None:
                return replace(sketch, lean_code=repaired.lean_code), repaired.verification
        return sketch, verification

    def usable(result: tuple[GeneratedSketch, VerificationResult | None]) -> bool:
        sketch, verification = result
        return bool(sketch.lean_code.strip()) and (
            not sketch.has_gaps or verification is None or verification.success
        )

    if parallel <= 1:
        return one()
    pool = ThreadPoolExecutor(max_workers=parallel)
    try:
        futures = [pool.submit(copy_context().run, one) for _ in range(parallel)]
        finished: list[tuple[GeneratedSketch, VerificationResult | None]] = []
        for future in as_completed(futures):
            result = future.result()
            if usable(result):
                return result
            finished.append(result)
        return next((r for r in finished if r[0].lean_code.strip()), finished[0])
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


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
        reasoning_effort=failed_stage.reasoning_effort,
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
    with step_timing.step("lean_sketch_check") as timing:
        result = cast(SketchVerifier, verifier).verify_sketch(lean_code)
        if timing is not None:
            timing.set_lean(result.success, result.diagnostics)
    return result


def _format_diagnostic_for_trace(diagnostic: Diagnostic) -> str:
    location = f" line {diagnostic.line}" if diagnostic.line is not None else ""
    code = f" [{diagnostic.code}]" if diagnostic.code else ""
    return f"{diagnostic.severity}{location}{code}: {diagnostic.message}"


_HARNESS_MISMATCH_CODES = frozenset({"lean.formal_harness_mismatch"})
_STATEMENT_MISMATCH_CODES = frozenset({"lean.formal_harness_mismatch", "lean.statement_mismatch"})


def _repeated_mismatch_codes(
    history: list[frozenset[str]], allowed_codes: frozenset[str], window: int = 2
) -> frozenset[str] | None:
    """The error codes seen when each of the last ``window`` failures has error codes, all within
    ``allowed_codes``; ``None`` when the run does not match."""
    if window < 2 or len(history) < window:
        return None
    seen: set[str] = set()
    for fingerprints in history[-window:]:
        codes = {fingerprint.split("|", maxsplit=1)[0] for fingerprint in fingerprints}
        if not codes or not codes <= allowed_codes:
            return None
        seen |= codes
    return frozenset(seen)


def _mismatch_repeated(
    history: list[frozenset[str]], allowed_codes: frozenset[str], window: int = 2
) -> bool:
    return _repeated_mismatch_codes(history, allowed_codes, window) is not None


def _harness_mismatch_repeated(history: list[frozenset[str]]) -> bool:
    """True when each of the last two failures had exactly the harness-mismatch error."""
    return _mismatch_repeated(history, _HARNESS_MISMATCH_CODES)


def _statement_mismatch_repeated(history: list[frozenset[str]]) -> bool:
    """True when each of the last two failures had only harness- or statement-mismatch errors."""
    return _mismatch_repeated(history, _STATEMENT_MISMATCH_CODES)


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
            "The same normalized diagnostic signatures appeared in 3 consecutive attempts: "
            + ", ".join(persistent_codes)
            + ". This does not establish that their mathematical causes are identical. "
            "Reconsider whether repair should resume from sketch or draft instead "
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
        and diagnostic.code != "verifier_compile_failed"
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
    if (
        not isinstance(seed.prior_failure_fingerprints, tuple)
        or len(seed.prior_failure_fingerprints) > min(2, seed.attempt - 1)
        or any(
            not isinstance(items, frozenset)
            or len(items) > 8
            or any(not isinstance(item, str) or not 1 <= len(item) <= 512 for item in items)
            for items in seed.prior_failure_fingerprints
        )
    ):
        raise ValueError("API repair seed has invalid prior diagnostic fingerprints")
    if not seed.generated.lean_code.strip():
        raise ValueError("API repair seed requires nonblank prior Lean code")
    if not any(
        diagnostic.code == "verifier_compile_failed"
        and diagnostic.severity == "error"
        for diagnostic in seed.verification.diagnostics
    ):
        raise ValueError("API repair seed requires verifier_compile_failed evidence")


def _aligned_with_request(statement: str, lean_code: str) -> bool:
    """The deterministic target check the worker applies before it submits a candidate."""
    target = extract_single_target_declaration(lean_code)
    return target is not None and target_matches_statement(statement, target)


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


def _annotate_lemma_repair(
    attempt: dict[str, Any],
    note: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Record a deterministic lemma repair on the attempt it produced; the note is spent."""
    if note is not None:
        attempt["deterministic_lemma_repair"] = note
    return None


def _statements_unchanged(before: str, after: str) -> bool:
    """A lemma-name patch may not move any theorem statement."""
    return _theorem_type_signatures(
        _normalize_lean_text(_strip_lean_comments(before))
    ) == _theorem_type_signatures(
        _normalize_lean_text(_strip_lean_comments(after))
    ) and statement_fingerprint(before) == statement_fingerprint(after)


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
    if EARLY_STOP_DIAGNOSTIC_CODE in codes:
        return EARLY_STOP_REASON
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
        EARLY_STOP_REASON: "repair_early_stop",
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


def _attribute_empty_generation(
    preflight: list[Diagnostic], generation: Diagnostic
) -> list[Diagnostic]:
    """Say why `pals.generation_empty` fired, keeping its code for existing consumers.

    No Lean code reaches preflight whenever a stage fails (a provider error, a Sketch that
    does not compile, a Prove that still has `sorry`), not only when the model returns
    nothing. In 129 measured attempts none was a model that returned nothing, so counting the
    bare code overstates empty generations. `explained_by` is the stage diagnostic code, or
    "none" when the model really produced no extractable Lean code.
    """
    cause = generation.code if generation.severity == "error" and generation.code else "none"
    return [
        replace(item, metadata={**(item.metadata or {}), "explained_by": cause})
        if item.code == "pals.generation_empty"
        else item
        for item in preflight
    ]


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
        with latency_stage("context_retrieval"):
            retrieval = proof_flow_retriever.retrieve(normalized)
        return ProofRequest(
            id=problem_id or "custom_statement",
            prompt=normalized,
            formal_statement=formal,
            query_openmath_xml=retrieval.query_openmath,
            related_draft_contexts=tuple(
                _related_draft_context(
                    item.candidate.draft,
                    exact_equivalence=(item.exact_equivalence if isinstance(item, DraftEvidence)
                                       else False),
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
