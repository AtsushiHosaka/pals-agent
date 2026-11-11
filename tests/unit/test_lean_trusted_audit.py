from __future__ import annotations

from pathlib import Path

import pytest

import pals_agent.lean as lean_module
from pals_agent.lean import LeanVerifier
from pals_agent.lean_audit import (
    ALLOWED_AXIOMS,
    TRUSTED_AUDIT_SOURCE,
    audit_diagnostics,
    parse_audit_report,
)
from pals_agent.lean_source_policy import statement_reference

NONCE = "ab" * 32


def _ok(stdout: str = "", returncode: int = 0) -> lean_module._ProcessResult:
    return lean_module._ProcessResult(returncode, stdout, "", False, False)


def _report(*lines: str, nonce: str = NONCE) -> str:
    return "\n".join([*lines, f"complete {nonce}", ""])


def test_allowlist_is_exactly_the_standard_axioms() -> None:
    assert frozenset({"propext", "Classical.choice", "Quot.sound"}) == ALLOWED_AXIOMS


def test_audit_source_replays_through_kernel_and_never_imports_the_candidate() -> None:
    assert "env.replay" in TRUSTED_AUDIT_SOURCE
    assert "readModuleData" in TRUSTED_AUDIT_SOURCE
    assert "import Main" not in TRUSTED_AUDIT_SOURCE


def test_parse_accepts_complete_report() -> None:
    report = parse_audit_report(_report("theorem N.a", "axiom propext"), NONCE)

    assert report is not None
    assert report.theorems == ("N.a",)
    assert report.axioms == ("propext",)


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "theorem a\naxiom propext\n",
        _report(nonce="cd" * 32),
        _report() + "theorem late\n",
        _report() + _report(),
        "unexpected line\n" + _report(),
    ],
)
def test_parse_fails_closed(stdout: str) -> None:
    assert parse_audit_report(stdout, NONCE) is None


def test_diagnostics_accept_standard_axioms_and_declared_theorem() -> None:
    report = parse_audit_report(
        _report("theorem N.target", "axiom propext", "axiom Quot.sound", "bound N.target"), NONCE
    )

    assert report is not None
    assert audit_diagnostics(report, ("target",)) == []


@pytest.mark.parametrize(
    "axiom",
    ["sorryAx", "bad", "Lean.ofReduceBool", "Lean.trustCompiler", "b._native.native_decide.ax_1_1"],
)
def test_diagnostics_reject_every_other_axiom(axiom: str) -> None:
    report = parse_audit_report(_report("theorem t", f"axiom {axiom}", "bound t"), NONCE)

    assert report is not None
    assert [item.code for item in audit_diagnostics(report, ("t",))] == ["lean.disallowed_axiom"]


@pytest.mark.parametrize("reported", ["other", "Xtarget", "target.other"])
def test_diagnostics_reject_declared_theorem_absent_from_compiled_module(reported: str) -> None:
    report = parse_audit_report(_report(f"theorem {reported}"), NONCE)

    assert report is not None
    assert [item.code for item in audit_diagnostics(report, ("target",))] == [
        "lean.undeclared_theorem"
    ]


def test_diagnostics_match_private_and_guillemet_names() -> None:
    report = parse_audit_report(
        _report(
            "theorem _private.Main.0.N.a",
            "theorem «e f»",
            "bound _private.Main.0.N.a",
            "bound «e f»",
        ),
        NONCE,
    )

    assert report is not None
    assert audit_diagnostics(report, ("a", "«e f»")) == []


def test_diagnostics_reject_compiled_type_that_differs_from_statement() -> None:
    report = parse_audit_report(_report("theorem t", "unbound t"), NONCE)

    assert report is not None
    assert [item.code for item in audit_diagnostics(report, ("t",))] == [
        "lean.statement_mismatch"
    ]


def test_diagnostics_reject_declared_theorem_without_restatement() -> None:
    report = parse_audit_report(_report("theorem t"), NONCE)

    assert report is not None
    assert [item.code for item in audit_diagnostics(report, ("t",))] == [
        "lean.statement_mismatch"
    ]


def test_diagnostics_reject_unbound_auxiliary_definition() -> None:
    report = parse_audit_report(_report("theorem t", "bound t", "unbound helper"), NONCE)

    assert report is not None
    assert [item.code for item in audit_diagnostics(report, ("t",))] == [
        "lean.statement_mismatch"
    ]


def test_diagnostics_reject_statement_that_needs_a_removed_command() -> None:
    report = parse_audit_report(_report("theorem t", "statement_error unknown n"), NONCE)

    assert report is not None
    assert [item.code for item in audit_diagnostics(report, ("t",))] == [
        "lean.statement_mismatch"
    ]


def test_reference_replaces_proofs_and_drops_outside_commands() -> None:
    reference = statement_reference(
        "import Mathlib\n"
        "open Filter\n"
        "variable (h : False)\n"
        "include h\n"
        "instance forged : OfNat Nat 2 := ⟨1⟩\n"
        "namespace N\n"
        "/-- doc -/\n"
        "def twice (n : Nat) : Nat := n + n\n"
        "@[simp] theorem t {a : Nat} (ha : 0 < a) :\n"
        "    twice a = a + a := by\n"
        "  rfl\n"
        "end N\n"
    )

    assert reference == (
        "open Filter\n"
        "namespace N\n"
        "def twice (n : Nat) : Nat := n + n\n"
        "theorem t {a : Nat} (ha : 0 < a) :\n"
        "    twice a = a + a := sorry\n"
        "end N\n"
    )


def test_reference_keeps_scoped_prefix_only_for_its_declaration() -> None:
    reference = statement_reference(
        "set_option maxHeartbeats 1000 in\n"
        "theorem t : True := trivial\n"
        "open Nat in\n"
        "instance forged : OfNat Nat 2 := ⟨1⟩\n"
        "theorem u : True := trivial\n"
    )

    assert reference == (
        "set_option maxHeartbeats 1000 in\n"
        "theorem t : True := sorry\n"
        "theorem u : True := sorry\n"
    )


def test_reference_reads_lets_and_match_alternatives() -> None:
    reference = statement_reference(
        "theorem t : let a := 1; a = a := rfl\n"
        "theorem u : ∀ n : Nat, n = n\n"
        "  | 0 => rfl\n"
        "  | _ + 1 => rfl\n"
    )

    assert reference == (
        "theorem t : let a := 1; a = a := sorry\n"
        "theorem u : ∀ n : Nat, n = n := sorry\n"
    )


@pytest.mark.parametrize(
    "statement",
    [
        "(μ m σ : ℝ) (h : 0 < σ) :\n    |μ - m| ≤ σ",
        "(x y : ℝ) :\n    |x - y| ≤ |x| + |y|",
        "(x y : ℝ) : x = y →\n    |x| ≤ 1 ∧\n    |y| ≤ 1",
        "(f : ℝ → ℝ) :\n    |f (fun x => x) 1| ≤ 1",
        "(x : ℝ) :\n    ‖x‖ ≤ 1",
    ],
)
def test_reference_keeps_line_leading_absolute_value_in_the_type(statement: str) -> None:
    assert statement_reference(f"theorem t {statement} := by\n  simp\n") == (
        f"theorem t {statement} := sorry\n"
    )
    assert statement_reference(f"noncomputable def pals_audit_0 {statement} := by\n  simp\n") == (
        f"noncomputable def pals_audit_0 {statement} := sorry\n"
    )


def test_reference_still_cuts_alternatives_whose_bodies_contain_assignments() -> None:
    assert statement_reference(
        "theorem t : ∀ n : Nat, n = n\n"
        "  | 0 => by have h := rfl; exact h\n"
        "  | n + 1 => by\n"
        "    have h := rfl\n"
        "    exact h\n"
    ) == "theorem t : ∀ n : Nat, n = n := sorry\n"


def test_reference_stays_fail_closed_when_a_bar_line_and_a_lambda_share_the_type() -> None:
    # The `=>` before `:=` makes the bar read as an alternative, so the restatement is cut short
    # and ends in a dangling `:`. It cannot elaborate, so a correct proof is rejected, never a
    # weaker statement accepted.
    reference = statement_reference(
        "theorem t (f : ℝ → ℝ) :\n    |f 0| ≤ 1 ∧ f = fun x => x := by\n  simp\n"
    )

    assert reference == "theorem t (f : ℝ → ℝ) : := sorry\n"


def test_reference_does_not_let_a_bar_weaken_the_statement() -> None:
    # A proof author cannot hide a conjunct behind a line-leading bar: the cut reference then
    # differs from what Lean checks, so the audit's type comparison rejects it.
    reference = statement_reference(
        "theorem t (x : ℝ) : x = x ∧\n  | 0 => rfl\n  False := by\n  simp\n"
    )

    assert reference == "theorem t (x : ℝ) : x = x ∧ := sorry\n"


def test_reference_blanks_comments_and_literals() -> None:
    reference = statement_reference('/--/ " -/\nmacro\n"\ntheorem t : True := trivial\n')

    assert reference is not None
    assert "macro" not in reference
    assert '"' not in reference


def test_reference_fails_closed_without_a_statement() -> None:
    assert statement_reference("theorem t := trivial\n") is None


def test_reference_skips_example_without_a_type_and_restates_typed_one() -> None:
    reference = statement_reference(
        "noncomputable def pals_audit_0 := 1\n"
        "noncomputable def pals_audit_1 : 1 = 1 := rfl\n"
    )

    assert reference == "noncomputable def pals_audit_1 : 1 = 1 := sorry\n"


class _Compiler:
    """Fake compile and audit processes while keeping the real verifier control flow."""

    def __init__(
        self,
        *,
        writes_artifact: bool = True,
        audit_stdout: str | None = None,
        audit_returncode: int = 0,
    ) -> None:
        self.writes_artifact = writes_artifact
        self.audit_stdout = audit_stdout
        self.audit_returncode = audit_returncode
        self.commands: list[list[str]] = []
        self.audit_source = ""

    def __call__(self, command: list[str], **_kwargs: object) -> lean_module._ProcessResult:
        self.commands.append(command)
        if "--run" in command:
            run = command.index("--run")
            self.audit_source = Path(command[run + 1]).read_text(encoding="utf-8")
            nonce = command[run + 2]
            stdout = (
                self.audit_stdout
                if self.audit_stdout is not None
                else _report("theorem t", "axiom propext", "bound t", nonce=nonce)
            )
            return _ok(stdout, self.audit_returncode)
        if "-o" in command and self.writes_artifact:
            Path(command[command.index("-o") + 1]).write_bytes(b"olean")
        return _ok()


@pytest.fixture
def compiler(monkeypatch: pytest.MonkeyPatch) -> _Compiler:
    fake = _Compiler()
    monkeypatch.setattr("pals_agent.lean.shutil.which", lambda binary, **_kw: f"/usr/bin/{binary}")
    monkeypatch.setattr(lean_module, "_run_limited_process", fake)
    return fake


def _run_commands(fake: _Compiler) -> list[list[str]]:
    # The child launcher's `--` is the last one; Linux also has an outer prlimit `--`.
    return [
        command[len(command) - command[::-1].index("--") :] for command in fake.commands
    ]


def test_verify_runs_compile_then_separate_trusted_audit(
    compiler: _Compiler, tmp_path: Path
) -> None:
    result = LeanVerifier(scratch_dir=tmp_path).verify("theorem t : True := trivial")

    assert result.success is True
    compile_command, audit_command = _run_commands(compiler)
    assert compile_command[-2:] == ["--threads=1", compile_command[-1]]
    assert Path(compile_command[-1]).name == "Main.lean"
    assert "-o" in compile_command
    assert "--run" in audit_command
    assert compiler.audit_source == TRUSTED_AUDIT_SOURCE
    assert [item.code for item in result.diagnostics] == ["lean.verified"]


def test_candidate_never_receives_the_nonce(compiler: _Compiler, tmp_path: Path) -> None:
    result = LeanVerifier(scratch_dir=tmp_path).verify("theorem t : True := trivial")

    compile_command, audit_command = _run_commands(compiler)
    nonce = audit_command[audit_command.index("--run") + 2]
    assert len(nonce) == 64
    assert nonce not in " ".join(compile_command)
    assert nonce not in result.stdout + result.stderr


def test_nonce_is_fresh_per_request(compiler: _Compiler, tmp_path: Path) -> None:
    verifier = LeanVerifier(scratch_dir=tmp_path)
    verifier.verify("theorem t : True := trivial")
    verifier.verify("theorem t : True := trivial")

    audits = [c for c in _run_commands(compiler) if "--run" in c]
    assert audits[0][audits[0].index("--run") + 2] != audits[1][audits[1].index("--run") + 2]


def test_exit_zero_without_artifact_is_rejected(compiler: _Compiler, tmp_path: Path) -> None:
    compiler.writes_artifact = False

    result = LeanVerifier(scratch_dir=tmp_path).verify("theorem t : True := trivial")

    assert result.success is False
    assert [item.code for item in result.diagnostics] == ["lean.trusted_audit_failed"]
    assert len(compiler.commands) == 1


@pytest.mark.parametrize(
    ("audit_stdout", "audit_returncode", "code"),
    [
        ("", 0, "lean.trusted_audit_failed"),
        (_report("theorem t", nonce="cd" * 32), 0, "lean.trusted_audit_failed"),
        (None, 1, "lean.trusted_audit_failed"),
    ],
)
def test_incomplete_audit_is_rejected(
    compiler: _Compiler,
    tmp_path: Path,
    audit_stdout: str | None,
    audit_returncode: int,
    code: str,
) -> None:
    compiler.audit_stdout = audit_stdout
    compiler.audit_returncode = audit_returncode

    result = LeanVerifier(scratch_dir=tmp_path).verify("theorem t : True := trivial")

    assert result.success is False
    assert [item.code for item in result.diagnostics] == [code]


def test_compile_error_skips_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def failing(command: list[str], **_kwargs: object) -> lean_module._ProcessResult:
        commands.append(command)
        return lean_module._ProcessResult(
            1, "/tmp/Main.lean:1:0: error: bad\n", "", False, False
        )

    monkeypatch.setattr("pals_agent.lean.shutil.which", lambda binary, **_kw: f"/usr/bin/{binary}")
    monkeypatch.setattr(lean_module, "_run_limited_process", failing)

    result = LeanVerifier(scratch_dir=tmp_path).verify("theorem t : True := trivial")

    assert result.success is False
    assert len(commands) == 1
    assert result.diagnostics[0].code == "lean.error"


def test_sketch_compiles_without_artifact_or_audit(compiler: _Compiler, tmp_path: Path) -> None:
    result = LeanVerifier(scratch_dir=tmp_path).verify_sketch(
        "theorem t : True := by\n  sorry"
    )

    assert result.success is True
    assert len(compiler.commands) == 1
    assert "-o" not in compiler.commands[0]


def test_example_is_audited_through_separate_named_compile(
    compiler: _Compiler, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compiled: list[str] = []
    fake = lean_module._run_limited_process

    def recording(command: list[str], **kwargs: object) -> lean_module._ProcessResult:
        if command[-1].endswith(".lean") and "--run" not in command:
            compiled.append(Path(command[-1]).read_text(encoding="utf-8"))
        return fake(command, **kwargs)

    monkeypatch.setattr(lean_module, "_run_limited_process", recording)
    source = "example : True := trivial"

    result = LeanVerifier(scratch_dir=tmp_path).verify(source)

    assert result.success is True
    assert compiled == [source, "noncomputable def pals_audit_0 : True := trivial"]
    assert "-o" not in _run_commands(compiler)[0]


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def test_admission_mode_runs_literal_receipt_command_before_audit_compile(
    compiler: _Compiler, tmp_path: Path
) -> None:
    project = _project(tmp_path)

    result = LeanVerifier(
        project_dir=project,
        scratch_dir=tmp_path,
        literal_admission_command=True,
    ).verify("theorem t : True := trivial")

    assert result.success is True
    literal, compile_for_audit, audit = _run_commands(compiler)
    assert literal[:2] == ["/usr/bin/lake", "env"]
    assert literal[2:4] == ["/usr/bin/lean", "--threads=1"]
    assert Path(literal[4]).name == "Main.lean"
    assert len(literal) == 5
    assert "-o" in compile_for_audit
    assert audit[:2] == ["/usr/bin/lake", "env"]
    assert "--run" in audit
    # The attested file keeps the source; the audit compile uses its own copy.
    assert Path(compile_for_audit[-1]).name == "Candidate.lean"
    # A receipt's closed diagnostic sequence stays byte-for-byte unchanged.
    assert [item.code for item in result.diagnostics] == ["lean.verified"]


def test_admission_mode_rejects_exit_zero_during_audit_compile(
    compiler: _Compiler, tmp_path: Path
) -> None:
    compiler.writes_artifact = False

    result = LeanVerifier(
        project_dir=_project(tmp_path),
        scratch_dir=tmp_path,
        literal_admission_command=True,
    ).verify("theorem t : True := trivial")

    assert result.success is False
    assert [item.code for item in result.diagnostics] == ["lean.trusted_audit_failed"]
