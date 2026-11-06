"""Lean's own elaborator specialises a stored Recipe; the pinned toolchain decides, not us."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.recipe_instantiation import (
    InstantiationRejected,
    check_alignment,
    check_proposition,
    elaborate,
    render_answer,
)

PINNED = Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1/bin/lean"
LAKE_PACKAGES = Path(os.environ.get(
    "PALS_TEST_MATHLIB_PACKAGES",
    "/Users/atsushi/OrbStack/docker/volumes/pals-local_pals-agent-lake/packages"))
needs_lean = pytest.mark.skipif(not PINNED.exists(), reason="pinned Lean v4.32.0-rc1 is required")

POW = "example : ∀ (n : Nat), 0 < 2 ^ n := fun n => Nat.two_pow_pos n\n"
ADD = "theorem add_comm_nat (a b : Nat) : a + b = b + a := Nat.add_comm a b\n"
NESTED = (
    "theorem le_add_nat : ∀ (n : Nat), ∀ (m : Nat), n ≤ n + m :=\n"
    "  fun n m => Nat.le_add_right n m\n"
)
FUNCTION = "theorem twice_refl (f : Nat → Nat) (a : Nat) : f (f a) = f (f a) := rfl\n"
IMPLICIT = (
    "theorem len_append' {α : Type} (l m : List α) : (l ++ m).length = l.length + m.length :=\n"
    "  List.length_append\n"
)
HYPOTHESIS = "theorem pred_succ (n : Nat) (h : 0 < n) : n - 1 + 1 = n := Nat.sub_add_cancel h\n"
TYPECLASS = (
    "theorem replicate_len {α : Type} [Inhabited α] (n : Nat) :\n"
    "    (List.replicate n (default : α)).length = n := by simp\n"
)
DEPENDENT = "theorem fin_lt (n : Nat) (i : Fin (n + 1)) : i.val < n + 1 := i.isLt\n"
HIGHER_ORDER = "theorem app_eq (f : Nat → Nat) (a : Nat) : f a = f a := rfl\n"
EXISTS = "theorem some_nat : ∃ n : Nat, n = n := ⟨0, rfl⟩\n"


def verifier() -> LeanVerifier:
    return LeanVerifier(lean_binary=str(PINNED), timeout_seconds=120.0)


@needs_lean
@pytest.mark.parametrize(("source", "request_"), [
    pytest.param(POW, "0 < 2 ^ 3", id="example-form-x-cubed-shape"),
    pytest.param(POW, "0 < 2 ^ 2", id="example-form-n-2"),
    pytest.param(ADD, "3 + 4 = 4 + 3", id="two-binders"),
    pytest.param(NESTED, "5 ≤ 5 + 7", id="nested-forall"),
    pytest.param(FUNCTION, "Nat.succ (Nat.succ 3) = Nat.succ (Nat.succ 3)", id="function-argument"),
    pytest.param(IMPLICIT, "([1, 2] ++ [3]).length = [1, 2].length + [3].length",
                 id="implicit-type-argument"),
    pytest.param(HYPOTHESIS, "5 - 1 + 1 = 5", id="side-condition-closed-by-decide"),
    pytest.param(TYPECLASS, "(List.replicate 3 (default : Nat)).length = 3",
                 id="instance-argument"),
    pytest.param(DEPENDENT, "(0 : Fin (2 + 1)).val < 2 + 1", id="dependent-binder-fin"),
    pytest.param(HIGHER_ORDER, "(fun y => y + 1) (2 * 3) = (fun y => y + 1) (2 * 3)",
                 id="higher-order-pattern-lambda-argument"),
])
def test_elaborator_derives_arguments_and_verifier_accepts(source, request_):
    instance = elaborate(source, request_)
    assert check_alignment(source, instance)
    result = verifier().verify(instance.source)
    assert result.success, result.diagnostics


@needs_lean
@pytest.mark.parametrize(("source", "request_"), [
    pytest.param(POW, "0 < 2 ^ (-1)", id="negative-exponent-for-nat-binder"),
    pytest.param(POW, "0 < 2 ^ (1 / 2 : Real)", id="real-exponent"),
    pytest.param(POW, "2 ^ 3 < 0", id="changed-conclusion"),
    pytest.param(POW, "1 = 1 → 0 < 2 ^ 3", id="added-hypothesis"),
    pytest.param(ADD, "(3 : Int) + 4 = 4 + 3", id="type-mismatch-nat-vs-int"),
    pytest.param(HYPOTHESIS, "0 - 1 + 1 = 0", id="unprovable-premise"),
    pytest.param(ADD, "3 + 4 = 4 + 4", id="wrong-statement"),
    pytest.param(DEPENDENT, "(0 : Fin (2 + 1)).val < 2", id="dependent-binder-wrong-bound"),
    pytest.param(HIGHER_ORDER, "(fun y => y + 1) 3 = (fun y => y + 2) 3",
                 id="higher-order-two-different-functions"),
])
def test_lean_refuses_what_is_not_an_instance(source, request_):
    instance = elaborate(source, request_)
    assert not verifier().verify(instance.source).success


def test_existential_recipe_has_no_universal_parameter_to_specialise():
    with pytest.raises(InstantiationRejected):
        elaborate(EXISTS, "∀ n : Nat, n = n")


@needs_lean
def test_wrong_hint_cannot_make_a_wrong_statement_pass_and_cannot_block_the_right_one():
    right = elaborate(ADD, "3 + 4 = 4 + 3", [("a", "9")])
    assert verifier().verify(right.source).success
    wrong = elaborate(ADD, "3 + 4 = 4 + 5", [("a", "3"), ("b", "5")])
    assert not verifier().verify(wrong.source).success


@pytest.mark.parametrize("request_", [
    "0 < 2 ^ 3 := by simp", "(by simp : 0 < 2 ^ 3)", "show 0 < 2 ^ 3 from trivial",
    "0 < 2 ^ 3\n theorem evil : False := sorry", "sorry", "0 < 2 ^ 3 -- c", "0 < 2 ^ (3",
    "native_decide", "∀ x, x = x; True", "0 < 2 ^ 3 ) (", "", "x" * 2001,
    "(change 0 < 8 : 0 < 2 ^ 3)", "unfold f", "`foo",
])
def test_type_rewriting_and_command_syntax_never_enters_the_template(request_):
    with pytest.raises(InstantiationRejected):
        elaborate(ADD, request_)
    with pytest.raises(InstantiationRejected):
        check_proposition(request_)


def test_alignment_rejects_tampered_wrappers_and_foreign_sources():
    instance = elaborate(ADD, "3 + 4 = 4 + 3")
    tampered = type(instance)(**{**instance.__dict__, "proposition": "3 + 4 = 4 + 4"}) \
        if hasattr(instance, "__dict__") else None
    assert tampered is None or not check_alignment(ADD, tampered)
    assert not check_alignment(ADD + "-- x\n", instance)
    assert not check_alignment(POW, instance)


def test_hints_must_be_numeric_literals_of_explicit_parameters():
    for hints in ([("z", "2")], [("a", "x")], [("a", "-1")], [("a", "1"), ("a", "2")]):
        with pytest.raises(InstantiationRejected):
            elaborate(ADD, "1 + 1 = 1 + 1", hints)


def test_hint_names_outside_the_wire_pattern_are_dropped():
    # The API accepts only short display names; anything else is left to Lean's unification.
    source = "theorem pw (base exp : Nat) : base ^ exp = base ^ exp := rfl\n"
    instance = elaborate(source, "2 ^ 3 = 2 ^ 3", [{"variable": "base", "value": "2"}])
    assert instance.bindings == () and "(base :=" not in instance.source


def test_elaborated_answer_never_asserts_arguments_in_prose():
    text = render_answer("ja", "一般的な結果", (), "保存回答")
    assert "保存回答" in text and "$" not in text


def test_unsupported_recipe_arity_and_shapes_reject():
    with pytest.raises(InstantiationRejected):
        elaborate("theorem t : True := trivial\n", "True")
    with pytest.raises(InstantiationRejected):
        elaborate("namespace A\ntheorem t (n : Nat) : n = n := rfl\nend A\n", "1 = 1")
    many = "theorem t (a b c d e f g : Nat) : True := trivial\n"
    with pytest.raises(InstantiationRejected):
        elaborate(many, "True")


MATHLIB_POWER = (
    "import Mathlib\n\nexample : ∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n) := by\n"
    "  intro n\n  induction n with\n"
    "  | zero => simpa using (continuous_const : Continuous (fun _ : ℝ => (1 : ℝ)))\n"
    "  | succ n ih => simpa only [pow_succ, Pi.mul_apply, id_eq] using ih.fun_mul continuous_id\n"
)


def mathlib_environment() -> dict[str, str] | None:
    paths = [str(p / ".lake/build/lib/lean") for p in LAKE_PACKAGES.glob("*")
             if (p / ".lake/build/lib/lean").is_dir()]
    toolchain = PINNED.parent.parent / "lib/lean"
    if not paths or not toolchain.is_dir():
        return None
    return {**os.environ, "LEAN_PATH": ":".join(paths + [str(toolchain)])}


@needs_lean
@pytest.mark.skipif(mathlib_environment() is None, reason="no built Mathlib for v4.32.0-rc1")
@pytest.mark.parametrize("request_", [
    "Continuous (fun x : ℝ => x ^ 2)", "Continuous (fun x : ℝ => x ^ 3)",
])
def test_production_recipe_specialises_to_x_squared_with_real_mathlib(request_, tmp_path):
    instance = elaborate(MATHLIB_POWER, request_)
    (tmp_path / "Main.lean").write_text(instance.source)
    started = time.monotonic()
    done = subprocess.run([str(PINNED), "Main.lean"], cwd=tmp_path, env=mathlib_environment(),
                          capture_output=True, text=True, timeout=600)
    elapsed = time.monotonic() - started
    assert done.returncode == 0, done.stdout + done.stderr
    print(f"mathlib compile of instance: {elapsed:.1f}s")


@needs_lean
@pytest.mark.skipif(mathlib_environment() is None, reason="no built Mathlib for v4.32.0-rc1")
def test_mathlib_refuses_a_fractional_exponent_for_the_production_recipe(tmp_path):
    instance = elaborate(MATHLIB_POWER, "Continuous (fun x : ℝ => x ^ (1 / 2 : ℝ))")
    (tmp_path / "Main.lean").write_text(instance.source)
    done = subprocess.run([str(PINNED), "Main.lean"], cwd=tmp_path, env=mathlib_environment(),
                          capture_output=True, text=True, timeout=600)
    assert done.returncode != 0
