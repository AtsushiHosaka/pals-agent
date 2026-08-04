from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["info", "warning", "error"]
RepairRoute = Literal["draft", "sketch", "prove"]
RepairRouteAttemptOutcome = Literal[
    "selected",
    "invalid_response",
    "transport_error",
]
FormalStatementSource = Literal["user"]
VerificationHarnessSource = Literal["user"]
SelectedProofMethod = Literal["epsilon_delta"]
DEFAULT_MAX_REPAIR_ATTEMPTS = 12
ProofJobState = Literal[
    "queued",
    "retrieving_context",
    "drafting",
    "sketching",
    "proving",
    "compiling",
    "repairing",
    "verified",
    "failed",
    "canceled",
]


@dataclass(frozen=True, slots=True)
class RepairRouteAttemptEvidence:
    attempt: int
    outcome: RepairRouteAttemptOutcome
    diagnostic_code: str | None
    route: RepairRoute | None


class RepairRouteSelectionError(RuntimeError):
    """Raised when the DSP repair route cannot be selected by the configured LLM."""

    def __init__(
        self,
        message: str,
        *,
        prompt: str = "",
        model: str = "",
        provider: str = "",
        elapsed_ms: int = 0,
        attempt_outputs: tuple[str, ...] = (),
        selector_attempts: tuple[RepairRouteAttemptEvidence, ...] = (),
    ) -> None:
        super().__init__(message)
        self.prompt = prompt
        self.model = model
        self.provider = provider
        self.elapsed_ms = elapsed_ms
        self.attempt_outputs = attempt_outputs
        self.selector_attempts = selector_attempts


@dataclass(frozen=True, slots=True)
class BenchmarkProblem:
    id: str
    prompt: str


@dataclass(frozen=True, slots=True)
class ProofDraft:
    id: str
    matched_prompt: str
    openmath_xml: str
    proof_strategy: str
    sketch_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelatedDraftContext:
    source_draft_id: str
    strategy_notes: tuple[str, ...]
    sketch_steps: tuple[str, ...]
    exact_equivalence: bool = False
    selected_proof_method: SelectedProofMethod | None = None


@dataclass(frozen=True, slots=True)
class ProofRequest:
    id: str
    prompt: str
    formal_statement: str | None = None
    draft: ProofDraft | None = field(default=None, compare=False)
    query_openmath_xml: str | None = field(default=None, compare=False)
    vector_score: float | None = field(default=None, compare=False)
    structural_score: float | None = field(default=None, compare=False)
    final_score: float | None = field(default=None, compare=False)
    exact_equivalence: bool = field(default=False, compare=False)
    related_draft_context: RelatedDraftContext | None = field(
        default=None,
        compare=False,
    )
    related_draft_contexts: tuple[RelatedDraftContext, ...] = field(
        default=(),
        compare=False,
    )
    proof_flow_result: dict[str, Any] | None = field(default=None, compare=False)
    formal_statement_source: FormalStatementSource | None = field(
        default=None,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    message: str
    code: str | None = None
    line: int | None = None
    column: int | None = None
    metadata: dict[str, Any] | None = None

    def to_api(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True, slots=True)
class GeneratedDraft:
    text: str
    model: str
    raw_model_output: str
    prompt: str = ""
    provider: str = ""
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedSketch:
    lean_code: str
    model: str
    raw_model_output: str
    has_gaps: bool = False
    prompt: str = ""
    provider: str = ""
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedProof:
    lean_code: str
    model: str
    raw_model_output: str
    draft: GeneratedDraft | None = None
    sketch: GeneratedSketch | None = None
    prompt: str = ""
    provider: str = ""
    elapsed_ms: int = 0
    stage_diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairRouteDecision:
    route: RepairRoute
    rationale: str
    raw_model_output: str
    prompt: str = ""
    model: str = ""
    provider: str = ""
    elapsed_ms: int = 0
    attempt_outputs: tuple[str, ...] = ()
    selector_attempts: tuple[RepairRouteAttemptEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationFeedback:
    attempt: int
    previous_lean_code: str
    diagnostics: tuple[Diagnostic, ...]
    repair_route: RepairRoute = "draft"
    repair_rationale: str = ""
    previous_draft: GeneratedDraft | None = None
    previous_sketch: GeneratedSketch | None = None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    success: bool
    diagnostics: list[Diagnostic]
    stdout: str
    stderr: str
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class ProofArtifact:
    uri: str
    lean_uri: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProofRunResult:
    proof_job_id: str | None
    problem_id: str | None
    prompt: str
    generated: GeneratedProof
    model_attempt: GeneratedProof
    model_attempt_verification: VerificationResult | None
    verification: VerificationResult
    artifact: ProofArtifact
    verification_pending: bool = False

    @property
    def state(self) -> ProofJobState:
        if self.verification_pending:
            return "compiling"
        return "verified" if self.verification.success else "failed"

    @property
    def model_attempt_success(self) -> bool:
        return (
            self.model_attempt_verification is not None
            and self.model_attempt_verification.success
        )
