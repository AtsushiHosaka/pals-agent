from __future__ import annotations

import shlex
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from pals_agent import lean_child
from pals_agent.lean import _limited_command


def test_runtime_paths_do_not_grant_the_host_root_or_daemon_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    binary = tmp_path / "lean"
    binary.write_bytes(b"validated-executable")
    monkeypatch.setenv("ELAN_HOME", str(tmp_path / "no-elan"))
    for key in ("LEAN_PATH", "LEAN_SRC_PATH", "LD_LIBRARY_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sysconfig, "get_config_var", lambda _: "test-linux-gnu")

    paths = lean_child._readable_runtime_paths([str(binary), "--threads=1"])

    assert binary in paths
    assert Path("/") not in paths
    assert not any(path.is_relative_to(root) for path in paths for root in (
        Path("/run"), Path("/proc"),
    ))
    assert tmp_path not in paths
    assert Path("/usr/bin") not in paths


@pytest.mark.parametrize("import_path", ["/", "/run", "/proc", "/unreviewed/imports"])
def test_unreviewed_library_paths_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, import_path: str,
) -> None:
    binary = tmp_path / "lean"
    binary.write_bytes(b"validated-executable")
    monkeypatch.setenv("ELAN_HOME", str(tmp_path / "no-elan"))
    monkeypatch.delenv("LEAN_PATH", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", import_path)

    with pytest.raises(ValueError, match="outside its runtime"):
        lean_child._readable_runtime_paths([str(binary)])


def test_operator_linked_elan_toolchain_is_a_runtime_without_granting_its_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    elan = tmp_path / "elan"
    active = elan / "toolchains/active"
    linked = tmp_path / "linked-native-runtime"
    for root in (active, linked):
        (root / "bin").mkdir(parents=True)
        (root / "lib/lean").mkdir(parents=True)
        (root / "bin/lean").write_bytes(b"validated-executable")
    (elan / "toolchains/development").symlink_to(linked, target_is_directory=True)
    monkeypatch.setenv("ELAN_HOME", str(elan))
    for key in ("LEAN_PATH", "LEAN_SRC_PATH", "LD_LIBRARY_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sysconfig, "get_config_var", lambda _: "test-linux-gnu")

    paths = lean_child._readable_runtime_paths([str(active / "bin/lean")])

    assert active in paths
    assert linked in paths
    assert elan not in paths
    assert tmp_path not in paths


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Landlock boundary")
def test_linux_child_reads_only_approved_inputs_and_its_own_scratch(tmp_path: Path) -> None:
    scratch = tmp_path / "request"
    scratch.mkdir()
    (scratch / "input.txt").write_text("allowed\n")
    outside = tmp_path / "unrelated-fixture.txt"
    outside.write_text("ordinary fixture\n")
    sibling = tmp_path / "other-request"
    sibling.mkdir()
    sibling_input = sibling / "input.txt"
    sibling_input.write_text("other request fixture\n")
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "lean-toolchain").write_text("reviewed fixture toolchain\n")
    (workspace / "lakefile.lean").write_text("reviewed fixture configuration\n")
    library_input = workspace / "approved-library-fixture"
    library_input.write_text("library fixture\n")
    (scratch / "outside-link").symlink_to(outside)
    probe = tmp_path / "reviewed-probe"
    probe.write_text(
        "#!/bin/sh\n"
        "IFS= read -r value < \"$TMPDIR/input.txt\" || exit 30\n"
        "[ \"$value\" = allowed ] || exit 31\n"
        "printf 'created\\n' > \"$TMPDIR/output.txt\" || exit 32\n"
        f"if (IFS= read -r value < {shlex.quote(str(outside))}); then exit 33; fi\n"
        "if (IFS= read -r value < \"$TMPDIR/outside-link\"); then exit 34; fi\n"
        f"if (IFS= read -r value < {shlex.quote(str(sibling_input))}); then exit 35; fi\n"
        f"if (printf changed > {shlex.quote(str(outside))}); then exit 36; fi\n"
        f"IFS= read -r value < {shlex.quote(str(library_input))} || exit 37\n"
        "[ \"$value\" = 'library fixture' ] || exit 38\n"
        f"if (printf changed > {shlex.quote(str(library_input))}); then exit 39; fi\n"
        "printf 'sandbox-ok\\n'\n",
    )
    probe.chmod(0o755)
    result = subprocess.run(
        _limited_command([str(probe), "env", "/bin/true"], timeout_seconds=10, scratch_dir=scratch),
        cwd=workspace,
        env={
            "PATH": "/usr/bin:/bin", "ELAN_HOME": str(tmp_path / "no-elan"),
            "HOME": str(scratch), "TMPDIR": str(scratch), "LANG": "C.UTF-8",
        },
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "sandbox-ok\n"
    assert (scratch / "output.txt").read_text() == "created\n"
    assert outside.read_text() == "ordinary fixture\n"
    assert sibling_input.read_text() == "other request fixture\n"
    assert library_input.read_text() == "library fixture\n"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Landlock boundary")
def test_linux_child_missing_executable_fails_closed(tmp_path: Path) -> None:
    result = subprocess.run(
        _limited_command([str(tmp_path / "missing")], timeout_seconds=10, scratch_dir=tmp_path),
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path)},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
    )

    assert result.returncode == 125
