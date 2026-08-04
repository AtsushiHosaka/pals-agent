from __future__ import annotations

import shutil

import pytest

from pals_agent import lean as lean_module
from pals_agent.lean import LeanVerifier, parse_lean_diagnostics


def test_verifier_rejects_sorry_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify("example : True := by\n  sorry")

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_placeholder"


def test_verifier_rejects_sorry_ax_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(
        "theorem unsound : False := _root_.sorryAx False true"
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_placeholder"
    assert "sorryAx" in result.diagnostics[0].message


def test_sketch_verifier_allows_sorry_but_still_invokes_lean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _binary: "/usr/bin/lean")
    calls: list[list[str]] = []

    def compiler_accepts_sketch(
        command: list[str],
        **_kwargs: object,
    ) -> lean_module._ProcessResult:
        calls.append(command)
        return lean_module._ProcessResult(
            returncode=0,
            stdout="",
            stderr="/tmp/Main.lean:1:8: warning: declaration uses `sorry`\n",
            timed_out=False,
            output_limited=False,
        )

    monkeypatch.setattr(lean_module, "_run_limited_process", compiler_accepts_sketch)

    result = LeanVerifier().verify_sketch("example : True := by\n  sorry")

    assert calls
    assert result.success is True
    assert all(
        diagnostic.code != "lean.declaration_uses_sorry"
        for diagnostic in result.diagnostics
    )


def test_sketch_verifier_does_not_allow_admit() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify_sketch(
        "example : True := by\n  admit"
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_placeholder"


def test_verifier_rejects_compiler_report_that_declaration_uses_sorry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _binary: "/usr/bin/lean")

    def compiler_accepts_with_sorry_warning(
        *_args: object,
        **_kwargs: object,
    ) -> lean_module._ProcessResult:
        return lean_module._ProcessResult(
            returncode=0,
            stdout="",
            stderr="/tmp/Main.lean:1:8: warning: declaration uses `sorry`\n",
            timed_out=False,
            output_limited=False,
        )

    monkeypatch.setattr(
        lean_module,
        "_run_limited_process",
        compiler_accepts_with_sorry_warning,
    )

    result = LeanVerifier().verify("example : True := by trivial")

    assert result.success is False
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "lean.declaration_uses_sorry"
    ]
    assert all(diagnostic.code != "lean.verified" for diagnostic in result.diagnostics)


def test_verifier_rejects_trusted_declarations_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(
        "axiom h : False\nexample : False := h"
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_trusted_declaration"


def test_verifier_ignores_disallowed_tokens_in_comments_and_strings() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(
        '\n'.join(
            [
                '-- sorry sorryAx axiom constant unsafe opaque #check run_cmd',
                '/- admit axiom constant unsafe opaque #eval macro -/',
                'def note := "sorry sorryAx axiom constant unsafe opaque #check run_cmd"',
                'example : True := by',
                '  trivial',
            ]
        )
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.not_found"


def test_verifier_rejects_interactive_command_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify("#eval IO.println \"hello\"")

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_interactive_command"


def test_verifier_rejects_check_command_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify("#check Nat")

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_interactive_command"


def test_verifier_rejects_metaprogramming_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(
        "run_cmd do\n  IO.println \"hidden target\""
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_metaprogramming"


def test_verifier_rejects_syntax_quotation_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(
        "def targetSyntax := `(command| theorem sample : True := by trivial)"
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_syntax_quotation"


def test_parse_lean_diagnostics_extracts_location() -> None:
    diagnostics = parse_lean_diagnostics(
        "/tmp/Main.lean:3:12: error: unknown identifier 'foo'\n"
    )

    assert diagnostics[0].severity == "error"
    assert diagnostics[0].line == 3
    assert diagnostics[0].column == 12
    assert diagnostics[0].message == "unknown identifier 'foo'"


def test_parse_lean_diagnostics_preserves_multiline_message_and_compiler_code() -> None:
    diagnostics = parse_lean_diagnostics(
        "/tmp/Main.lean:41:41: error: Application type mismatch: The argument\n"
        "  hδle\n"
        "has type\n"
        "  δ ≤ ε / (2 * ‖x‖ + 1)\n"
        "but is expected to have type\n"
        "  1 < ε / (2 * ‖x‖ + 1)\n"
        "/tmp/Main.lean:43:12: error(lean.unknownIdentifier): "
        "Unknown identifier `mul_lt_mul_right_of_pos'`\n"
    )

    assert len(diagnostics) == 2
    assert "hδle" in diagnostics[0].message
    assert "is expected to have type" in diagnostics[0].message
    assert diagnostics[1].code == "lean.unknownIdentifier"
    assert "mul_lt_mul_right_of_pos'" in diagnostics[1].message


def test_parse_lean_diagnostics_promotes_sorry_warning_to_error() -> None:
    diagnostics = parse_lean_diagnostics(
        "/tmp/Main.lean:1:8: warning: declaration uses 'sorry'\n"
    )

    assert diagnostics[0].severity == "error"
    assert diagnostics[0].code == "lean.declaration_uses_sorry"
