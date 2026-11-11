# ruff: noqa: E501  (attack payloads are single-line statements)
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
import time
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
        # second independent review: `_root_` bypassed the identifier deny-list, `by_elab` runs code
        "by_elab-root-write": (
            f'(by_elab (do _root_.IO.FS.writeFile "{marker}" "pwned"; return _root_.Lean.mkNatLit 1) : ℕ) = 1',
            f'theorem t : (by_elab (do _root_.IO.FS.writeFile "{marker}" "pwned"; '
            "return _root_.Lean.mkNatLit 1) : ℕ) = 1 := sorry\n",
        ),
        "by_elab-char-obfuscated": (
            f"(by_elab (do _root_.IO.FS.writeFile (String.mk [{codes}]) (String.mk [Char.ofNat 120]); "
            "return _root_.Lean.mkNatLit 1) : ℕ) = 1",
            f"theorem t : (by_elab (do _root_.IO.FS.writeFile (String.mk [{codes}]) "
            "(String.mk [Char.ofNat 120]); return _root_.Lean.mkNatLit 1) : ℕ) = 1 := sorry\n",
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
        "by_elab-root-write",
        "by_elab-char-obfuscated",
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


# --- memory and CPU: the watchdog bounds the three kinds of Lean process --------------------------
HOG = "#eval (List.replicate 400000000 (1 : Nat)).length\n"


def test_a_memory_hog_is_killed_in_the_one_shot_runner(runner, monkeypatch):
    monkeypatch.setenv("PALS_LEAN_RSS_LIMIT_MB", "12000")
    code, out, seconds = runner.run("import Mathlib\n" + HOG)
    assert code == 137 and out == "killed:rss" and seconds < 120


def test_a_memory_hog_is_killed_in_the_streamed_run(runner, monkeypatch):
    monkeypatch.setenv("PALS_LEAN_RSS_LIMIT_MB", "12000")
    result = ap.run_stream(runner, "import Mathlib\n" + HOG, budget_s=120)
    assert result.reason == "rss" and result.seconds < 120


def test_a_memory_hog_kills_the_warm_worker_and_it_can_be_replaced(runner, monkeypatch):
    monkeypatch.setenv("PALS_LEAN_RSS_LIMIT_MB", "12000")
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        with pytest.raises(RuntimeError, match="rss"):
            worker.check(HOG, timeout_s=120)
        assert worker.killed_reason() == "rss" and not worker.alive()
        worker.restart()
        out, _ = worker.check("theorem t : (1 : ℕ) + 1 = 2 := rfl\n#print axioms t\n")
        assert "'t' does not depend on any axioms" in out
    finally:
        worker.close()


def test_the_warm_worker_has_a_cumulative_cpu_budget_after_which_it_is_recycled(
    runner, monkeypatch
):
    monkeypatch.setenv("PALS_LEAN_WORKER_CPU_S", "25")
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    heavy = (
        "theorem t : ∀ x y : ℝ, (x + y) ^ 4 ≤ 8 * (x ^ 4 + y ^ 4) := by\n"
        "  intro x y\n  nlinarith [sq_nonneg (x - y), sq_nonneg (x + y), sq_nonneg (x ^ 2 - y ^ 2)]\n"
    )
    try:
        with pytest.raises(RuntimeError, match="cpu"):
            for _ in range(200):  # every request burns CPU in the one shared process
                worker.check(heavy, timeout_s=60)
        assert worker.killed_reason() == "cpu"
    finally:
        worker.close()


# --- review #2, layer 2: the Lean-side allow-list (parse only, the statement is never elaborated)
LEAN_REFUSED = [
    "_root_.IO.FS.writeFile = _root_.IO.FS.writeFile",
    "∀ x : ℕ, _root_.Lean.Elab.Command.elabCommand x = x",
    "∀ x : ℕ, x = by_elab (_root_.IO.FS.writeFile (String.mk [Char.ofNat 112]) (String.mk [Char.ofNat 120]))",
    '(by_elab (do _root_.IO.FS.writeFile "/tmp/m" "pwned"; return _root_.Lean.mkNatLit 1) : ℕ) = 1',
    "type_of% x = x",
    "binop% HAdd.hAdd 1 2 = 3",
    "binrel% Eq 1 2",
    "∀ x : ℕ, x = %[x]",
    "ptrAddrUnsafe 1 = ptrAddrUnsafe 1",
    "dbgTrace = dbgTrace",
    "dbgTraceIfShared = dbgTraceIfShared",
    "Lean.Elab.Command.elabCommand = Lean.Elab.Command.elabCommand",
    "IO.println = IO.println",
    "∀ n : ℕ, (by run_tac (IO.println 1) : n = n)",
    "∀ n : ℕ, (by simp : n = n)",
    "∀ n : ℕ, n = n := by simp",
    "(show 1 = 1 from rfl)",
    "∀ x : ℕ, ⟨x, x⟩ = ⟨x, x⟩",
]
LEAN_ACCEPTED = [
    "∀ x : ℝ, 0 ≤ x ^ 2",
    "∑ i ∈ Finset.range 11, i = 55",
    "Real.sqrt 16 = 4",
    "∫ x in (0:ℝ)..1, x ^ 2 = 1 / 3",
    "Nat.choose 5 2 = 10",
    "Nat.gcd 12 18 = 6",  # `Nat.gcd` is @[extern]: refused by the first review-2 e2e, a legitimate loss
    "Continuous fun x : ℝ => x ^ 2 + 1",
    "∀ x y : ℝ, x * y = y * x",
]


@pytest.fixture(scope="module")
def checker(runner):
    worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    yield worker
    worker.close()


@pytest.mark.parametrize("statement", LEAN_REFUSED)
def test_the_lean_side_allow_list_refuses_the_payloads_with_the_python_layer_bypassed(
    checker, statement
):
    accepted, reason = checker.check_statement(statement)
    assert not accepted, f"accepted: {statement}"
    assert reason  # a reason is always given


@pytest.mark.parametrize("statement", LEAN_ACCEPTED)
def test_the_lean_side_allow_list_accepts_plain_mathematics(checker, statement):
    assert checker.check_statement(statement) == (True, "")


def test_a_refused_statement_is_never_elaborated(checker, tmp_path):
    marker = tmp_path / "elaborated"
    payload = (
        f'(by_elab (do _root_.IO.FS.writeFile "{marker}" "pwned"; '
        "return _root_.Lean.mkNatLit 1) : ℕ) = 1"
    )
    assert checker.check_statement(payload)[0] is False
    assert not marker.exists(), "the parse-only check must not run the statement's code"


# --- review #2: per-request fresh workers and the clean re-check, with the real Lean -------------
def _real_stage0(runner, model, **kw):
    from pals_agent import stage0

    made: list[ap.WarmWorker] = []

    def factory():
        worker = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
        made.append(worker)
        return worker

    class Idle:  # the shared worker is never used for a model statement
        def alive(self):
            return True

    stage = stage0.Stage0(Idle(), [], model, require_flags=False, worker_factory=factory, **kw)
    return stage, made


def _model(formal):
    def model(prompt, schema):
        props = schema["properties"]
        if "kind" in props:
            return {"kind": "prove", "formal": formal, "expression": "", "type": "none"}
        if "description" in props:
            return {"description": "plain words"}
        return {"checks": "", "faithful": True, "issue": ""}

    return model


def test_a_model_statement_is_proved_in_fresh_workers_and_rechecked_in_a_clean_one(runner):
    stage, made = _real_stage0(runner, _model("∀ x : ℝ, 0 ≤ x ^ 2"))
    t0 = time.monotonic()
    result = stage.run("x^2 is nonnegative", "en", budget_s=150.0)
    elapsed = time.monotonic() - t0
    assert result.outcome == "answered", (result.reason, result.gate)
    assert len(made) == 2 and all(w.proc.poll() is not None for w in made), "workers closed"
    print(f"per-request fresh workers: total {elapsed:.1f}s, start-up {made[0].startup_s:.1f}s")


def test_a_payload_in_a_model_statement_never_reaches_elaboration_in_any_worker(runner, tmp_path):
    marker = tmp_path / "pwned"
    payload = (
        f'(by_elab (do _root_.IO.FS.writeFile "{marker}" "pwned"; '
        "return _root_.Lean.mkNatLit 1) : ℕ) = 1"
    )
    stage, made = _real_stage0(runner, _model(payload))
    result = stage.run("anything", "en")
    assert result.outcome == "fallthrough"
    assert result.reason.startswith(("statement_not_plain", "statement_refused_by_lean_check"))
    assert not marker.exists()
    assert all(w.proc.poll() is not None for w in made)


def test_the_clean_verifier_rejects_a_proof_that_does_not_close_the_statement(runner):
    verifier = ap.WarmWorker(runner, ROOT / "scripts/eval/warm_worker.lean")
    try:
        claimed = ap.SolveResult(outcome="answered", route="portfolio", by="ring")
        ok, reason = ap.recheck(verifier, "∀ x : ℝ, 0 < x", claimed)
        assert not ok and reason in {"error_logged", "no_verdict", "nonstandard_axiom"}
        ok, _ = ap.recheck(
            verifier, "∀ x : ℝ, 0 ≤ x ^ 2", ap.SolveResult("answered", "portfolio", "positivity")
        )
        assert ok
    finally:
        verifier.close()
