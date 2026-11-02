"""Real-compiler regressions for elaboration-time forgery.

Most cases patch out the source policy on purpose: each layer must hold on its own, and these prove
the trusted audit against sources that Lean really exits from or really accepts.

Mathlib cases need ``PALS_FORGERY_MATHLIB_PROJECT`` with ``PALS_FORGERY_LEAN`` and
``PALS_FORGERY_LAKE`` naming the pinned toolchain binaries.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import pals_agent.lean as lean_module
from pals_agent.lean import LeanVerifier
from pals_agent.lean_environment import LakeEnvironmentCache
from pals_agent.models import VerificationResult

FORGED = "theorem forged_false : (1 : Nat) = 2 := by simp\n"
EXIT = "(IO.Process.exit 0 : IO Unit)"
EXIT_SOURCES = {
    "exact_exploit": f"open Nat in #eval {EXIT}\n{FORGED}",
    "section_wrapped": f"section\n#eval {EXIT}\nend\n{FORGED}",
    "run_cmd": f"import Lean\nrun_cmd {EXIT}\n{FORGED}",
    "run_elab": f"import Lean\nrun_elab {EXIT}\n{FORGED}",
    "run_meta": f"import Lean\nopen Nat in run_meta {EXIT}\n{FORGED}",
    "run_tac": f"import Lean\ntheorem forged_false : (1 : Nat) = 2 := by\n  run_tac {EXIT}\n",
    "by_elab": (
        "import Lean\nopen Lean in\ntheorem forged_false : (1 : Nat) = 2 := "
        "by_elab (IO.Process.exit 0 : Elab.TermElabM Expr)\n"
    ),
    # A correct statement and a real proof after the exit still leave no compiled module.
    "leading_exit_correct_statement": (
        f"#eval {EXIT}\ntheorem honest : (1 : Nat) = 1 := rfl\n"
    ),
}


def _lean() -> str:
    lean = os.environ.get("PALS_FORGERY_LEAN") or shutil.which("lean")
    if lean is None:
        pytest.skip("Lean is not installed")
    return lean


def _plain(lean: str) -> LeanVerifier:
    return LeanVerifier(lean_binary=lean, elan_home=str(Path(lean).parent.parent))


def _codes(result: VerificationResult) -> list[str]:
    return [str(item.code) for item in result.diagnostics]


@pytest.fixture
def without_source_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lean_module, "find_source_violation", lambda _source: None)
    monkeypatch.setattr(lean_module, "_TRUSTED_DECLARATION_RE", re.compile(r"(?!)"))


@pytest.mark.parametrize("name", sorted(EXIT_SOURCES))
def test_source_policy_rejects_every_exit_variant(name: str) -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(EXIT_SOURCES[name])

    assert result.success is False
    assert _codes(result)[0].startswith("lean.disallowed_")


@pytest.mark.parametrize("name", sorted(EXIT_SOURCES))
@pytest.mark.usefixtures("without_source_policy")
def test_audit_rejects_real_exit_zero_without_the_source_policy(
    name: str, tmp_path: Path
) -> None:
    lean = _lean()
    source = tmp_path / "Exit.lean"
    source.write_text(EXIT_SOURCES[name], encoding="utf-8")
    plain = subprocess.run([lean, str(source)], capture_output=True, text=True, timeout=120)
    assert plain.returncode == 0, "the exploit no longer exits zero, so this proves nothing"

    result = _plain(lean).verify(EXIT_SOURCES[name])

    assert result.success is False
    assert "lean.trusted_audit_failed" in _codes(result)
    assert "lean.verified" not in _codes(result)


@pytest.mark.parametrize(
    "source",
    [
        "axiom bad : (1 : Nat) = 2\ntheorem forged_false : (1 : Nat) = 2 := bad\n",
        # Reached only through a helper, and through an instance rather than a named theorem.
        "axiom bad : False\ntheorem helper : (1 : Nat) = 2 := bad.elim\n"
        "theorem forged_false : (1 : Nat) = 2 := helper\n",
        "axiom bad : False\ninstance forgedInstance : Inhabited False := ⟨bad⟩\n",
        "theorem native_forged : 2 ^ 10 = 1024 := by native_decide\n",
        # Lean discards an `example`, so its axioms need the named audit compile.
        "example : 2 ^ 10 = 1024 := by native_decide\n",
        "axiom bad : False\nexample : (1 : Nat) = 2 := bad.elim\n",
    ],
)
@pytest.mark.usefixtures("without_source_policy")
def test_audit_rejects_transitive_nonstandard_axioms(source: str) -> None:
    result = _plain(_lean()).verify(source)

    assert result.success is False
    assert _codes(result)[-1] == "lean.disallowed_axiom"


@pytest.mark.usefixtures("without_source_policy")
def test_kernel_replay_rejects_a_declaration_the_compile_skipped() -> None:
    # This module compiles cleanly and `#print axioms` would report nothing.
    source = "\n".join(
        [
            "import Lean",
            "open Lean Elab Command",
            "set_option debug.skipKernelTC true in",
            "run_cmd liftCoreM do",
            "  addDecl <| Declaration.thmDecl {",
            "    name := `forged_hack, levelParams := [],",
            "    type := mkApp3 (mkConst ``Eq [1]) (mkConst ``Nat) (mkNatLit 1) (mkNatLit 2),",
            "    value := mkConst ``Nat.zero }",
            "theorem forged_false : (1 : Nat) = 2 := forged_hack",
        ]
    )

    result = _plain(_lean()).verify(source)

    assert result.success is False
    assert _codes(result) == ["lean.trusted_audit_failed"]


@pytest.mark.parametrize(
    "source",
    [
        "theorem honest : (1 : Nat) = 1 := rfl\n",
        "example : True := trivial\n",
        "example : Nat := 1\n",
        "example := (2 : Nat)\n",
        "variable (n : Nat) in\nexample : n = n := rfl\n",
        "noncomputable section\nexample (p : Prop) : p ∨ ¬p := Classical.em p\nend\n",
        "namespace A.B\nprotected theorem honest : True := trivial\nend A.B\n",
        "private theorem hidden : True := trivial\n",
        "theorem «quoted name» : True := trivial\n",
        "theorem universe_polymorphic.{u} (α : Sort u) : α = α := rfl\n",
        "def array := #[1, 2, 3]\ntheorem size_three : array.size = 3 := by decide\n",
        "theorem first (h : 1 = 1 ∧ 2 = 2) : 1 = 1 := h.1\n",
        "theorem classical (p : Prop) : p ∨ ¬p := Classical.em p\n",
        "set_option maxRecDepth 1000 in\n@[simp] theorem marked : (1 : Nat) = 1 := rfl\n",
    ],
)
def test_legitimate_plain_lean_is_verified(source: str) -> None:
    result = _plain(_lean()).verify(source)

    assert result.success is True, result.diagnostics
    assert _codes(result)[-1] == "lean.verified"


def _mathlib_verifier(**kwargs: object) -> LeanVerifier:
    project = os.environ.get("PALS_FORGERY_MATHLIB_PROJECT")
    lean = os.environ.get("PALS_FORGERY_LEAN")
    lake = os.environ.get("PALS_FORGERY_LAKE")
    if not project or not lean or not lake:
        pytest.skip("pinned Mathlib workspace is not configured")
    return LeanVerifier(
        project_dir=Path(project),
        lean_binary=lean,
        lake_binary=lake,
        elan_home=str(Path(lean).parent.parent),
        **kwargs,  # type: ignore[arg-type]
    )


MATHLIB_SOURCE = """\
import Mathlib

section
open Finset

theorem finset_notation (s : Finset ℕ) (h : #s = 0) : s = ∅ := by simpa using h

theorem union_card (s t : Finset ℕ) : #(s ∪ t) ≤ #s + #t := card_union_le s t

theorem filter_card (s : Finset ℕ) : #{x ∈ s | x = 0} ≤ #s := card_filter_le _ _

end

open Cardinal in
theorem cardinal_notation : #ℕ = ℵ₀ := mk_nat

theorem image_notation (f : ℕ → ℕ) (s : Set ℕ) (x : ℕ) (hx : x ∈ s) : f x ∈ f '' s :=
  Set.mem_image_of_mem f hx

theorem preimage_notation (f : ℕ → ℕ) (s : Set ℕ) (x : ℕ) (hx : f x ∈ s) : x ∈ f ⁻¹' s := hx

theorem array_literal : (#[1, 2, 3] : Array ℕ).size = 3 := rfl
"""


@pytest.mark.parametrize(
    "options",
    [{}, {"literal_admission_command": True}],
    ids=["proof_job", "admission"],
)
def test_real_mathlib_notation_is_verified_through_lake(options: dict[str, object]) -> None:
    result = _mathlib_verifier(**options).verify(MATHLIB_SOURCE)

    assert result.success is True, result.diagnostics
    assert _codes(result)[-1] == "lean.verified"


def test_real_mathlib_is_verified_with_reused_environment() -> None:
    verifier = _mathlib_verifier(lake_environment_cache=LakeEnvironmentCache())

    assert verifier.verify(MATHLIB_SOURCE).success is True
    assert verifier.verify(MATHLIB_SOURCE).success is True


@pytest.mark.parametrize(
    "options",
    [{}, {"literal_admission_command": True}, {"lake_environment_cache": LakeEnvironmentCache()}],
    ids=["proof_job", "admission", "reused_environment"],
)
@pytest.mark.usefixtures("without_source_policy")
def test_real_mathlib_exit_is_rejected_on_every_compile_path(
    options: dict[str, object],
) -> None:
    result = _mathlib_verifier(**options).verify(
        f"import Mathlib\nopen Nat in #eval {EXIT}\n{FORGED}"
    )

    assert result.success is False
    assert "lean.trusted_audit_failed" in _codes(result)
