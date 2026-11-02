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
        _report("theorem N.target", "axiom propext", "axiom Quot.sound"), NONCE
    )

    assert report is not None
    assert audit_diagnostics(report, ("target",)) == []


@pytest.mark.parametrize(
    "axiom",
    ["sorryAx", "bad", "Lean.ofReduceBool", "Lean.trustCompiler", "b._native.native_decide.ax_1_1"],
)
def test_diagnostics_reject_every_other_axiom(axiom: str) -> None:
    report = parse_audit_report(_report("theorem t", f"axiom {axiom}"), NONCE)

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
    report = parse_audit_report(_report("theorem _private.Main.0.N.a", "theorem «e f»"), NONCE)

    assert report is not None
    assert audit_diagnostics(report, ("a", "«e f»")) == []


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
                else _report("theorem t", "axiom propext", nonce=nonce)
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
