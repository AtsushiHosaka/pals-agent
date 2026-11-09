import json
from pathlib import Path

from pals_agent.artifacts import FileArtifactStore
from pals_agent.generator import HybridLeanGenerator
from pals_agent.models import Diagnostic, GeneratedProof, ProofRequest, VerificationResult
from pals_agent.pipeline import ProofPipeline
from pals_agent.statement_template import MARKER, TEMPLATE_INSTRUCTION, assemble

STATEMENT = "theorem pals_card_target (n : ℕ) : n + 0 = n"


def test_marker_layout_inserts_the_fixed_statement_verbatim() -> None:
    raw = f"import Mathlib\nopen Nat\n\nlemma aux : True := trivial\n{MARKER}\nsimp\n"
    assert assemble(raw, STATEMENT) == (
        "import Mathlib\nopen Nat\n\nlemma aux : True := trivial\n\n"
        f"{STATEMENT} := by\n  simp\n"
    )


def test_a_leading_by_and_indentation_are_normalised() -> None:
    raw = f"import Mathlib\n{MARKER}\nby\n    intro h\n    exact h\n"
    out = assemble(raw, STATEMENT)
    assert out.endswith(f"{STATEMENT} := by\n  intro h\n  exact h\n")


def test_an_unrelated_example_is_never_taken_for_the_target() -> None:
    raw = "import Mathlib\nexample (z : ℕ) : z = z := by\n  rfl\n"
    assert assemble(raw, STATEMENT) == raw


def test_a_rewritten_target_keeps_only_its_body() -> None:
    raw = "import Mathlib\ntheorem pals_card_target (n : ℕ) (h : True) : n = n := by\n  rfl\n"
    out = assemble(raw, STATEMENT)
    assert f"{STATEMENT} := by\n  rfl" in out
    assert "(h : True)" not in out


def test_a_term_mode_target_is_left_alone() -> None:
    raw = "import Mathlib\ntheorem pals_card_target (n : ℕ) : n + 0 = n := rfl\n"
    assert assemble(raw, STATEMENT) == raw


def test_empty_body_and_non_theorem_statements_are_left_alone() -> None:
    assert assemble(f"import Mathlib\n{MARKER}\n", STATEMENT) == f"import Mathlib\n{MARKER}\n"
    assert assemble(f"{MARKER}\nsimp", "def f := 1") == f"{MARKER}\nsimp"


class _Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def _request(formal: str | None) -> ProofRequest:
    return ProofRequest(id="r", prompt="n plus zero", formal_statement=formal)


def test_generator_adds_the_instruction_and_assembles_only_when_enabled() -> None:
    reply = f"```lean\nimport Mathlib\n{MARKER}\nsimp\n```"
    on_client, off_client = _Client(reply), _Client(reply)
    from pals_agent.models import GeneratedDraft

    draft = GeneratedDraft(text="d", model="m", raw_model_output="d")
    on = HybridLeanGenerator(model="m", client=on_client, fixed_statement_template=True)
    off = HybridLeanGenerator(model="m", client=off_client)
    sketch_on = on.generate_sketch(_request(STATEMENT), draft)
    sketch_off = off.generate_sketch(_request(STATEMENT), draft)
    assert TEMPLATE_INSTRUCTION in on_client.prompts[0]
    assert TEMPLATE_INSTRUCTION not in off_client.prompts[0]
    assert f"{STATEMENT} := by" in sketch_on.lean_code
    assert STATEMENT not in sketch_off.lean_code
    # Without a fixed statement the template stays out of the way.
    free = on.generate_sketch(_request(None), draft)
    assert TEMPLATE_INSTRUCTION not in on_client.prompts[-1]
    assert STATEMENT not in free.lean_code


# ---------------------------------------------------------------- early stop


class _AlwaysMismatching:
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):  # type: ignore[no-untyped-def]
        return self._wrong()

    def repair(self, request, feedback):  # type: ignore[no-untyped-def]
        return self._wrong()

    def select_repair_route(self, request, feedback):  # type: ignore[no-untyped-def]
        from pals_agent.models import RepairRouteDecision

        return RepairRouteDecision(route="prove", rationale="r", raw_model_output="{}")

    def _wrong(self) -> GeneratedProof:
        self.calls += 1
        code = "import Mathlib\nexample : True := trivial\n"
        return GeneratedProof(lean_code=code, model=self.model, raw_model_output=code)


class _Verifier:
    def verify(self, lean_code: str) -> VerificationResult:
        return VerificationResult(
            success=False,
            diagnostics=[Diagnostic(severity="error", code="lean.error", message="x")],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )


def _run(tmp_path: Path, **flags: bool) -> tuple[_AlwaysMismatching, dict]:
    generator = _AlwaysMismatching()
    pipeline = ProofPipeline(
        generator=generator,  # type: ignore[arg-type]
        verifier=_Verifier(),  # type: ignore[arg-type]
        artifact_store=FileArtifactStore(tmp_path),
        max_repair_attempts=6,
        **flags,
    )
    pipeline.run_statement(statement="n plus zero", formal_statement=STATEMENT, proof_job_id="job")
    return generator, json.loads((tmp_path / "job" / "result.json").read_text())


def test_without_the_flag_the_mismatch_uses_the_whole_repair_budget(tmp_path: Path) -> None:
    generator, metadata = _run(tmp_path)
    assert generator.calls == 7
    assert metadata["repairs_used"] == 6


def test_with_the_flag_the_second_mismatch_ends_the_run(tmp_path: Path) -> None:
    generator, metadata = _run(tmp_path, stop_on_repeated_harness_mismatch=True)
    assert generator.calls == 2
    assert metadata["repairs_used"] == 1
    assert metadata["termination_reason"] == "repair_budget_exhausted"


# ------------------------------------------------- early stop on statement mismatch


class _Scripted:
    """Generates one attempt per scripted kind: harness, statement or other failure."""

    model = "fake"

    def __init__(self, kinds: list[str]) -> None:
        self.kinds = kinds
        self.calls = 0

    def generate(self, request):  # type: ignore[no-untyped-def]
        return self._next()

    def repair(self, request, feedback):  # type: ignore[no-untyped-def]
        return self._next()

    def select_repair_route(self, request, feedback):  # type: ignore[no-untyped-def]
        from pals_agent.models import RepairRouteDecision

        return RepairRouteDecision(route="prove", rationale="r", raw_model_output="{}")

    def _next(self) -> GeneratedProof:
        kind = self.kinds[min(self.calls, len(self.kinds) - 1)]
        self.calls += 1
        statement = "" if kind == "harness" else f"{STATEMENT} := by\n  sorry\n"
        code = f"import Mathlib\n-- kind:{kind}\n{statement or 'example : True := trivial'}\n"
        return GeneratedProof(lean_code=code, model=self.model, raw_model_output=code)


class _KindVerifier:
    def verify(self, lean_code: str) -> VerificationResult:
        code = "lean.statement_mismatch" if "kind:statement" in lean_code else "lean.error"
        return VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic(severity="error", code=code, message="x"),
                Diagnostic(severity="warning", code="lean.warning", message="unused"),
            ],
            stdout="",
            stderr="",
            elapsed_ms=1,
        )


def _run_kinds(tmp_path: Path, kinds: list[str], **flags: bool) -> tuple[_Scripted, dict]:
    generator = _Scripted(kinds)
    pipeline = ProofPipeline(
        generator=generator,  # type: ignore[arg-type]
        verifier=_KindVerifier(),  # type: ignore[arg-type]
        artifact_store=FileArtifactStore(tmp_path),
        max_repair_attempts=6,
        **flags,
    )
    pipeline.run_statement(statement="n plus zero", formal_statement=STATEMENT, proof_job_id="job")
    return generator, json.loads((tmp_path / "job" / "result.json").read_text())


def _early_stop_diagnostics(metadata: dict) -> list[dict]:
    return [
        d for d in metadata["diagnostics"] if d["code"] == "pals.repair_budget_exhausted"
    ]


def test_statement_flag_off_does_not_stop_on_repeated_statement_mismatch(tmp_path: Path) -> None:
    generator, metadata = _run_kinds(tmp_path, ["statement"])
    assert generator.calls == 7
    assert metadata["repairs_used"] == 6


def test_two_statement_mismatches_end_the_run_before_the_next_generation(tmp_path: Path) -> None:
    generator, metadata = _run_kinds(
        tmp_path, ["statement"], stop_on_repeated_statement_mismatch=True
    )
    assert generator.calls == 2
    assert metadata["repairs_used"] == 1
    assert metadata["termination_reason"] == "repair_budget_exhausted"
    (diagnostic,) = _early_stop_diagnostics(metadata)
    assert "statement" in diagnostic["message"]


def test_a_mixed_harness_and_statement_pair_ends_the_run(tmp_path: Path) -> None:
    for kinds in (["harness", "statement"], ["statement", "harness"]):
        generator, metadata = _run_kinds(
            tmp_path / "_".join(kinds), kinds, stop_on_repeated_statement_mismatch=True
        )
        assert generator.calls == 2, kinds
        assert metadata["termination_reason"] == "repair_budget_exhausted"


def test_another_error_in_between_does_not_stop_the_run(tmp_path: Path) -> None:
    generator, metadata = _run_kinds(
        tmp_path,
        ["statement", "other", "statement", "other", "statement", "other", "statement"],
        stop_on_repeated_statement_mismatch=True,
    )
    assert generator.calls == 7
    assert metadata["repairs_used"] == 6


def test_the_harness_flag_alone_ignores_statement_mismatch(tmp_path: Path) -> None:
    generator, metadata = _run_kinds(
        tmp_path / "statement", ["statement"], stop_on_repeated_harness_mismatch=True
    )
    assert generator.calls == 7
    generator, _ = _run_kinds(
        tmp_path / "mixed", ["harness", "statement"], stop_on_repeated_harness_mismatch=True
    )
    assert generator.calls == 7


def test_both_flags_emit_one_early_stop_diagnostic(tmp_path: Path) -> None:
    generator, metadata = _run_kinds(
        tmp_path,
        ["harness"],
        stop_on_repeated_harness_mismatch=True,
        stop_on_repeated_statement_mismatch=True,
    )
    assert generator.calls == 2
    assert len(_early_stop_diagnostics(metadata)) == 1
