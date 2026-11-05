"""Runtime preflight codes remain closed and redacted; no compiler/model calls."""

import sys
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_verifier.http_server import _failure_code, _repair_diagnostics
from pals_agent.models import Diagnostic, VerificationResult


@pytest.mark.parametrize("code", ["lean.not_found", "lake.not_found"])
def test_missing_runtime_feedback_retains_only_the_closed_code(code):
    diagnostic = Diagnostic(
        severity="error", code=code,
        message="secret path /private/runtime/credentials unexpectedly token=do-not-export",
        line=12, column=8,
    )
    result = VerificationResult(False, [diagnostic], "private stdout", "private stderr", 0)
    assert _failure_code(result) == "verifier_compile_failed"
    assert _repair_diagnostics(result, "unused") == [
        {"code": code, "symbol": None, "line": None, "column": None}
    ]


@pytest.mark.parametrize("tool", ["lean", "lake"])
def test_real_missing_tool_preflight_does_not_become_source_feedback(tool, tmp_path):
    corpus = Path(__file__).resolve().parents[2] / "testdata/explanation-grounding-v1"
    absent = str(tmp_path / "intentionally-absent")
    assert not Path(absent).exists()
    verifier = LeanVerifier(lean_binary=absent) if tool == "lean" else LeanVerifier(
        lean_binary=sys.executable, lake_binary=absent, project_dir=corpus,
    )
    # The lake case never executes the stand-in found binary: it fails preflight first.
    result = verifier.verify((corpus / "Coprime.lean").read_text())
    assert not result.success
    assert [d.code for d in result.diagnostics] == [tool + ".not_found"]
    assert _repair_diagnostics(result, "unused") == [
        {"code": tool + ".not_found", "symbol": None, "line": None, "column": None}
    ]


def test_real_compile_feedback_and_bounded_output_are_preserved():
    result = VerificationResult(False, [
        Diagnostic(severity="error", code="lean.unknown", message="type mismatch",
                   line=2, column=3),
        *[Diagnostic(severity="error", code="lean.not_found", message="private")
          for _ in range(12)],
    ], "", "", 0)
    feedback = _repair_diagnostics(result, "unused")
    assert len(feedback) == 8
    assert feedback[0] == {
        "code": "lean.type_mismatch", "symbol": None, "line": 2, "column": 3,
    }
    assert all(d == {"code": "lean.not_found", "symbol": None, "line": None,
                     "column": None} for d in feedback[1:])
