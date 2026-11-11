"""Statement injection with the REAL Lean: the validator refuses it, and with the validator
bypassed the sandboxed processes still cannot act.

For every payload the test (1) checks the shared validator refuses the statement form, (2) runs the
attack as a Lean source WITHOUT the sandbox (``PALS_LEAN_SANDBOX=off``) to show the attack really
does something on this machine, and (3) runs the same source in the cold runner and in the warm
worker with the sandbox on and asserts it had no effect.

Needs the pinned Lean + Mathlib workspace and macOS ``sandbox-exec`` (skipped elsewhere: on
Linux the production verifier's Landlock/seccomp is the real containment).
"""

import os
import shutil
from pathlib import Path

import pytest

from pals_agent import automation_portfolio as ap
from pals_agent import general_recipe_lane as lane
from pals_agent import sandbox
from pals_agent.statement_grammar import StatementRejected, validate_proposition

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = Path(os.environ.get("PALS_LEAN_WORKSPACE", ROOT / "lean-workspace"))
LAKE = shutil.which("lake") or str(Path.home() / ".elan/bin/lake")
pytestmark = pytest.mark.skipif(
    not (WORKSPACE / ".lake/packages/mathlib").exists()
    or not Path(LAKE).exists()
    or not sandbox.available(),
    reason="needs the pinned Lean workspace and macOS sandbox-exec",
)


@pytest.fixture(scope="module")
def runner() -> lane.LeanRunner:
    return lane.LeanRunner.from_workspace(WORKSPACE, lake=LAKE)


def _write(marker: str) -> str:
    return f'IO.FS.writeFile "{marker}" "pwned"'


# name -> (statement as it would reach the validator, Lean source for the bypass run)
def payloads(marker: str) -> dict[str, tuple[str, str]]:
    codes = ", ".join(f"Char.ofNat {ord(c)}" for c in marker)
    return {
        "run_tac-in-term": (
            f"∀ n : ℕ, (by run_tac ({_write(marker)}) : n = n)",
            f"theorem t : ∀ n : ℕ, n = n := by\n  run_tac ({_write(marker)})\n  intro n; rfl\n",
        ),
        "let-by-suffix": (
            f"∀ n : ℕ, n = n := by run_tac ({_write(marker)})",
            f"theorem t : ∀ n : ℕ, n = n := by\n  run_tac ({_write(marker)})\n  intro n; rfl\n",
        ),
        "open-in": (
            "open Lean in ∀ n : ℕ, n = n",
            f"open Lean in run_cmd {_write(marker)}\ntheorem t : True := trivial\n",
        ),
        "set_option-in": (
            "set_option maxRecDepth 100000 in ∀ n : ℕ, n = n",
            f"set_option maxRecDepth 100000 in run_cmd {_write(marker)}\ntheorem t : True := trivial\n",
        ),
        "unsafe": (
            f"unsafe def u : IO Unit := {_write(marker)}",
            f"unsafe def u : IO Unit := {_write(marker)}\n#eval u\ntheorem t : True := trivial\n",
        ),
        "hash-eval": (
            f"#eval {_write(marker)}",
            f"#eval {_write(marker)}\ntheorem t : True := trivial\n",
        ),
        "char-obfuscation": (
            f"'{marker[0]}' = '{marker[0]}'",
            f'#eval IO.FS.writeFile (String.mk [{codes}]) "pwned"\ntheorem t : True := trivial\n',
        ),
        "string-literal": (
            f'"{marker}" = "{marker}"',
            f'#eval IO.FS.writeFile "{marker}" "pwned"\ntheorem t : True := trivial\n',
        ),
        "exec-touch": (
            "IO.Process.output = IO.Process.output",
            f'#eval do let _ ← IO.Process.output {{ cmd := "/usr/bin/touch", args := #["{marker}"] }}\n'
            "theorem t : True := trivial\n",
        ),
    }


def _fresh_marker(directory: Path, name: str) -> str:
    return str(directory / f"{name}.marker")


@pytest.mark.parametrize(
    "name",
    [
        "run_tac-in-term",
        "let-by-suffix",
        "open-in",
        "set_option-in",
        "unsafe",
        "hash-eval",
        "char-obfuscation",
        "string-literal",
        "exec-touch",
    ],
)
def test_injection_is_refused_and_has_no_effect_in_the_sandboxed_processes(
    name, runner, tmp_path, monkeypatch
):
    statement, bypass = payloads("/MARKER")[name]
    statement = statement.replace("/MARKER", "/tmp/x")
    with pytest.raises(StatementRejected):
        validate_proposition(statement)
    with pytest.raises(Exception) as caught:
        ap.check_formal_statement(statement)
    assert "Rejected" in type(caught.value).__name__

    # (2) unsandboxed: the attack source really acts on this machine
    marker_open = _fresh_marker(tmp_path, name + "-open")
    monkeypatch.setenv("PALS_LEAN_SANDBOX", "off")
    runner.run("import Mathlib\n" + payloads(marker_open)[name][1])
    assert Path(marker_open).exists(), "the attack must work without the sandbox"
    monkeypatch.delenv("PALS_LEAN_SANDBOX")

    # (3a) sandboxed cold runner
    marker_cold = _fresh_marker(tmp_path, name + "-cold")
    runner.run("import Mathlib\n" + payloads(marker_cold)[name][1])
    assert not Path(marker_cold).exists()

    # (3b) sandboxed warm worker
    marker_warm = _fresh_marker(tmp_path, name + "-warm")
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        worker.check(payloads(marker_warm)[name][1], timeout_s=60.0)
    finally:
        worker.close()
    assert not Path(marker_warm).exists()


def test_a_secret_outside_the_allowed_roots_cannot_be_read(runner, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    source = f'#eval do IO.println (← IO.FS.readFile "{secret}")\ntheorem t : True := trivial\n'
    _, out, _ = runner.run("import Mathlib\n" + source)
    assert "TOP-SECRET-VALUE" not in out


def test_the_environment_is_scrubbed_of_secrets(runner, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")
    source = '#eval do IO.println ((← IO.getEnv "OPENAI_API_KEY").getD "unset")\n'
    _, out, _ = runner.run("import Mathlib\n" + source)
    assert "sk-test-should-not-leak" not in out and "unset" in out


def test_a_runaway_process_is_killed_with_its_group_on_timeout(runner):
    short = lane.LeanRunner(runner.lean_binary, runner.lean_path, timeout_seconds=3.0)
    code, out, seconds = short.run("import Mathlib\n#eval (do while true do pure () : IO Unit)\n")
    assert code == 124 and out == "timeout" and seconds < 15


def test_the_warm_worker_runs_in_its_own_session_with_the_sandbox_applied(runner):
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        assert os.getpgid(worker.proc.pid) != os.getpgid(os.getpid())
        assert "sandbox-exec" in sandbox.describe()
    finally:
        worker.close()
