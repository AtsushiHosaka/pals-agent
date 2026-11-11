"""Resident Lean: derivation of the warm audit (always) and the real worker (needs a pinned Lean).

The real tests start a Mathlib process, so they run only when ``PALS_RESIDENT_LEAN`` (the pinned
``lean`` binary) and ``PALS_RESIDENT_LEAN_PATH`` (its ``LEAN_PATH``) are set.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pals_agent.lean_audit import TRUSTED_AUDIT_SOURCE, parse_audit_report
from pals_agent.lean_verifier.resident import (
    ResidentBusy,
    ResidentConfig,
    ResidentLean,
    ResidentUnavailable,
)
from pals_agent.lean_verifier.resident.manager import render_worker_source, warm_audit_source

REAL = pytest.mark.skipif(
    not os.environ.get("PALS_RESIDENT_LEAN") or not os.environ.get("PALS_RESIDENT_LEAN_PATH"),
    reason="needs PALS_RESIDENT_LEAN and PALS_RESIDENT_LEAN_PATH (pinned Lean 4.32 + Mathlib)",
)


def test_warm_audit_differs_from_the_trusted_audit_only_at_two_anchors() -> None:
    warm = warm_audit_source()
    original_lines = TRUSTED_AUDIT_SOURCE.split("unsafe def main", 1)[1].splitlines()[1:]
    warm_lines = warm.split("\n", 1)[1].splitlines()
    removed = [line for line in original_lines if line not in warm_lines]
    added = [line for line in warm_lines if line not in original_lines]
    assert removed == [
        "  enableInitializersExecution",
        "  let env ← importModules mod.imports {} 0 (loadExts := true)",
    ]
    assert len(added) == 2
    assert "Lean.Elab.process input env {}" in warm
    for kept in ("env.replay constants", "collectAxioms name", "complete {nonce}"):
        assert kept in warm


def test_warm_audit_refuses_a_changed_trusted_audit() -> None:
    with pytest.raises(ValueError):
        warm_audit_source(TRUSTED_AUDIT_SOURCE.replace("  enableInitializersExecution\n", ""))
    with pytest.raises(ValueError):
        duplicated = (
            "\n  enableInitializersExecution\n"
            "  let env ← importModules mod.imports {} 0 (loadExts := true)\n"
        )
        warm_audit_source(TRUSTED_AUDIT_SOURCE + duplicated)


def test_worker_source_has_no_unfilled_placeholder() -> None:
    source = render_worker_source()
    assert "{{" not in source
    assert "auditWarm" in source and "checkWarm" in source


def test_statement_check_source_is_the_one_of_the_measurement_worker() -> None:
    from pals_agent.lean_verifier.resident.manager import STATEMENT_CHECK_SOURCE

    original = (Path(__file__).resolve().parents[2] / "scripts/eval/warm_worker.lean").read_text()
    start = original.index("/-- Syntax node kinds a proposition")
    segment = original[start : original.index("unsafe def run")]
    assert segment.rstrip() in STATEMENT_CHECK_SOURCE.read_text(encoding="utf-8")


def test_requests_fail_closed_when_not_started(tmp_path: Path) -> None:
    resident = ResidentLean(
        ResidentConfig(
            lean_binary="lean", lean_path="", build_dir=tmp_path / "b", allow_unconfined=True
        )
    )
    with pytest.raises(ResidentUnavailable):
        resident.compile(tmp_path / "x.lean", workdir=tmp_path, olean=None, timeout_s=1)
    assert not resident.alive()


# ------------------------------------------------------------------ real Lean


@pytest.fixture(scope="module")
def resident(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    config = ResidentConfig(
        lean_binary=os.environ["PALS_RESIDENT_LEAN"],
        lean_path=os.environ["PALS_RESIDENT_LEAN_PATH"],
        build_dir=tmp_path_factory.mktemp("resident-build"),
        max_children=4,
        queue_timeout_s=0.2,
        child_cpu_seconds=60,
        allow_unconfined=True,
    )
    instance = ResidentLean(config)
    instance.start()
    yield instance
    instance.close()


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


GOOD = "import Mathlib\ntheorem t (a b : ℝ) : 0 ≤ a ^ 2 + b ^ 2 := by positivity\n"
BAD = "import Mathlib\ntheorem t : (1 : ℕ) = 2 := by simp\n"


@REAL
def test_good_proof_compiles_and_is_audited(resident: ResidentLean, tmp_path: Path) -> None:
    source = _write(tmp_path, "Main.lean", GOOD)
    olean = tmp_path / "Main.olean"
    compiled = resident.compile(source, workdir=tmp_path, olean=olean, timeout_s=60)
    assert (compiled.returncode, compiled.stdout) == (0, "")
    assert olean.is_file()
    statement = "theorem t (a b : ℝ) : 0 ≤ a ^ 2 + b ^ 2 := sorry\n"
    reference = _write(tmp_path, "Statements.lean", statement)
    nonce = secrets.token_hex(16)
    audited = resident.audit(olean, reference, nonce, workdir=tmp_path, timeout_s=60)
    report = parse_audit_report(audited.stdout, nonce)
    assert audited.returncode == 0 and report is not None
    assert "t" in report.theorems and "t" in report.bound and not report.unbound
    assert set(report.axioms) <= {"propext", "Classical.choice", "Quot.sound"}


@REAL
def test_failing_proof_reports_the_compiler_error(resident: ResidentLean, tmp_path: Path) -> None:
    source = _write(tmp_path, "Main.lean", BAD)
    outcome = resident.compile(source, workdir=tmp_path, olean=None, timeout_s=60)
    assert outcome.returncode == 1
    assert "error" in outcome.stdout and str(source) in outcome.stdout


@REAL
def test_statement_check_accepts_a_plain_proposition_and_refuses_code(
    resident: ResidentLean, tmp_path: Path
) -> None:
    assert resident.check_statement("∀ n : ℕ, n + 0 = n", workdir=tmp_path) == (True, "")
    accepted, reason = resident.check_statement("(by exact trivial : True)", workdir=tmp_path)
    assert not accepted and "syntax kind" in reason
    accepted, reason = resident.check_statement("IO.Process.exit 0 = 0", workdir=tmp_path)
    assert not accepted


@REAL
def test_other_imports_are_not_served(resident: ResidentLean, tmp_path: Path) -> None:
    source = _write(tmp_path, "Main.lean", "import Mathlib.Data.Nat.Defs\nexample : 1 = 1 := rfl\n")
    outcome = resident.compile(source, workdir=tmp_path, olean=None, timeout_s=60)
    assert outcome.unsupported


@REAL
def test_a_hanging_request_is_killed_and_the_next_one_is_unaffected(
    resident: ResidentLean, tmp_path: Path
) -> None:
    loop = (
        "import Mathlib\nset_option maxHeartbeats 0 in\n"
        "theorem t : True := by\n  repeat (first | skip)\n"
    )
    # `repeat skip` loops forever without allocating much; only the deadline can stop it.
    source = _write(tmp_path, "Loop.lean", loop)
    started = time.monotonic()
    outcome = resident.compile(source, workdir=tmp_path, olean=None, timeout_s=3)
    assert outcome.timed_out and time.monotonic() - started < 10
    good = _write(tmp_path, "Main.lean", GOOD)
    assert resident.compile(good, workdir=tmp_path, olean=None, timeout_s=60).returncode == 0


@REAL
def test_no_state_leaks_between_requests(resident: ResidentLean, tmp_path: Path) -> None:
    # Request A declares `leak`; request B must not see it, even immediately afterwards.
    a = _write(tmp_path, "A.lean", "import Mathlib\ntheorem leak : True := trivial\n")
    b = _write(tmp_path, "B.lean", "import Mathlib\n#check leak\n")
    assert resident.compile(a, workdir=tmp_path, olean=None, timeout_s=60).returncode == 0
    outcome = resident.compile(b, workdir=tmp_path, olean=None, timeout_s=60)
    assert outcome.returncode == 1 and "unknown identifier" in outcome.stdout.lower()


@REAL
def test_a_killed_zygote_is_restarted_and_inflight_work_is_an_interruption(
    resident: ResidentLean, tmp_path: Path
) -> None:
    proc = resident._proc  # noqa: SLF001
    assert proc is not None
    os_kill = __import__("os").kill
    os_kill(proc.pid, 9)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline and not (resident.alive() and resident._proc is not proc):  # noqa: SLF001
        time.sleep(0.5)
    assert resident.alive() and resident.restarts >= 1
    source = _write(tmp_path, "Main.lean", GOOD)
    assert resident.compile(source, workdir=tmp_path, olean=None, timeout_s=60).returncode == 0


_ = (ResidentBusy, subprocess)


class _AliveStub:
    def __init__(self, lean_binary: str, project_dir: Path | None, limit: int) -> None:
        from types import SimpleNamespace

        self.config = SimpleNamespace(
            lean_binary=lean_binary,
            project_dir=project_dir,
            output_limit_bytes=limit,
            confine=True,
        )

    def alive(self) -> bool:
        return True


def test_the_verifier_uses_the_resident_only_in_its_own_environment(tmp_path: Path) -> None:
    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_profiles import resolve_profile

    lean = tmp_path / "lean"
    lean.write_text("#!/bin/sh\n")
    lean.chmod(0o755)
    other = tmp_path / "other"
    other.write_text("#!/bin/sh\n")
    other.chmod(0o755)
    project = tmp_path / "ws"
    project.mkdir()
    limit = LeanVerifier().output_limit_bytes
    stub = _AliveStub(str(lean), project, limit)

    def verifier(**kwargs):  # type: ignore[no-untyped-def]
        return LeanVerifier(lean_binary=str(lean), project_dir=project, resident=stub, **kwargs)

    assert verifier()._resident_usable() is stub  # noqa: SLF001
    assert verifier(library_profile=resolve_profile())._resident_usable() is stub  # noqa: SLF001
    assert verifier(literal_admission_command=True)._resident_usable() is None  # noqa: SLF001
    # another toolchain, another project, or a looser output limit than the verifier's own
    foreign_lean = LeanVerifier(lean_binary=str(other), project_dir=project, resident=stub)
    assert foreign_lean._resident_usable() is None  # noqa: SLF001
    foreign_project = LeanVerifier(lean_binary=str(lean), project_dir=tmp_path, resident=stub)
    assert foreign_project._resident_usable() is None  # noqa: SLF001
    loose = _AliveStub(str(lean), project, limit * 2)
    looser = LeanVerifier(lean_binary=str(lean), project_dir=project, resident=loose)
    assert looser._resident_usable() is None  # noqa: SLF001
    assert LeanVerifier()._resident_usable() is None  # noqa: SLF001
    if sys.platform.startswith("linux"):
        unconfined = _AliveStub(str(lean), project, limit)
        unconfined.config.confine = False
        bare = LeanVerifier(lean_binary=str(lean), project_dir=project, resident=unconfined)
        assert bare._resident_usable() is None  # noqa: SLF001


@REAL
def test_close_kills_running_request_children(tmp_path: Path) -> None:
    config = ResidentConfig(
        lean_binary=os.environ["PALS_RESIDENT_LEAN"],
        lean_path=os.environ["PALS_RESIDENT_LEAN_PATH"],
        build_dir=tmp_path / "b",
        startup_timeout_s=180,
        allow_unconfined=True,
    )
    instance = ResidentLean(config)
    instance.start()
    loop = _write(
        tmp_path,
        "Loop.lean",
        "import Mathlib\nset_option maxHeartbeats 0 in\n"
        "theorem t : True := by\n  repeat (first | skip)\n",
    )
    outcomes: list[object] = []
    thread = threading.Thread(
        target=lambda: outcomes.append(
            instance.compile(loop, workdir=tmp_path, olean=None, timeout_s=120)
        )
    )
    thread.start()
    deadline = time.monotonic() + 30
    while not instance._children and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.05)
    children = set(instance._children)  # noqa: SLF001
    assert children
    instance.close()
    thread.join(timeout=30)
    time.sleep(0.5)
    for pid in children:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert outcomes and outcomes[0].aborted  # type: ignore[attr-defined]


@REAL
def test_a_prebuilt_shim_needs_no_compiler_at_run_time(tmp_path: Path) -> None:
    from pals_agent.lean_verifier.resident.manager import compile_shim

    lean = os.environ["PALS_RESIDENT_LEAN"]
    shim = tmp_path / "image" / "shim.so"
    compile_shim(lean, shim)
    instance = ResidentLean(
        ResidentConfig(
            lean_binary=lean,
            lean_path=os.environ["PALS_RESIDENT_LEAN_PATH"],
            build_dir=tmp_path / "run",
            prebuilt_shim=shim,
            allow_shim_compile=False,
            startup_timeout_s=180,
            allow_unconfined=True,
        )
    )
    instance.start()
    try:
        source = _write(tmp_path, "Main.lean", GOOD)
        assert instance.compile(source, workdir=tmp_path, olean=None, timeout_s=60).returncode == 0
        assert not list((tmp_path / "run").glob("*.so")) and not list(
            (tmp_path / "run").glob("*.dylib")
        )
    finally:
        instance.close()


def test_an_unconfined_resident_cannot_be_built_on_linux_by_default(tmp_path: Path) -> None:
    config = ResidentConfig(lean_binary="lean", lean_path="", build_dir=tmp_path / "b")
    if sys.platform.startswith("linux"):
        with pytest.raises(ValueError):
            ResidentLean(config)
    else:  # development hosts may run unconfined
        ResidentLean(config)
    import dataclasses

    explicit = dataclasses.replace(config, allow_unconfined=True)
    ResidentLean(explicit)  # the explicit development switch


def test_confinement_is_reported_unavailable_without_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    from pals_agent.lean_verifier.resident import confinement_available

    monkeypatch.setattr(sys, "platform", "darwin")
    ok, reason = confinement_available()
    assert not ok and "Linux" in reason


def test_start_refuses_confinement_that_the_host_cannot_provide(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import pals_agent.lean_verifier.resident.manager as manager

    monkeypatch.setattr(manager, "confinement_available", lambda: (False, "no Landlock"))
    resident = ResidentLean(
        ResidentConfig(
            lean_binary="lean",
            lean_path="",
            build_dir=tmp_path / "b",
            confine=True,
            request_root=tmp_path,
        )
    )
    with pytest.raises(ResidentUnavailable, match="no Landlock"):
        resident.start()


def test_the_self_test_rejects_children_that_can_write_another_requests_directory(
    tmp_path: Path,
) -> None:
    class Leaky(ResidentLean):
        def compile(self, source, *, workdir, olean, timeout_s, cancel=None):  # type: ignore[no-untyped-def]
            from pals_agent.lean_verifier.resident.manager import CompileOutcome

            text = source.read_text()
            for path in re.findall(r'writeFile "([^"]+)"', text):
                Path(path).write_text("x")  # an unconfined child writes everywhere
            return CompileOutcome(0, "")

    import re

    resident = Leaky(
        ResidentConfig(
            lean_binary="lean",
            lean_path="",
            build_dir=tmp_path / "b",
            confine=True,
            request_root=tmp_path,
            allow_unconfined=True,
        )
    )
    with pytest.raises(ResidentUnavailable, match="not confined"):
        resident._confinement_self_test()  # noqa: SLF001
