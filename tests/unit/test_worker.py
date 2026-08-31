from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
import rfc8785

from pals_agent.api_client import VerifierAttestation
from pals_agent.explanations import ProofSemanticReview
from pals_agent.lean_target import (
    LeanTargetDeclaration,
    extract_single_target_declaration,
)
from pals_agent.models import Diagnostic, ProofJobState
from pals_agent.openmath import OpenMathStructuringError
from pals_agent.pipeline import ApiRepairSeed
from pals_agent.private_recipe_selection import (
    RecipeNotSelected,
    RecipeSelected,
    ToolchainFingerprintV1,
)
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError
from pals_agent.recipe_attempt import RecipeAttemptPlannerV1
from pals_agent.settings import AgentSettings
from pals_agent.worker import (
    SqsProofWorker,
    _api_repair_seed_from_worker_input,
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


class _RecipeSelector:
    def __init__(self) -> None:
        self.calls = 0

    def select(self, query: object) -> RecipeSelected:
        del query
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
        return RecipeNotSelected(exclusions=())


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

    def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
        return {
            "id": proof_job_id,
            "state": "semantic_review",
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
    assert [item.code for item in seed.verification.diagnostics] == ["verifier_compile_failed"]


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


def test_recipe_semantic_review_uses_the_closed_v3_evidence_without_llm_provenance() -> None:
    class RecipeSemanticReviewApi:
        def __init__(self) -> None:
            self.evidence: list[dict[str, Any]] = []

        def get_proof_job(self, proof_job_id: str) -> dict[str, Any]:
            return {
                "id": proof_job_id,
                "state": "semantic_review",
                "attempt_source": "recipe",
                "chat_id": "chat-1",
                "output_language": "en",
                "theorem_statement": "Show that True.",
                "request_context": {"formal_statement": "example : True := by trivial"},
                "lean_code": _RECIPE_SOURCE,
                "status_context": {
                    "target_declaration": {
                        "kind": "example",
                        "name": None,
                        "proposition": "True",
                    }
                },
                "verification_candidate_id": "22222222-2222-4222-8222-222222222222",
                "source_binding_sha256": "f" * 64,
            }

        def settle_recipe_semantic_review(
            self,
            *,
            proof_job_id: str,
            evidence: dict[str, Any],
        ) -> dict[str, Any]:
            self.evidence.append(evidence)
            return {"id": proof_job_id, "state": "failed"}

    api = RecipeSemanticReviewApi()
    reviewer = RecordingSemanticReviewer(reject=True)
    worker = SqsProofWorker(
        settings=cast(
            AgentSettings,
            SimpleNamespace(explanation_model_timeout_seconds=17),
        ),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=ExplainerThatMustNotRun(),
        proof_reviewer=reviewer,
    )

    assert worker.process_proof_job("job-recipe-semantic") is True
    evidence = api.evidence[0]
    assert set(evidence) == {
        "schema_version",
        "candidate_id",
        "lean_sha256",
        "target_declaration",
        "review_input_sha256",
        "decision",
        "rationale",
    }
    assert evidence["schema_version"] == "pals.proof-semantic-review.v3"
    assert evidence["lean_sha256"] == hashlib.sha256(_RECIPE_SOURCE.encode("utf-8")).hexdigest()
    assert evidence["target_declaration"] == {
        "kind": "example",
        "name": None,
        "proposition": "True",
    }
    assert len(reviewer.calls) == 1
    assert reviewer.calls[0]["lean_code"] == _RECIPE_SOURCE
    assert not {"generator_session_id", "reviewer", "model", "source_binding_sha256"} & set(
        evidence
    )


@pytest.mark.parametrize(
    "proof_reviewer",
    [None, RaisingSemanticReviewer()],
    ids=["unavailable", "raises"],
)
def test_worker_durably_rejects_when_the_independent_reviewer_is_unavailable(
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
    assert api.evidence[0]["decision"] == "rejected"
    assert api.evidence[0]["rationale"] == ("The independent proof review could not be completed.")
    assert api.evidence[0]["reviewer"] == {
        "provider": "unavailable",
        "model": "independent-proof-review-unavailable",
        "session_id": "44444444-4444-4444-8444-444444444444",
    }


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
    assert api.reconciliation_retries == [
        ("job-pending", "22222222-2222-4222-8222-222222222222")
    ]
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


def test_selected_recipe_submits_exact_bytes_without_constructing_pipeline_or_repair() -> None:
    class RecipeApi:
        def __init__(self) -> None:
            self.recipe_submissions: list[dict[str, Any]] = []
            self.claims = 0

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
                "request_context": {"formal_statement": "example : True := by trivial"},
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
            return {"candidate_status": "compiling"}

    class PipelineThatMustNotRun:
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
    assert api.claims == 1
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
    api = RecordingApi()
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
    assert api.updates[-1]["state"] == "failed"
    assert api.updates[-1]["diagnostics"][0].code == "pals.openmath_structuring_failed"
