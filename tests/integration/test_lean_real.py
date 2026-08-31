from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier


def test_real_lean_accepts_a_hole_free_verified_source() -> None:
    lean_binary = _available_lean_binary()

    result = LeanVerifier(
        lean_binary=lean_binary,
        elan_home=str(Path(lean_binary).parent.parent),
    ).verify(
        "theorem verified_reflexivity : 1 = 1 := by\n"
        "  rfl\n"
    )

    assert result.success is True
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["lean.verified"]


def test_real_lean_sorry_warning_is_never_verified(tmp_path: Path) -> None:
    lean_binary = _available_lean_binary()

    wrapper = tmp_path / "lean-with-injected-sorry"
    wrapper.write_text(
        "#!/bin/sh\n"
        "for input do :; done\n"
        "injected=\"$TMPDIR/injected.lean\"\n"
        "/bin/cp \"$input\" \"$injected\"\n"
        "/bin/chmod u+w \"$injected\"\n"
        "printf '\\n%s\\n' "
        "'theorem injectedUnsound : False := by sorry' >> \"$injected\"\n"
        f"exec {shlex.quote(lean_binary)} \"$injected\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = LeanVerifier(
        lean_binary=str(wrapper),
        elan_home=str(Path(lean_binary).parent.parent),
    ).verify(
        "example : True := by exact True.intro"
    )

    assert result.success is False
    assert any(
        diagnostic.code == "lean.declaration_uses_sorry"
        for diagnostic in result.diagnostics
    )
    assert all(diagnostic.code != "lean.verified" for diagnostic in result.diagnostics)


def _available_lean_binary() -> str:
    lean_binary = shutil.which("lean")
    if lean_binary is None:
        pytest.skip("Lean is not installed")
    try:
        probe = subprocess.run(
            [lean_binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("Lean toolchain is not available")
    if probe.returncode != 0:
        pytest.skip("Lean toolchain is not available")
    return lean_binary
