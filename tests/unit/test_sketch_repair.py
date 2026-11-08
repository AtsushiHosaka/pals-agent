import json
from pathlib import Path

from pals_agent.artifacts import FileArtifactStore
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import ProofPipeline
from pals_agent.sketch_repair import normalize_header, repair_sketch, sorry_failing_leaves
from tools.mathlib_index.sketch_failures import classify_message

HEADER = "theorem t (a b : ℕ) (h : a = b) : b = a := by"


def _error(line: int, column: int, message: str = "linarith failed") -> Diagnostic:
    return Diagnostic(
        severity="error", code="lean.error", message=message, line=line, column=column
    )


def test_failing_nested_block_becomes_sorry_and_keeps_the_statement() -> None:
    code = "\n".join(
        [
            "import Mathlib",
            "",
            HEADER,
            "  have h1 : a = b := by",
            "    omega",
            "    simp",
            "  have h2 : b = a := by",
            "    sorry",
            "  exact h2",
        ]
    )
    fixed = sorry_failing_leaves(code, [_error(6, 4)])
    assert fixed is not None
    assert fixed.split("\n")[3:] == [
        "  have h1 : a = b := by",
        "    sorry",
        "  have h2 : b = a := by",
        "    sorry",
        "  exact h2",
    ]


def test_inline_by_is_replaced_without_swallowing_later_lines() -> None:
    code = "\n".join(
        [
            HEADER,
            "  constructor",
            "  · have h1 : a = b := by linarith",
            "    exact h1.symm",
        ]
    )
    fixed = sorry_failing_leaves(code, [_error(3, 31)])
    assert fixed is not None
    assert fixed.split("\n")[2:] == ["  · have h1 : a = b := by sorry", "    exact h1.symm"]


def test_errors_in_statement_or_syntax_are_left_alone() -> None:
    code = "\n".join([HEADER, "  have h : a = b := by", "    omega"])
    assert sorry_failing_leaves(code, [_error(1, 10, "Unknown identifier `x`")]) is None
    assert sorry_failing_leaves(code, [_error(3, 4, "unexpected token ')'; expected term")]) is None
    assert sorry_failing_leaves(code, []) is None


def test_type_mismatch_message_is_not_mistaken_for_a_parse_error() -> None:
    code = "\n".join([HEADER, "  have h : a = b := by", "    exact foo"])
    message = "Type mismatch\n  foo\nhas type\n  a = b\nbut is expected to have type\n  b = a"
    assert sorry_failing_leaves(code, [_error(3, 4, message)]) is not None


def test_header_gets_full_mathlib_and_the_open_for_scoped_notation() -> None:
    code = (
        "import Mathlib.Order.Filter.Basic\nimport Mathlib.Tactic\n\n"
        "theorem t : 𝓝 (0 : ℝ) = 𝓝 0 := by\n  rfl"
    )
    fixed = normalize_header(code)
    assert fixed is not None
    assert fixed.startswith("import Mathlib\nopen Topology\n\ntheorem t")
    assert normalize_header(fixed) is None
    assert normalize_header("import Mathlib\n\ntheorem t : True := by\n  trivial") is None


def test_notation_inside_a_comment_does_not_add_an_open() -> None:
    code = "import Mathlib.Tactic\n\ntheorem t : True := by\n  -- uses 𝓝 later\n  trivial"
    fixed = normalize_header(code)
    assert fixed is not None and "open" not in fixed


def test_repair_stops_after_the_first_passing_recheck() -> None:
    code = (
        "import Mathlib.Tactic\n\n" + HEADER + "\n  have h : a = b := by\n    omega\n  exact h.symm"
    )
    calls: list[str] = []

    def verify(candidate: str) -> VerificationResult:
        calls.append(candidate)
        ok = "import Mathlib\n" in candidate
        return VerificationResult(success=ok, diagnostics=[], stdout="", stderr="", elapsed_ms=5)

    first = VerificationResult(
        success=False, diagnostics=[_error(5, 4)], stdout="", stderr="", elapsed_ms=1
    )
    repaired = repair_sketch(code, first, verify)
    assert repaired is not None
    assert repaired.steps == ("header",)
    assert len(calls) == 1


def test_repair_gives_up_when_nothing_can_be_isolated() -> None:
    code = "import Mathlib\n\n" + HEADER + "\n  omega"
    first = VerificationResult(
        success=False,
        diagnostics=[_error(1, 5, "Unknown identifier `x`")],
        stdout="",
        stderr="",
        elapsed_ms=1,
    )
    assert repair_sketch(code, first, lambda c: first) is None


def test_classifier_reads_the_message_not_the_generic_code() -> None:
    assert classify_message("Unknown identifier `foo.bar`") == "unknown_identifier"
    assert classify_message("Unknown identifier `𝓝`") == "unknown_notation"
    assert classify_message("linarith failed to find a contradiction") == "tactic_failed"
    assert classify_message("Type mismatch\n  x") == "type_mismatch"
    assert classify_message("unsolved goals\n⊢ False") == "unsolved_goals"
    assert (
        classify_message("object file '/m/A.olean' of module A does not exist") == "missing_module"
    )
    assert classify_message("unexpected token '≠'; expected ':' or term") == "syntax"
    assert classify_message("something unrecognised") == "other"


# ---------------------------------------------------------------- pipeline flag

FORMAL = "theorem pals_card_target : (0 : ℕ) + 0 = 0"
GOOD = f"import Mathlib\n\n{FORMAL} := by\n  simp\n"


class _Generator:
    model = "fake"

    def __init__(self) -> None:
        self.route_calls = 0
        self.sketches_seen_by_prove: list[str] = []

    def generate_draft(self, request, feedback=None):  # type: ignore[no-untyped-def]
        return GeneratedDraft(text="draft", model=self.model, raw_model_output="draft")

    def generate_sketch(self, request, draft, feedback=None):  # type: ignore[no-untyped-def]
        code = (
            f"import Mathlib.Tactic\n\n{FORMAL} := by\n"
            "  have h : (0 : ℕ) = 0 := by\n    sorry\n  omega"
        )
        return GeneratedSketch(
            lean_code=code, model=self.model, raw_model_output=code, has_gaps=True
        )

    def generate_proof(self, request, draft, sketch, feedback=None):  # type: ignore[no-untyped-def]
        self.sketches_seen_by_prove.append(sketch.lean_code)
        return GeneratedProof(
            lean_code=GOOD, model=self.model, raw_model_output=GOOD, draft=draft, sketch=sketch
        )

    def repair(self, request, feedback):  # type: ignore[no-untyped-def]
        raise AssertionError("the staged path never calls repair()")

    def select_repair_route(self, request, feedback):  # type: ignore[no-untyped-def]
        self.route_calls += 1
        return RepairRouteDecision(route="prove", rationale="model", raw_model_output="{}")


class _Verifier:
    """A Sketch passes only with the full `import Mathlib`; the final proof always passes."""

    def verify(self, lean_code: str) -> VerificationResult:
        return VerificationResult(success=True, diagnostics=[], stdout="", stderr="", elapsed_ms=1)

    def verify_sketch(self, lean_code: str) -> VerificationResult:
        ok = lean_code.startswith("import Mathlib\n")
        diagnostics = (
            []
            if ok
            else [
                Diagnostic(
                    severity="error",
                    code="lean.error",
                    message="Unknown constant `X`",
                    line=1,
                    column=0,
                )
            ]
        )
        return VerificationResult(
            success=ok, diagnostics=diagnostics, stdout="", stderr="", elapsed_ms=1
        )


def _run(tmp_path: Path, **flags: bool) -> tuple[_Generator, str]:
    generator = _Generator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=_Verifier(),  # type: ignore[arg-type]
        artifact_store=FileArtifactStore(tmp_path),
        max_repair_attempts=3,
        **flags,
    )
    result = pipeline.run_statement(
        statement="Zero plus zero is zero.", formal_statement=FORMAL, proof_job_id="job"
    )
    return generator, result.state


def test_without_the_flag_a_failed_sketch_still_costs_a_route_call(tmp_path: Path) -> None:
    generator, state = _run(tmp_path)
    assert generator.route_calls == 1
    assert state == "verified"
    assert json.loads((tmp_path / "job" / "result.json").read_text())["repairs_used"] == 1


def test_with_the_flag_the_sketch_is_repaired_before_prove(tmp_path: Path) -> None:
    generator, state = _run(tmp_path, sketch_mechanical_repair=True)
    assert state == "verified"
    assert generator.route_calls == 0
    assert json.loads((tmp_path / "job" / "result.json").read_text())["repairs_used"] == 0
    assert generator.sketches_seen_by_prove[0].startswith("import Mathlib\n")
