from __future__ import annotations

import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pals_agent import lean as lean_module
from pals_agent.lean import LeanVerifier
from pals_agent.lean_environment import (
    LakeEnvironmentCache,
    VerificationTiming,
    environment_identity,
    materialize_lake_environment,
    parse_lake_environment,
)


def _base() -> dict[str, str]:
    return {"PATH": "/bin", "HOME": "/scratch/one/home", "TMPDIR": "/scratch/one"}


def _encoded(values: dict[str, str]) -> str:
    return "".join(f"{key}={value}\0" for key, value in values.items())


def test_preparation_retains_only_reviewed_deltas_and_no_request_state() -> None:
    base = _base()
    captured = {**base, "LEAN_PATH": "/trusted/mathlib", "PATH": "/lean/bin:/bin"}
    assert parse_lake_environment(_encoded(captured), base) == {
        "LEAN_PATH": "/trusted/mathlib", "PATH": "/lean/bin:/bin",
    }


@pytest.mark.parametrize("change", [
    {"AWS_ACCESS_KEY_ID": "credential"}, {"NEW_LAKE_KEY": "unreviewed"},
    {"HOME": "/old/home"}, {"TMPDIR": "/old/scratch"},
    {"LEAN_PATH": "/scratch/one/generated"},
])
def test_preparation_rejects_unreviewed_keys_and_stale_scratch(change: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        parse_lake_environment(_encoded({**_base(), **change}), _base())


@pytest.mark.parametrize("raw", ["", "PATH=/bin", "PATH=/bin\0PATH=/bin\0", "bad\0"])
def test_incomplete_or_duplicate_environment_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_lake_environment(raw, _base())


def test_default_lake_config_is_rebound_to_fresh_home() -> None:
    first = _base()
    captured = {**first, "LAKE_CONFIG": first["HOME"] + "/.lake/config.toml"}
    delta = parse_lake_environment(_encoded(captured), first)
    assert first["HOME"] not in str(delta)
    second = {**first, "HOME": "/scratch/two/home", "TMPDIR": "/scratch/two"}
    assert materialize_lake_environment(second, delta)["LAKE_CONFIG"] == (
        "/scratch/two/home/.lake/config.toml"
    )


def test_darwin_runtime_key_is_dropped_only_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {**_base(), "__CF_USER_TEXT_ENCODING": "0x1F5:0x0:0x0"}
    monkeypatch.setattr("pals_agent.lean_environment.sys.platform", "darwin")
    assert parse_lake_environment(_encoded(captured), _base()) == {}
    monkeypatch.setattr("pals_agent.lean_environment.sys.platform", "linux")
    with pytest.raises(ValueError):
        parse_lake_environment(_encoded(captured), _base())


def test_elan_proxy_hop_count_is_a_reviewed_delta() -> None:
    captured = {**_base(), "ELAN_TOOLCHAIN": "pinned", "LEAN_RECURSION_COUNT": "1"}
    assert parse_lake_environment(_encoded(captured), _base()) == {
        "ELAN_TOOLCHAIN": "pinned", "LEAN_RECURSION_COUNT": "1",
    }


@pytest.mark.parametrize("count", ["", "0", "01", "1 ", "2", "20", "one"])
def test_unexpected_elan_proxy_hop_count_is_rejected(count: str) -> None:
    captured = {**_base(), "LEAN_RECURSION_COUNT": count}
    with pytest.raises(ValueError, match="Elan recursion count"):
        parse_lake_environment(_encoded(captured), _base())


def _elan_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    (project / "lake-manifest.json").write_text(json.dumps({"packages": []}))
    (project / "lean-toolchain").write_text("pinned-toolchain")
    proxy = tmp_path / "elan/bin"
    proxy.mkdir(parents=True)
    # Elan installs one multiplexing executable under both names.
    for name in ("lake", "lean"):
        (proxy / name).write_text("elan-proxy")
    return project, proxy / "lean", proxy / "lake"


def _simulate_elan_compiler(
    monkeypatch: pytest.MonkeyPatch, *, lake_hops: int, rejects: tuple[int, ...] = (),
) -> list[tuple[list[str], dict[str, str]]]:
    """Replace only process execution; proxies add their hop as the real Elan does."""
    calls: list[tuple[list[str], dict[str, str]]] = []
    compiles: list[bool] = []
    monkeypatch.setattr(
        shutil, "which",
        lambda name, path=None: name if name.startswith("/") else f"/usr/bin/{name}",
    )

    def run(
        command: list[str], *, environment: dict[str, str], **_: object,
    ) -> lean_module._ProcessResult:
        argv = command[len(command) - command[::-1].index("--"):]
        calls.append((argv, environment))
        stdout = ""
        returncode = 0
        if argv[1:] == ["env", "/usr/bin/env", "-0"]:
            stdout = _encoded({
                **environment, "ELAN_TOOLCHAIN": "pinned", "LEAN_PATH": "/trusted/mathlib",
                "LEAN_RECURSION_COUNT": str(lake_hops),
            })
        elif "--run" in argv:
            nonce = argv[argv.index("--run") + 2]
            stdout = f"theorem target\nbound target\ncomplete {nonce}\n"
        else:
            compiles.append(True)
            returncode = 1 if len(compiles) in rejects else 0
            if "-o" in argv:
                Path(argv[argv.index("-o") + 1]).write_bytes(b"olean")
        return lean_module._ProcessResult(returncode, stdout, "", False, False)

    monkeypatch.setattr(lean_module, "_run_limited_process", run)
    return calls


def test_elan_path_hits_and_every_request_still_compiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, lean, lake = _elan_workspace(tmp_path)
    calls = _simulate_elan_compiler(monkeypatch, lake_hops=1, rejects=(3,))
    events: list[VerificationTiming] = []
    verifier = LeanVerifier(
        lean_binary=str(lean), lake_binary=str(lake), project_dir=project,
        scratch_dir=tmp_path, lake_environment_cache=LakeEnvironmentCache(),
        timing_observer=events.append,
    )

    source = "theorem target : True := by trivial"
    assert verifier.verify(source).success
    assert verifier.verify(source).success
    # The identical source is compiled again; the entry holds no earlier verdict.
    assert not verifier.verify(source).success

    assert [e.cache_status for e in events if e.stage == "environment_prepare"] == [
        "miss", "hit", "hit",
    ]
    assert calls[0][0][:2] == [str(lake), "env"]
    # The rejected third compile has no audit, and the audit also reuses the prepared environment.
    assert [("audit" if "--run" in argv else "compile", argv[0]) for argv, _ in calls[1:]] == [
        ("compile", str(lean)), ("audit", str(lean)),
        ("compile", str(lean)), ("audit", str(lean)),
        ("compile", str(lean)),
    ]
    compile_environments = [environment for argv, environment in calls[1:] if "--run" not in argv]
    assert [e["LEAN_RECURSION_COUNT"] for e in compile_environments] == ["1"] * 3
    assert len({e["HOME"] for e in compile_environments}) == 3


def test_unexpected_elan_hop_count_falls_back_to_original_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, lean, lake = _elan_workspace(tmp_path)
    calls = _simulate_elan_compiler(monkeypatch, lake_hops=2, rejects=(2,))
    events: list[VerificationTiming] = []
    verifier = LeanVerifier(
        lean_binary=str(lean), lake_binary=str(lake), project_dir=project,
        scratch_dir=tmp_path, lake_environment_cache=LakeEnvironmentCache(),
        timing_observer=events.append,
    )

    source = "theorem target : True := by trivial"
    assert verifier.verify(source).success
    assert not verifier.verify(source).success

    assert [e.cache_status for e in events if e.stage == "environment_prepare"] == [
        "fallback", "fallback",
    ]
    compiled = [
        (argv[:3], environment) for argv, environment in calls
        if "--threads=1" in argv and "--run" not in argv
    ]
    assert [argv for argv, _ in compiled] == [[str(lake), "env", str(lean)]] * 2
    assert all("LEAN_RECURSION_COUNT" not in environment for _, environment in compiled)


def test_cache_has_one_immutable_entry_and_lifecycle_reset() -> None:
    cache = LakeEnvironmentCache()
    prepared = {"LEAN_PATH": "/first"}
    first, status = cache.get_or_prepare("first", lambda: prepared)
    assert status == "miss"
    first["LEAN_PATH"] = "/caller-mutated"
    prepared["LEAN_PATH"] = "/producer-mutated"
    hit, status = cache.get_or_prepare("first", lambda: pytest.fail("unexpected preparation"))
    assert (hit, status) == ({"LEAN_PATH": "/first"}, "hit")
    assert cache.get_or_prepare("second", lambda: {"LEAN_PATH": "/second"})[1] == "miss"
    cache.clear()
    assert cache.get_or_prepare("second", lambda: {}) == ({}, "miss")


def test_failed_replacement_does_not_keep_an_old_environment() -> None:
    cache = LakeEnvironmentCache()
    cache.get_or_prepare("first", lambda: {"LEAN_PATH": "/first"})

    def fail() -> dict[str, str]:
        raise ValueError("failed preparation")

    with pytest.raises(ValueError):
        cache.get_or_prepare("second", fail)
    assert cache.get_or_prepare("first", lambda: {}) == ({}, "miss")


def test_concurrent_preparation_is_single_flight() -> None:
    cache = LakeEnvironmentCache()
    barrier = threading.Barrier(4)
    calls: list[bool] = []

    def prepare() -> dict[str, str]:
        calls.append(True)
        return {"LEAN_PATH": "/trusted"}

    def run() -> tuple[dict[str, str], str]:
        barrier.wait(timeout=3)
        return cache.get_or_prepare("same", prepare)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: run(), range(4)))
    assert len(calls) == 1
    assert sorted(status for _, status in results) == ["hit", "hit", "hit", "miss"]
    assert all(value == {"LEAN_PATH": "/trusted"} for value, _ in results)


def test_environment_identity_invalidation_and_source_independence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / ".lake/packages/mathlib"
    package.mkdir(parents=True)
    (project / "lake-manifest.json").write_text(json.dumps({
        "packages": [{"type": "git", "name": "mathlib", "subDir": None, "rev": "pinned"}],
    }))
    (project / "lean-toolchain").write_text("pinned-toolchain")
    (project / "lakefile.lean").write_text("pinned-config")
    (package / "lakefile.lean").write_text("pinned-dependency")
    binary = tmp_path / "lean"
    binary.write_text("pinned-binary")

    def identity() -> str:
        return environment_identity(project, str(binary), str(binary), _base())

    previous = identity()
    # Fresh compilation, not this key, owns source/import/.olean validity.
    (project / "Main.lean").write_text("import Mathlib\ntheorem changed : False := by trivial")
    assert identity() == previous
    for path in (project / "lean-toolchain", project / "lakefile.lean",
                 package / "lakefile.lean", binary):
        path.write_text(path.read_text() + "changed")
        current = identity()
        assert current != previous
        previous = current
    compiled_config = package / ".lake/lakefile.olean"
    compiled_config.parent.mkdir()
    compiled_config.write_bytes(b"changed-executable-config")
    assert identity() != previous


def test_external_package_topology_is_not_cached(tmp_path: Path) -> None:
    (tmp_path / "lake-manifest.json").write_text(json.dumps({
        "packages": [], "packagesDir": "../external",
    }))
    with pytest.raises(ValueError, match="external Lake packages"):
        environment_identity(tmp_path, "/bin/true", "/bin/true", _base())


def test_dependency_symlink_cannot_escape_read_only_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    packages = project / ".lake/packages"
    packages.mkdir(parents=True)
    outside = tmp_path / "mutable-dependency"
    outside.mkdir()
    (packages / "mathlib").symlink_to(outside, target_is_directory=True)
    (project / "lake-manifest.json").write_text(json.dumps({
        "packages": [{"type": "git", "name": "mathlib", "subDir": None}],
    }))
    with pytest.raises(ValueError, match="external Lake dependency"):
        environment_identity(project, "/bin/true", "/bin/true", _base())
