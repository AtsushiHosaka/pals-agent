from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_environment import LakeEnvironmentCache, VerificationTiming
from pals_agent.synthetic_geometry import _audit, proof_source


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


@pytest.mark.parametrize("native_binary", [False, True])
def test_real_lean_sorry_warning_is_never_verified(tmp_path: Path, native_binary: bool) -> None:
    lean_binary = _available_lean_binary()
    if native_binary:
        prefix = subprocess.run(
            [lean_binary, "--print-prefix"], capture_output=True, text=True,
            check=True, timeout=20,
        )
        lean_binary = str(Path(prefix.stdout.strip()) / "bin/lean")

    wrapper = tmp_path / "lean-with-injected-sorry"
    wrapper.write_text(
        "#!/bin/sh\n"
        "for input do :; done\n"
        "injected=\"$TMPDIR/injected.lean\"\n"
        "while IFS= read -r line || [ -n \"$line\" ]; do\n"
        "  printf '%s\\n' \"$line\"\n"
        "done < \"$input\" > \"$injected\"\n"
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


def test_real_mathlib_preserves_normal_and_cached_compilation() -> None:
    project_dir = _available_mathlib_project()
    source = (
        "import Mathlib\n"
        "theorem no_largest_natural : ¬ ∃ n : ℕ, ∀ m : ℕ, m ≤ n := by\n"
        "  rintro ⟨n, h⟩\n"
        "  have := h (n + 1)\n"
        "  omega\n"
    )
    assert LeanVerifier(project_dir=project_dir).verify(source).success
    prefix = subprocess.run(
        [_available_lean_binary(), "--print-prefix"], capture_output=True, text=True,
        check=True, timeout=20,
    )
    toolchain_bin = Path(prefix.stdout.strip()) / "bin"
    timings: list[VerificationTiming] = []
    cached = LeanVerifier(
        # Direct binaries avoid Elan's extra LEAN_RECURSION_COUNT key, which the
        # existing closed cache vocabulary deliberately does not accept.
        lean_binary=str(toolchain_bin / "lean"), lake_binary=str(toolchain_bin / "lake"),
        project_dir=project_dir, lake_environment_cache=LakeEnvironmentCache(),
        timing_observer=timings.append,
    )
    assert cached.verify(source).success
    assert cached.verify(source).success
    assert [t.cache_status for t in timings if t.stage == "environment_prepare"] == ["miss", "hit"]


def test_real_mathlib_preserves_reviewed_geometry_axiom_audit() -> None:
    project_dir = _available_mathlib_project()
    axioms, _ = _audit(LeanVerifier(project_dir=project_dir), proof_source())
    assert "isosceles_midpoint_perpendicular" in axioms


def _available_mathlib_project() -> Path:
    _available_lean_binary()
    value = os.environ.get("PALS_LEAN_PROJECT_DIR")
    if value is None or not (Path(value) / "lake-manifest.json").is_file():
        pytest.skip("An explicit pinned Mathlib project is not configured")
    return Path(value)
