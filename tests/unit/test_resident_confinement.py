"""Confinement and supervision of the resident Lean, with the attacks a reviewer reproduced.

Linux only (Landlock, seccomp) and only with a pinned Lean: set PALS_RESIDENT_LEAN,
PALS_RESIDENT_LEAN_PATH and PALS_RESIDENT_CONFINED_ROOT (an empty directory the zygote may use
for request directories).  The attack sources run through the RESIDENT worker directly, i.e.
without the source policy that the verifier applies first: this tests the second line of defence.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
import time
from pathlib import Path

import pytest

from pals_agent.lean_audit import parse_audit_report
from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean, ResidentUnavailable
from pals_agent.lean_verifier.resident.manager import default_read_roots

REAL = pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or not os.environ.get("PALS_RESIDENT_LEAN")
    or not os.environ.get("PALS_RESIDENT_LEAN_PATH")
    or not os.environ.get("PALS_RESIDENT_CONFINED_ROOT"),
    reason="needs Linux, PALS_RESIDENT_LEAN, PALS_RESIDENT_LEAN_PATH, PALS_RESIDENT_CONFINED_ROOT",
)
GOOD = "import Mathlib\ntheorem t (a b : ℝ) : 0 ≤ a ^ 2 + b ^ 2 := by positivity\n"


@pytest.fixture(scope="module")
def resident(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    lean, lean_path = os.environ["PALS_RESIDENT_LEAN"], os.environ["PALS_RESIDENT_LEAN_PATH"]
    root = Path(os.environ["PALS_RESIDENT_CONFINED_ROOT"])
    instance = ResidentLean(
        ResidentConfig(
            lean_binary=lean,
            lean_path=lean_path,
            build_dir=tmp_path_factory.mktemp("conf-b"),
            max_children=10,
            confine=True,
            read_roots=default_read_roots(lean, lean_path),
            request_root=root,
            startup_timeout_s=180,
            queue_timeout_s=30,
        )
    )
    instance.start()
    yield instance
    instance.close()


def request_dir() -> Path:
    root = Path(os.environ["PALS_RESIDENT_CONFINED_ROOT"])
    directory = root / f"pals-lean-{secrets.token_hex(4)}"
    directory.mkdir()
    return directory


def run(resident: ResidentLean, body: str, *, olean: bool = False):  # type: ignore[no-untyped-def]
    directory = request_dir()
    source = directory / "Main.lean"
    source.write_text("import Mathlib\n" + body + "\n", encoding="utf-8")
    outcome = resident.compile(
        source, workdir=directory, olean=directory / "Main.olean" if olean else None, timeout_s=30
    )
    return directory, outcome


@REAL
def test_a_good_proof_compiles_and_is_audited_while_confined(resident: ResidentLean) -> None:
    directory = request_dir()
    source = directory / "Main.lean"
    source.write_text(GOOD, encoding="utf-8")
    olean = directory / "Main.olean"
    assert resident.compile(source, workdir=directory, olean=olean, timeout_s=60).returncode == 0
    reference = directory / "Statements.lean"
    reference.write_text("theorem t (a b : ℝ) : 0 ≤ a ^ 2 + b ^ 2 := sorry\n", encoding="utf-8")
    nonce = secrets.token_hex(16)
    audited = resident.audit(olean, reference, nonce, workdir=directory, timeout_s=60)
    assert parse_audit_report(audited.stdout, nonce) is not None


@REAL
def test_a_request_cannot_read_or_overwrite_another_requests_files(resident: ResidentLean) -> None:
    victim = request_dir()
    reference = victim / "Statements.lean"
    reference.write_text("theorem t : True := sorry\n", encoding="utf-8")
    (victim / "secret.txt").write_text("SECRET", encoding="utf-8")
    _, read = run(
        resident, f'#eval show IO Unit from do IO.println (← IO.FS.readFile "{victim}/secret.txt")'
    )
    assert "SECRET" not in read.stdout and "permission denied" in read.stdout
    _, write = run(resident, f'#eval show IO Unit from IO.FS.writeFile "{reference}" "tampered"')
    assert "permission denied" in write.stdout
    assert reference.read_text(encoding="utf-8") == "theorem t : True := sorry\n"


@REAL
def test_a_request_can_write_only_its_own_directory(resident: ResidentLean) -> None:
    directory = request_dir()
    source = directory / "Main.lean"
    source.write_text(
        f'import Mathlib\n#eval show IO Unit from IO.FS.writeFile "{directory}/ok.txt" "fine"\n',
        encoding="utf-8",
    )
    outcome = resident.compile(source, workdir=directory, olean=None, timeout_s=30)
    assert outcome.returncode == 0 and (directory / "ok.txt").read_text() == "fine"


@REAL
def test_a_request_cannot_signal_the_zygote_or_start_a_process(resident: ResidentLean) -> None:
    pid = resident._proc.pid  # noqa: SLF001
    kill = (
        "#eval show IO Unit from do discard <| IO.Process.output "
        f'{{cmd := "/bin/kill", args := #["-9", "{pid}"]}}'
    )
    _, outcome = run(resident, kill)
    assert "not permitted" in outcome.stdout and resident.alive()
    directory = request_dir()
    spawn = (
        "#eval show IO Unit from do discard <| IO.Process.output "
        f'{{cmd := "/bin/sh", args := #["-c", "echo x > {directory}/pwned"]}}'
    )
    _, outcome = run(resident, spawn)
    assert "not permitted" in outcome.stdout and not (directory / "pwned").exists()


@REAL
def test_oversized_output_files_end_the_child_and_the_next_request_works(
    resident: ResidentLean,
) -> None:
    directory = request_dir()
    big = (
        f'#eval show IO Unit from IO.FS.writeFile "{directory}/big.bin" '
        "(String.mk (List.replicate 40000000 'a'))"
    )
    _, outcome = run(resident, big)
    assert outcome.aborted or outcome.returncode != 0
    assert (
        not (directory / "big.bin").exists() or (directory / "big.bin").stat().st_size < 40_000_000
    )
    _, good = run(resident, "theorem t : True := trivial")
    assert good.returncode == 0


@REAL
def test_ten_concurrent_attacks_and_good_requests_do_not_disturb_each_other(
    resident: ResidentLean,
) -> None:
    victim = request_dir()
    reference = victim / "Statements.lean"
    reference.write_text("ref", encoding="utf-8")
    results: list[tuple[str, int]] = []
    attack = f'#eval show IO Unit from IO.FS.writeFile "{reference}" "tampered"'

    def worker(kind: str) -> None:
        body = attack if kind == "attack" else "theorem t : True := trivial"
        results.append((kind, run(resident, body)[1].returncode))

    threads = [
        threading.Thread(target=worker, args=("attack" if i % 2 else "good",)) for i in range(10)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(rc == 0 for kind, rc in results if kind == "good")
    assert all(rc == 1 for kind, rc in results if kind == "attack")
    assert reference.read_text(encoding="utf-8") == "ref" and resident.alive()


@REAL
def test_a_request_directory_outside_the_confined_root_is_refused(
    resident: ResidentLean, tmp_path: Path
) -> None:
    source = tmp_path / "Main.lean"
    source.write_text(GOOD, encoding="utf-8")
    with pytest.raises(ValueError):
        resident.compile(source, workdir=tmp_path, olean=None, timeout_s=5)


def test_a_broken_installation_becomes_unavailable_after_bounded_restarts(tmp_path: Path) -> None:
    started = time.monotonic()
    resident = ResidentLean(
        ResidentConfig(
            lean_binary="/bin/false",
            lean_path="",
            build_dir=tmp_path / "b",
            startup_timeout_s=1,
            allow_shim_compile=False,
            prebuilt_shim=Path(__file__),
        )
    )
    with pytest.raises(ResidentUnavailable):
        resident.start()
    assert time.monotonic() - started < 60 and not resident.alive()
    assert resident.restarts <= 6


@REAL
def test_a_request_cannot_read_the_process_files_of_other_requests(resident: ResidentLean) -> None:
    pid = resident._proc.pid  # noqa: SLF001
    probe = f'#eval show IO Unit from do IO.println (← IO.FS.readFile "/proc/{pid}/environ").length'
    _, outcome = run(resident, probe)
    assert "permission denied" in outcome.stdout
    _, own = run(
        resident,
        '#eval show IO Unit from do IO.println (← IO.FS.readFile "/proc/self/status").length',
    )
    assert own.returncode == 0
