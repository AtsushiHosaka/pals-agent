"""The stepwise lane inside ProofPipeline: default off, assembled file checked whole."""

import threading
from pathlib import Path

import pytest

from pals_agent import dsp_stepwise
from pals_agent.artifacts import FileArtifactStore
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    VerificationResult,
)
from pals_agent.pipeline import ProofPipeline

FORMAL = "theorem t (a b c : ℝ) (hab : a ≤ b) (hbc : b ≤ c) : a ≤ c"
SKELETON = (
    "```lean\n-- PALS-PROOF-BODY\n  have h1 : a ≤ b := by sorry\n"
    "  have h2 : b ≤ c := by sorry\n  exact le_trans h1 h2\n```"
)
FINAL = (
    "import Mathlib\n\ntheorem t (a b c : ℝ) (hab : a ≤ b) (hbc : b ≤ c) : a ≤ c := by\n"
    "  have h1 : a ≤ b := by\n    exact hab\n"
    "  have h2 : b ≤ c := by\n    exact hbc\n  exact le_trans h1 h2\n"
)


def _ok(good: bool) -> VerificationResult:
    diags = [] if good else [Diagnostic(severity="error", message="RAW", line=3, column=2)]
    return VerificationResult(success=good, diagnostics=diags, stdout="", stderr="", elapsed_ms=1)


class Verifier:
    def __init__(self) -> None:
        self.full: list[str] = []
        self.sketch: list[str] = []
        self.lock = threading.Lock()

    def verify(self, code: str) -> VerificationResult:
        with self.lock:
            self.full.append(code)
        return _ok("sorry" not in code and "exact hab" in code)

    def verify_sketch(self, code: str) -> VerificationResult:
        with self.lock:
            self.sketch.append(code)
        return _ok("first |" not in code)  # automation never closes a step here


class Client:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Plan a Lean 4" in prompt and "The step to prove" not in prompt:
            return SKELETON
        return (
            "```lean\nexact hab\n```"
            if "have h1" in prompt.split("The step to prove:")[-1]
            else "```lean\nexact hbc\n```"
        )


class Generator:
    model = prove_model = "m"

    def __init__(self, client: Client | None) -> None:
        self.client = client
        self.calls: list[str] = []

    def _stage_endpoint(self, role):
        return self.client, "m", "openai", None

    def generate_draft(self, request, feedback=None):
        self.calls.append("draft")
        return GeneratedDraft(text="d", model="m", raw_model_output="d")

    def generate_sketch(self, request, draft, feedback=None):
        self.calls.append("sketch")
        return GeneratedSketch("import Mathlib\n", "m", "", has_gaps=True)

    def generate_proof(self, request, draft, sketch, feedback=None):
        self.calls.append("prove")
        return GeneratedProof(lean_code=FINAL, model="m", raw_model_output=FINAL)


def _run(tmp_path: Path, gen: Generator, verifier: Verifier):
    pipeline = ProofPipeline(
        generator=gen,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        accounting_wait_seconds=0.0,
    )
    return pipeline.run_statement(
        statement="Show a ≤ c.", formal_statement=FORMAL, proof_job_id="job-1"
    )


def test_default_off_runs_the_ordinary_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(dsp_stepwise.STEPWISE_ENV, raising=False)
    gen, verifier = Generator(Client()), Verifier()
    result = _run(tmp_path, gen, verifier)
    assert gen.calls == ["draft", "sketch", "prove"]
    assert result.state == "verified"
    assert verifier.sketch == [] or gen.client.prompts == []


def test_on_returns_the_assembled_file_and_lean_checks_it_as_one_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(dsp_stepwise.STEPWISE_ENV, "true")
    gen, verifier = Generator(Client()), Verifier()
    sink: list = []
    with dsp_stepwise.record_scope(sink):
        result = _run(tmp_path, gen, verifier)
    assert result.state == "verified"
    assert gen.calls == []  # no Draft, Sketch or Prove call of the ordinary path
    assert len(verifier.full) == 1 and "sorry" not in verifier.full[0]
    assert FORMAL + " := by" in verifier.full[0]
    assert sink and sink[0].lean_code == verifier.full[0]


def test_on_without_a_client_falls_back_to_the_ordinary_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(dsp_stepwise.STEPWISE_ENV, "true")
    gen = Generator(None)
    result = _run(tmp_path, gen, Verifier())
    assert gen.calls == ["draft", "sketch", "prove"]
    assert result.state == "verified"
