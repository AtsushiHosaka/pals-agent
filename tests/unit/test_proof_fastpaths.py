import json
from pathlib import Path

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import ProofPipeline
from pals_agent.proof_fastpaths import (
    DETERMINISTIC_ROUTE_PROVIDER,
    contains_formal_statement_modulo_layout,
    deterministic_repair_route,
    splice_formal_harness,
)

HARNESS = (
    "theorem pals_card_target {K : Type*} [Field K] {n : ℕ} (v : Fin n → K) : "
    "(∃ b : Fin n → K, (fun i => b i)=v) ↔ LinearIndependent K v ∧ n = n"
)
LET_HARNESS = (
    "theorem pals_card_target (f : ℝ → ℝ) : "
    "let p := f 0; let q := f 1; p = p ∧ q = q"
)


# ---------------------------------------------------------------- splice


def test_splice_restores_spacing_difference() -> None:
    code = (
        "import Mathlib\n\n"
        "theorem pals_card_target {K : Type*} [Field K] {n : ℕ} (v : Fin n → K) :\n"
        "    (∃ b : Fin n → K, (fun i => b i) = v) ↔ LinearIndependent K v ∧ n = n := by\n"
        "  simp\n"
    )
    spliced = splice_formal_harness(code, HARNESS)
    assert spliced is not None
    assert HARNESS in spliced
    assert spliced.startswith("import Mathlib\n\ntheorem pals_card_target")
    assert spliced.endswith(" := by\n  simp\n")


def test_splice_treats_semicolon_and_newline_let_separators_alike() -> None:
    code = (
        "theorem pals_card_target (f : ℝ → ℝ) :\n"
        "    let p := f 0\n"
        "    let q := f 1\n"
        "    p = p ∧ q = q := by\n"
        "  intro p q\n  exact ⟨rfl, rfl⟩\n"
    )
    spliced = splice_formal_harness(code, LET_HARNESS)
    assert spliced is not None
    assert LET_HARNESS in spliced
    assert spliced.endswith(" := by\n  intro p q\n  exact ⟨rfl, rfl⟩\n")


def test_splice_ignores_comments_inside_the_statement() -> None:
    code = (
        "theorem pals_card_target (f : ℝ → ℝ) : -- the claim\n"
        "    let p := f 0; let q := f 1; p = p ∧ q = q := by\n  simp\n"
    )
    spliced = splice_formal_harness(code, LET_HARNESS)
    assert spliced is not None
    assert LET_HARNESS in spliced
    assert "the claim" not in spliced


@pytest.mark.parametrize(
    "changed_statement",
    [
        # A different hypothesis, conclusion, binder and theorem name each change a token.
        "theorem pals_card_target (f : ℝ → ℝ) : let p := f 0; let q := f 1; p = p ∧ q = p",
        "theorem pals_card_target (f : ℝ → ℝ) (h : True) : "
        "let p := f 0; let q := f 1; p = p ∧ q = q",
        "theorem pals_card_target (g : ℝ → ℝ) : let p := g 0; let q := g 1; p = p ∧ q = q",
        "theorem other_name (f : ℝ → ℝ) : let p := f 0; let q := f 1; p = p ∧ q = q",
        "theorem pals_card_target (f : ℝ → ℝ) : let p := f 0; let q := f 1; p = p",
    ],
)
def test_splice_refuses_a_statement_the_model_changed(changed_statement: str) -> None:
    code = f"import Mathlib\n{changed_statement} := by\n  simp\n"
    assert splice_formal_harness(code, LET_HARNESS) is None
    assert not contains_formal_statement_modulo_layout(code, LET_HARNESS)


def test_splice_does_not_merge_adjacent_words() -> None:
    harness = "theorem t (a b : ℕ) : a + b = b + a"
    merged = "theorem t (ab : ℕ) : ab + b = b + ab := by omega"
    assert splice_formal_harness(merged, harness) is None


def test_splice_returns_none_when_already_verbatim_or_empty() -> None:
    code = f"{LET_HARNESS} := by\n  simp\n"
    assert splice_formal_harness(code, LET_HARNESS) is None
    assert splice_formal_harness("", LET_HARNESS) is None
    assert splice_formal_harness("theorem x : True := trivial", "   ") is None


def test_splice_ignores_truncated_or_degenerate_output() -> None:
    # Observed model outputs that merely start with ``theorem``.
    for code in (
        "theorem",
        "theorem -- have not been verified",
        "theorem. example : True := trivial",
    ):
        assert splice_formal_harness(code, LET_HARNESS) is None


# ---------------------------------------------------------------- route policy


def _request(formal_statement: str | None = HARNESS) -> ProofRequest:
    return ProofRequest(id="card", prompt="Prove the card.", formal_statement=formal_statement)


def _draft() -> GeneratedDraft:
    return GeneratedDraft(text="Informal draft.", model="m", raw_model_output="Informal draft.")


def _sketch(code: str) -> GeneratedSketch:
    return GeneratedSketch(lean_code=code, model="m", raw_model_output=code, has_gaps=True)


def _feedback(
    *codes: str,
    draft: GeneratedDraft | None = None,
    sketch: GeneratedSketch | None = None,
) -> GenerationFeedback:
    return GenerationFeedback(
        attempt=1,
        previous_lean_code="theorem x : True := by sorry",
        diagnostics=tuple(
            Diagnostic(severity="error", code=code, message=code) for code in codes
        ),
        previous_draft=draft,
        previous_sketch=sketch,
    )


def test_policy_resumes_at_prove_for_a_plain_lean_failure() -> None:
    sketch = _sketch(f"{HARNESS} := by\n  sorry")
    decision = deterministic_repair_route(
        _request(), _feedback("lean.error", draft=_draft(), sketch=sketch)
    )
    assert isinstance(decision, RepairRouteDecision)
    assert decision.route == "prove"
    assert decision.provider == DETERMINISTIC_ROUTE_PROVIDER
    assert decision.raw_model_output == ""
    assert decision.selector_attempts[0].route == "prove"


def test_policy_never_restarts_the_draft_for_a_statement_mismatch() -> None:
    carries = _sketch(f"{HARNESS} := by\n  sorry")
    lacks = _sketch("theorem pals_card_target : True := by\n  sorry")
    mismatch = "lean.formal_harness_mismatch"
    assert deterministic_repair_route(
        _request(), _feedback(mismatch, draft=_draft(), sketch=carries)
    ).route == "prove"  # type: ignore[union-attr]
    assert deterministic_repair_route(
        _request(), _feedback(mismatch, draft=_draft(), sketch=lacks)
    ).route == "sketch"  # type: ignore[union-attr]


def test_policy_recognises_a_sketch_carrying_the_statement_with_other_layout() -> None:
    sketch = _sketch(
        "theorem pals_card_target {K : Type*} [Field K] {n : ℕ} (v : Fin n → K) :\n"
        "    (∃ b : Fin n → K, (fun i => b i) = v) ↔ LinearIndependent K v ∧ n = n := by\n"
        "  sorry"
    )
    decision = deterministic_repair_route(
        _request(), _feedback("lean.formal_harness_mismatch", draft=_draft(), sketch=sketch)
    )
    assert decision is not None and decision.route == "prove"


def test_policy_restarts_the_missing_stage() -> None:
    assert deterministic_repair_route(_request(), _feedback("lean.error")).route == "draft"  # type: ignore[union-attr]
    assert deterministic_repair_route(
        _request(), _feedback("lean.error", draft=_draft())
    ).route == "sketch"  # type: ignore[union-attr]
    assert deterministic_repair_route(
        _request(), _feedback("lean.error", draft=_draft(), sketch=_sketch("  "))
    ).route == "sketch"  # type: ignore[union-attr]


@pytest.mark.parametrize("code", ["pals.repair_stagnation", "pals.proof_method_mismatch"])
def test_policy_leaves_judgement_calls_to_the_model(code: str) -> None:
    sketch = _sketch(f"{HARNESS} := by\n  sorry")
    assert (
        deterministic_repair_route(
            _request(), _feedback("lean.error", code, draft=_draft(), sketch=sketch)
        )
        is None
    )


def test_policy_does_not_apply_without_a_fixed_statement() -> None:
    sketch = _sketch("theorem x : True := by\n  sorry")
    assert (
        deterministic_repair_route(
            _request(None), _feedback("lean.error", draft=_draft(), sketch=sketch)
        )
        is None
    )
    assert (
        deterministic_repair_route(
            _request("  "), _feedback("lean.error", draft=_draft(), sketch=sketch)
        )
        is None
    )


# ---------------------------------------------------------------- pipeline wiring

FORMAL = "theorem add_zero_nat (n : Nat) : n + 0 = n"
SPACED = "theorem add_zero_nat (n : Nat) : n+0=n"
GOOD_PROOF = f"{FORMAL} := by\n  simp\n"
SPACED_PROOF = f"{SPACED} := by\n  simp\n"
BROKEN_PROOF = f"{FORMAL} := by\n  broken_identifier\n"


class RecordingVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        if "broken_identifier" in lean_code:
            return VerificationResult(
                success=False,
                diagnostics=[
                    Diagnostic(severity="error", code="lean.error", message="unknown identifier")
                ],
                stdout="",
                stderr="",
                elapsed_ms=1,
            )
        return VerificationResult(success=True, diagnostics=[], stdout="", stderr="", elapsed_ms=1)


class ScriptedGenerator:
    """Single-stage generator that returns scripted candidates and counts its calls."""

    model = "fake"

    def __init__(self, first: str, repaired: str = GOOD_PROOF) -> None:
        self.first = first
        self.repaired = repaired
        self.generate_calls = 0
        self.repair_calls = 0
        self.route_calls = 0

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self.generate_calls += 1
        return GeneratedProof(lean_code=self.first, model=self.model, raw_model_output=self.first)

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.repair_calls += 1
        return GeneratedProof(
            lean_code=self.repaired, model=self.model, raw_model_output=self.repaired
        )

    def select_repair_route(
        self, request: ProofRequest, feedback: GenerationFeedback
    ) -> RepairRouteDecision:
        self.route_calls += 1
        return RepairRouteDecision(route="prove", rationale="model", raw_model_output="{}")


def _run(tmp_path: Path, generator: ScriptedGenerator, **flags: bool):
    verifier = RecordingVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        max_repair_attempts=3,
        **flags,
    )
    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement=FORMAL,
        proof_job_id="job",
    )
    return result, verifier


def test_flags_are_off_by_default_and_change_nothing(tmp_path: Path) -> None:
    generator = ScriptedGenerator(SPACED_PROOF)
    result, verifier = _run(tmp_path, generator)
    assert result.state == "verified"
    assert generator.repair_calls == 1  # the old path: mismatch -> model route -> repair
    assert generator.route_calls == 1
    assert verifier.calls == [GOOD_PROOF]


def test_harness_splice_verifies_a_retyped_statement_without_any_repair(tmp_path: Path) -> None:
    generator = ScriptedGenerator(SPACED_PROOF)
    result, verifier = _run(tmp_path, generator, harness_splice=True)
    assert result.state == "verified"
    assert (generator.generate_calls, generator.repair_calls, generator.route_calls) == (1, 0, 0)
    assert verifier.calls == [GOOD_PROOF]
    assert result.generated.lean_code == GOOD_PROOF
    assert result.model_attempt.lean_code == GOOD_PROOF


def test_harness_splice_leaves_a_changed_statement_to_the_normal_repair(tmp_path: Path) -> None:
    changed = "theorem add_zero_nat (n : Nat) : n + 1 = n + 1 := by\n  simp\n"
    generator = ScriptedGenerator(changed)
    result, verifier = _run(tmp_path, generator, harness_splice=True)
    assert result.state == "verified"
    assert generator.repair_calls == 1
    assert verifier.calls == [GOOD_PROOF]


def test_spliced_candidate_still_goes_through_lean(tmp_path: Path) -> None:
    spliced_broken = f"{SPACED} := by\n  broken_identifier\n"
    generator = ScriptedGenerator(spliced_broken)
    result, verifier = _run(tmp_path, generator, harness_splice=True)
    assert verifier.calls[0] == BROKEN_PROOF  # compiled with the user's statement verbatim
    assert result.state == "verified"
    assert generator.repair_calls == 1


def test_deterministic_route_skips_the_selector_model_call(tmp_path: Path) -> None:
    generator = ScriptedGenerator(BROKEN_PROOF)
    result, _verifier = _run(tmp_path, generator, deterministic_repair_route=True)
    assert result.state == "verified"
    assert generator.route_calls == 0
    assert generator.repair_calls == 1
    route = json.loads((tmp_path / "job" / "result.json").read_text())["attempts"][1][
        "repair_route"
    ]
    assert route["provider"] == DETERMINISTIC_ROUTE_PROVIDER
    # This single-stage fake never produced a Draft, so the policy restarts at the Draft.
    assert route["route"] == "draft"
    assert route["elapsed_ms"] == 0


# ---------------------------------------------------------------- sketch failure


class StagedGenerator:
    model = "fake"

    def __init__(self) -> None:
        self.proof_feedback: list[GenerationFeedback | None] = []
        self.route_calls = 0

    def generate_draft(self, request, feedback=None):  # type: ignore[no-untyped-def]
        return GeneratedDraft(text="draft", model=self.model, raw_model_output="draft")

    def generate_sketch(self, request, draft, feedback=None):  # type: ignore[no-untyped-def]
        code = f"{FORMAL} := by\n  sorry\n"
        return GeneratedSketch(
            lean_code=code, model=self.model, raw_model_output=code, has_gaps=True
        )

    def generate_proof(self, request, draft, sketch, feedback=None):  # type: ignore[no-untyped-def]
        self.proof_feedback.append(feedback)
        return GeneratedProof(
            lean_code=GOOD_PROOF, model=self.model, raw_model_output=GOOD_PROOF,
            draft=draft, sketch=sketch,
        )

    def repair(self, request, feedback):  # type: ignore[no-untyped-def]
        raise AssertionError("the staged path never calls repair()")

    def select_repair_route(self, request, feedback):  # type: ignore[no-untyped-def]
        self.route_calls += 1
        return RepairRouteDecision(route="prove", rationale="model", raw_model_output="{}")


class SketchRejectingVerifier(RecordingVerifier):
    def verify_sketch(self, lean_code: str) -> VerificationResult:
        return VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic(severity="error", code="lean.invalidField", message="bad sketch field")
            ],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )


def _run_staged(tmp_path: Path, **flags: bool):
    generator = StagedGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=SketchRejectingVerifier(),
        artifact_store=FileArtifactStore(tmp_path),
        max_repair_attempts=3,
        **flags,
    )
    result = pipeline.run_statement(
        statement="Every natural number plus zero is itself.",
        formal_statement=FORMAL,
        proof_job_id="job",
    )
    return generator, result


def test_failed_sketch_normally_costs_an_attempt_and_a_route_call(tmp_path: Path) -> None:
    generator, result = _run_staged(tmp_path)
    assert result.state == "verified"
    assert generator.route_calls == 1
    metadata = json.loads((tmp_path / "job" / "result.json").read_text())
    assert len(metadata["attempts"]) == 2
    assert metadata["repairs_used"] == 1


def test_failed_sketch_proceeds_to_prove_within_the_same_attempt(tmp_path: Path) -> None:
    generator, result = _run_staged(tmp_path, sketch_failure_proceeds_to_prove=True)
    assert result.state == "verified"
    assert generator.route_calls == 0
    metadata = json.loads((tmp_path / "job" / "result.json").read_text())
    assert len(metadata["attempts"]) == 1
    assert metadata["repairs_used"] == 0
    (feedback,) = generator.proof_feedback
    assert feedback is not None
    assert feedback.repair_route == "prove"
    assert feedback.previous_lean_code.endswith("sorry\n")
    assert [d.code for d in feedback.diagnostics] == ["lean.invalidField"]
