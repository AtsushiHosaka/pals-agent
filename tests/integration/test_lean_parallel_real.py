"""Real Lean/Mathlib checks of overlapping compiles; opt in inside the Linux verifier image.

Set ``PALS_PARALLEL_REAL_PROJECT`` to the pinned workspace and ``PALS_PARALLEL_REAL_SCRATCH`` to a
bounded scratch directory.  Nothing here is mocked: each compile is the verifier's own child.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socket
import ssl
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from uuid import UUID

import pytest

from pals_agent.lean import (
    LeanCompileInterrupted,
    LeanVerifier,
    _limited_command,
    _run_limited_process,
    enable_orphan_reaping,
)
from pals_agent.lean_environment import LakeEnvironmentCache
from pals_agent.lean_verifier.http_server import (
    IsolatedVerifierHttpSettings,
    VerifierDeploymentBinding,
    create_server,
)
from pals_agent.models import VerificationResult

_TRUE = """import Mathlib.Algebra.BigOperators.Intervals
import Mathlib.Tactic.Ring
theorem pals_sum_odd (n : ℕ) : ∑ i ∈ Finset.range n, (2 * i + 1) = n ^ 2 := by
  induction n with
  | zero => simp
  | succ k ih => rw [Finset.sum_range_succ, ih]; ring
"""
_FALSE = """import Mathlib.Algebra.BigOperators.Intervals
import Mathlib.Tactic.Ring
theorem pals_sum_odd (n : ℕ) : ∑ i ∈ Finset.range n, (2 * i + 1) = n ^ 2 + 1 := by
  induction n with
  | zero => simp
  | succ k ih => rw [Finset.sum_range_succ, ih]; ring
"""
_SECRET = "pals-sibling-marker"


@pytest.fixture
def runtime() -> tuple[Path, Path]:
    project = os.environ.get("PALS_PARALLEL_REAL_PROJECT")
    scratch = os.environ.get("PALS_PARALLEL_REAL_SCRATCH")
    if not (project and scratch) or not sys.platform.startswith("linux"):
        pytest.skip("set PALS_PARALLEL_REAL_PROJECT/SCRATCH inside the Linux verifier image")
    return Path(project), Path(scratch)


def _verifier(runtime: tuple[Path, Path], *, cache: bool = False) -> LeanVerifier:
    project, scratch = runtime
    return LeanVerifier(
        project_dir=project,
        scratch_dir=scratch,
        lake_environment_cache=LakeEnvironmentCache() if cache else None,
    )


def _both(verifier: LeanVerifier, *sources: str) -> list[VerificationResult]:
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        return list(pool.map(verifier.verify, sources))


@pytest.mark.parametrize("cache", [False, True], ids=["lake-env", "reused-env"])
def test_concurrent_compiles_succeed_and_leave_no_scratch(
    runtime: tuple[Path, Path],
    cache: bool,
) -> None:
    results = _both(_verifier(runtime, cache=cache), _TRUE, _TRUE)
    assert [result.success for result in results] == [True, True], [
        (result.diagnostics, result.stderr[:500]) for result in results
    ]
    assert list(runtime[1].glob("pals-lean-*")) == []


@pytest.mark.parametrize("cache", [False, True], ids=["lake-env", "reused-env"])
@pytest.mark.parametrize(
    ("sources", "expected"),
    [((_FALSE, _TRUE), [False, True]), ((_TRUE, _FALSE), [True, False])],
    ids=["false-first", "true-first"],
)
def test_a_false_proof_beside_a_true_proof_keeps_each_verdict(
    runtime: tuple[Path, Path],
    cache: bool,
    sources: tuple[str, str],
    expected: list[bool],
) -> None:
    results = _both(_verifier(runtime, cache=cache), *sources)
    assert [result.success for result in results] == expected, [
        (result.diagnostics, result.stderr[:500]) for result in results
    ]
    false_result = results[expected.index(False)]
    assert any(item.severity == "error" for item in false_result.diagnostics)


def test_killing_one_compile_fails_only_that_compile(runtime: tuple[Path, Path]) -> None:
    verifier = _verifier(runtime)
    # A comment keeps the sources distinct, so the victim's scratch file can be told apart.
    victim_source = "-- pals-victim-compile\n" + _TRUE

    def kill_victim() -> bool:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            for main in runtime[1].glob("pals-lean-*/Main.lean"):
                if "pals-victim-compile" not in _read(main):
                    continue
                for pid in _pids_with_argument(str(main)):
                    os.kill(pid, signal.SIGKILL)
                    return True
            time.sleep(0.01)
        return False

    with ThreadPoolExecutor(max_workers=3) as pool:
        victim = pool.submit(verifier.verify, victim_source)
        survivor = pool.submit(verifier.verify, _TRUE)
        killed = pool.submit(kill_victim)
        assert killed.result() is True
        interrupted = victim.result()
        assert interrupted.success is False
        assert [item.code for item in interrupted.diagnostics] == ["lean.compile_interrupted"]
        assert survivor.result().success is True
    assert list(runtime[1].glob("pals-lean-*")) == []


def test_a_compile_cannot_reach_a_sibling_scratch_or_process(runtime: tuple[Path, Path]) -> None:
    """Run hostile Lean under the real child sandbox beside a live sibling scratch directory."""
    project, scratch = runtime
    if shutil.which("prlimit") is None:
        pytest.skip("Linux resource limiter is required")
    environment_base = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    with (
        tempfile.TemporaryDirectory(prefix="pals-lean-", dir=scratch) as sibling,
        tempfile.TemporaryDirectory(prefix="pals-lean-", dir=scratch) as own,
    ):
        secret = Path(sibling) / "Main.lean"
        secret.write_text(_SECRET, encoding="utf-8")
        program = Path(own) / "Probe.lean"
        program.write_text(_PROBE, encoding="utf-8")
        lean = shutil.which("lean")
        assert lean is not None
        result = _run_limited_process(
            _limited_command(
                [
                    lean,
                    "--run",
                    str(program),
                    str(secret),
                    str(Path(sibling) / "planted"),
                    f"/proc/{os.getpid()}/cmdline",
                ],
                timeout_seconds=120,
                scratch_dir=Path(own),
            ),
            cwd=project,
            environment={
                **environment_base,
                "PATH": os.environ["PATH"],
                "HOME": own,
                "TMPDIR": own,
                "ELAN_HOME": os.environ.get("ELAN_HOME", "/opt/elan"),
            },
            timeout_seconds=120,
            output_limit_bytes=65_536,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["read denied", "write denied", "proc denied"]
        assert _SECRET not in result.stdout
        assert not (Path(sibling) / "planted").exists()


def _pids_current() -> int:
    return int(Path("/sys/fs/cgroup/pids.current").read_text())


def _settled_pids(limit: int) -> int:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and _pids_current() > limit:
        time.sleep(0.05)
    return _pids_current()


def _run_hostile(
    runtime: tuple[Path, Path],
    own: str,
    *,
    children: int,
    parent_stays: bool,
    timeout: float,
):
    """Real Lean spawns detached and attached children that inherit its stdout."""
    project, _scratch = runtime
    sleeper = Path(own) / "Sleeper.lean"
    sleeper.write_text("def main : IO Unit := IO.sleep 120000\n", encoding="utf-8")
    program = Path(own) / "Hostile.lean"
    program.write_text(
        _HOSTILE.format(
            children=children,
            sleeper=str(sleeper),
            parent=("IO.sleep 120000" if parent_stays else "pure ()"),
        ),
        encoding="utf-8",
    )
    lean = shutil.which("lean")
    assert lean is not None
    return _run_limited_process(
        _limited_command(
            [lean, "--run", str(program)], timeout_seconds=timeout, scratch_dir=Path(own)
        ),
        cwd=project,
        environment={
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.environ["PATH"],
            "HOME": own,
            "TMPDIR": own,
            "ELAN_HOME": os.environ.get("ELAN_HOME", "/opt/elan"),
        },
        timeout_seconds=timeout,
        output_limit_bytes=65_536,
    )


def test_descendants_cannot_outlive_a_finished_compile_or_starve_a_sibling(
    runtime: tuple[Path, Path],
) -> None:
    baseline = _pids_current()
    with tempfile.TemporaryDirectory(prefix="pals-lean-", dir=runtime[1]) as own:
        started = time.monotonic()
        result = _run_hostile(runtime, own, children=20, parent_stays=False, timeout=90)
        elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr
    assert "spawned" in result.stdout
    assert elapsed < 30
    assert _settled_pids(baseline + 2) <= baseline + 2
    assert _verifier(runtime).verify(_TRUE).success is True


def test_deadline_kills_detached_descendants_and_a_starved_sibling_is_never_a_verdict(
    runtime: tuple[Path, Path],
) -> None:
    baseline = _pids_current()
    verifier = _verifier(runtime)
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        tempfile.TemporaryDirectory(prefix="pals-lean-", dir=runtime[1]) as own,
    ):
        hostile = pool.submit(
            _run_hostile,
            runtime,
            own,
            children=55,
            parent_stays=True,
            timeout=15,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and _pids_current() < baseline + 30:
            time.sleep(0.05)
        neighbour = verifier.verify(_TRUE)
        started = time.monotonic()
        result = hostile.result()
        assert time.monotonic() - started < 25
    assert result.timed_out is True
    # While PIDs are exhausted a true proof may be interrupted, never rejected.
    assert neighbour.success is True or [item.code for item in neighbour.diagnostics] == [
        "lean.compile_interrupted"
    ]
    assert _settled_pids(baseline + 2) <= baseline + 2
    assert verifier.verify(_TRUE).success is True


def test_killed_supervisor_is_an_interruption_and_its_descendants_are_reaped(
    runtime: tuple[Path, Path],
) -> None:
    baseline = _pids_current()
    enable_orphan_reaping()
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        tempfile.TemporaryDirectory(prefix="pals-lean-", dir=runtime[1]) as own,
    ):
        hostile = pool.submit(
            _run_hostile,
            runtime,
            own,
            children=5,
            parent_stays=True,
            timeout=60,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and _pids_current() < baseline + 6:
            time.sleep(0.02)
        supervisors = _pids_with_script("lean_supervisor.py")
        assert supervisors
        for pid in supervisors:
            os.kill(pid, signal.SIGKILL)
        started = time.monotonic()
        with pytest.raises(LeanCompileInterrupted):
            hostile.result()
        assert time.monotonic() - started < 5
    assert _settled_pids(baseline + 2) <= baseline + 2


def test_a_full_scratch_filesystem_fails_closed(runtime: tuple[Path, Path]) -> None:
    filler = runtime[1] / "pals-parallel-filler"
    try:
        with filler.open("wb") as stream, pytest.raises(OSError):
            while True:
                stream.write(b"\0" * (1024 * 1024))
                stream.flush()
        with pytest.raises(OSError):
            _verifier(runtime).verify(_TRUE)
    finally:
        filler.unlink(missing_ok=True)
    assert _verifier(runtime).verify(_TRUE).success is True


_PROBE = """
def attempt (label : String) (action : IO Unit) : IO Unit := do
  try
    action
    IO.println s!"{label} allowed"
  catch _ =>
    IO.println s!"{label} denied"

def main (args : List String) : IO UInt32 := do
  let [secret, planted, peer] := args | return 64
  attempt "read" (discard (IO.FS.readFile secret))
  attempt "write" (IO.FS.writeFile planted "planted")
  attempt "proc" (discard (IO.FS.readFile peer))
  return 0
"""


_HOSTILE = """
def main : IO Unit := do
  let lean ← IO.appPath
  for index in [0:{children}] do
    try
      discard <| IO.Process.spawn {{
        cmd := lean.toString, args := #["--run", "{sleeper}"], setsid := index % 2 == 0 }}
    catch _ => pure ()
  IO.println "spawned"
  (← IO.getStdout).flush
  {parent}
"""


def _pids_with_script(script: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal() or int(entry.name) == os.getpid():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(item.endswith(script.encode()) for item in arguments[:3]):
            found.append(int(entry.name))
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _pids_with_argument(argument: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
            executable = os.readlink(entry / "exe")
        except OSError:
            continue
        if argument.encode() in arguments and Path(executable).name.startswith("lean"):
            found.append(int(entry.name))
    return found


def test_real_server_runs_two_compiles_and_refuses_the_third_retryably(
    runtime: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    from tests.unit.test_isolated_verifier_http_server import (
        _admission_context,
        _create_certificates,
        _spki_sha256,
        _verify_request,
    )

    _create_certificates(tmp_path)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_3
    server_context.verify_mode = ssl.CERT_REQUIRED
    server_context.load_verify_locations(cafile=tmp_path / "ca.pem")
    server_context.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=tmp_path / "ca.pem")
    client_context.minimum_version = ssl.TLSVersion.TLSv1_3
    client_context.load_cert_chain(tmp_path / "client.pem", tmp_path / "client.key")
    settings = IsolatedVerifierHttpSettings(
        bind_host="127.0.0.1",
        binding=VerifierDeploymentBinding(
            release_id=UUID("018a3b10-514d-4d6d-845e-3f322b74bca0"),
            deployment_binding_sha256="a" * 64,
            verifier_image_digest="sha256:" + "b" * 64,
            verifier_toolchain_sha256="c" * 64,
        ),
        ssl_context=server_context,
        reconciler_client_spki_sha256=_spki_sha256((tmp_path / "client.der").read_bytes()),
        reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
        recipe_admission_context=_admission_context(),
        max_concurrent_compiles=2,
    )
    verifier = _verifier(runtime)
    server = create_server(settings, verifier=verifier)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            true_compile = pool.submit(_tls_request, client_context, _verify_request(_TRUE))
            false_compile = pool.submit(_tls_request, client_context, _verify_request(_FALSE))
            deadline = time.monotonic() + 30
            while len(list(runtime[1].glob("pals-lean-*"))) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            refused = _tls_request(client_context, _verify_request("third"))
            assert true_compile.result()[0] == 200
            assert false_compile.result()[0] == 422
        assert refused[0] == 503
        assert refused[1]["error_code"] == "verifier_unavailable"
        assert refused[1]["retryable"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _tls_request(context: ssl.SSLContext, raw_request: bytes) -> tuple[int, dict[str, object]]:
    with (
        socket.create_connection(("127.0.0.1", 18117), timeout=120) as raw,
        context.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(raw_request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        return response.status, json.loads(response.read())
