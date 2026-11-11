"""The shared allow-list grammar for propositions: hundreds of accept/refuse cases, pure Python.

CI never runs the real-Lean tests (no Lean workspace on the runner), so these are the tests that
guard statement injection in CI.  Every attack below was either reproduced against the earlier
deny-list validator or is a variant of one that was.
"""

import json
from pathlib import Path

import pytest

from pals_agent import automation_portfolio as ap
from pals_agent import general_recipe_lane as lane
from pals_agent.statement_grammar import StatementRejected, validate_proposition

ROOT = Path(__file__).resolve().parents[2]

# Each attack is a fragment that would run code, change the declaration, or hide text.
ATTACKS = [
    # term-level tactic blocks / code execution
    '∀ x : ℕ, (by run_tac (IO.FS.writeFile "/tmp/pwn" "x") : x = x)',
    "∀ x : ℕ, (by run_tac (pure ()) : x = x)",
    "∀ x : ℕ, (by exact rfl : x = x)",
    "∀ x : ℕ, x = x ∧ (by simp : True)",
    "(by decide : (1 : ℕ) = 1)",
    "∀ x : ℕ, x = by exact x",
    "∀ x : ℕ, (show x = x from rfl)",
    "∀ x : ℕ, (have h : x = x := rfl; x = x)",
    "∀ x : ℕ, x = (fun y => do pure y) x",
    "∀ x : ℕ, x = x := by run_tac (IO.println 1)",
    "∀ x : ℕ, x = x := by\n  run_tac (IO.println 1)",
    "∀ x : ℕ, x = x := rfl",
    "1 = 1 := by decide",
    "let y := by simp; True",
    "∀ x : ℕ, let y := by run_tac (pure ()); y = y",
    "∀ x : ℕ, let y := x; y = y",
    "∀ x : ℕ, x = x; 1 = 1",
    # commands and options
    "open Lean in ∀ x : ℕ, x = x",
    "open Lean Elab Command in True",
    "set_option maxRecDepth 100000 in ∀ x : ℕ, x = x",
    "set_option autoImplicit true in x + 0 = x",
    "unsafe def f := 1",
    "unsafeCast (1 : ℕ) = (1 : ℕ)",
    "∀ x : ℕ, x = x\ntheorem t : True := trivial",
    "∀ x : ℕ, x = x theorem t : True := trivial",
    "1 = 1 end",
    "namespace Foo",
    "section",
    "import Lean",
    "attribute [simp] foo",
    "@[simp] theorem t : True := trivial",
    "instance : Inhabited ℕ := ⟨0⟩",
    "macro \"x\" : term => `(1)",
    "syntax \"x\" : term",
    "notation \"x\" => 1",
    "elab \"x\" : term => pure (Lean.mkNatLit 1)",
    "macro_rules | `(x) => `(1)",
    "run_cmd IO.println 1",
    "∀ x : ℕ, run_cmd x = x",
    "#eval 1",
    "#print axioms foo",
    "#check 1",
    "∀ x : ℕ, x = x #eval 1",
    # code-bearing identifiers
    "IO.FS.writeFile = IO.FS.writeFile",
    "∀ x : ℕ, IO.println x = IO.println x",
    "Lean.Elab.Command.elabCommand = Lean.Elab.Command.elabCommand",
    "Lean.Meta.evalExpr = Lean.Meta.evalExpr",
    "∀ x : ℕ, System.FilePath.mk x = x",
    "run_tac = run_tac",
    "«run_tac» = «run_tac»",
    "native_decide = native_decide",
    "∀ x : ℕ, Nat.decEq x x = Nat.decEq x x ∧ sorry",
    "sorry",
    "admit = admit",
    "axiom_x = axiom",
    # string / char literals and obfuscation
    '"abc" = "abc"',
    "'a' = 'a'",
    "'(x)",
    "` x = x",
    "`(x)",
    "$x = $x",
    "$(x) = 1",
    "∀ x : ℕ, x = \\x",
    "\\u0062y",
    "∀ x : ℕ, x = x -- hidden",
    "∀ x : ℕ, x = x /- hidden -/",
    "/- c -/ 1 = 1",
    "1 = 1 -/",
    "∀ x : ℕ, x = x <| by simp",
    "∀ x : ℕ, x = x |> by simp",
    # structure and encoding
    "",
    "   ",
    "∀ x : ℕ, (x = x",
    "∀ x : ℕ, x = x)",
    "∀ x : ℕ, x = x\x00",
    "∀ x : ℕ, x = x‮",
    "∀ x : ℕ, x = x​ ∧ by simp",
    "x" * 5000,
    # tactic-like and term-like keywords that must not appear in a proposition
    "match 1 with | _ => True",
    "∀ x : ℕ, x = x from rfl",
    "calc 1 = 1 := rfl",
    "∀ x : ℕ, x = x using h",
    "∀ x : ℕ, x = x at h",
    "exact rfl",
    "intro x",
    "where x := 1",
    "deriving instance",
    "mutual",
    "variable (x : ℕ)",
    "universe u",
    "partial def f := 1",
    "private theorem t : True := trivial",
    "∀ x : ℕ, x = x with x",
]


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_shared_validator_refuses_every_attack(attack):
    with pytest.raises(StatementRejected):
        validate_proposition(attack)


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_portfolio_entry_refuses_every_attack(attack):
    with pytest.raises(Exception) as caught:  # StatementRejected or InstantiationRejected
        ap.check_formal_statement(attack)
    assert "Rejected" in type(caught.value).__name__


@pytest.mark.parametrize("attack", ATTACKS)
def test_the_recipe_lane_entry_refuses_every_attack(attack):
    recipe = lane.PoolRecipe(
        "x", "import Mathlib\n\ntheorem g (a : ℕ) : a = a := rfl", "∀ a : ℕ, a = a"
    )
    with pytest.raises(Exception) as caught:
        lane.build_source([recipe], attack)
    assert "Rejected" in type(caught.value).__name__


@pytest.mark.parametrize("wrapper", [
    "∀ x : ℕ, ({0})",
    "({0}) ∧ True",
    "Continuous (fun x : ℝ => {0})",
    "∀ f : ℝ → ℝ, ({0}) → True",
])
@pytest.mark.parametrize("payload", [
    "by simp",
    "by run_tac (pure ())",
    "(by exact rfl : True)",
    "IO.println 1",
    "do pure 1",
    "unsafeCast 1",
    "set_option maxHeartbeats 1 in 1",
    "open Lean in 1",
    "run_cmd 1",
    '"s"',
    "'c'",
    "`x",
])
def test_attack_payloads_are_refused_wherever_they_are_embedded(wrapper, payload):
    with pytest.raises(StatementRejected):
        validate_proposition(wrapper.format(payload))


ACCEPT = [
    "∀ x : ℝ, 0 ≤ x ^ 2",
    "∀ (x y : ℝ), x * (-y) + y * x = 0",
    "Continuous (fun x : ℝ => (x ^ 2 + 1) * Real.exp x + (x ^ 2 + 1))",
    "∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n",
    "∀ A B : Set ℕ, A ⊆ {1, 2} → A ∩ B ⊆ {1, 2}",
    "∀ x y : ZMod 7, x ^ 2 - y ^ 2 = (x + y) * (x - y)",
    "(({1, 2, 3} : Finset ℕ) \\ {2}).card = 2",
    "∀ (A B C : Type*) (f : A → B) (g : B → C), Function.Injective (g ∘ f) → Function.Injective f",
    "∀ (K : Type*) [DivisionRing K] (V : Type*) [AddCommGroup V] [Module K V], True",
    "∀ a b : ℝ, a ≤ b → ∀ f : ℝ → ℝ, ContinuousOn f (Set.Icc a b) → ∃ c ∈ Set.Icc a b, f c = c",
    "(∫ x in (0 : ℝ)..(1 : ℝ), x ^ 2) = (1 / 3 : ℝ)",
    "∀ n : ℕ, (∑ k ∈ Finset.Icc 1 n, k) = n * (n + 1) / 2",
    "∀ x : ℝ, x ≠ -1 → x ≠ -2 → (2 * x + 3) / ((x + 1) * (x + 2)) = 1 / (x + 1) + 1 / (x + 2)",
    "((!![(1 : ℝ), 2; 3, 5] : Matrix (Fin 2) (Fin 2) ℝ).det) = -1",
    "∀ f : ℝ → ℝ, Differentiable ℝ f → (∀ x : ℝ, deriv f x > 0) → Function.Injective f",
    "¬ ∃ q : ℚ, Real.tan (Real.pi / 180) = (q : ℝ)",
    "∀ (f g : ℝ → ℝ) (a f' g' : ℝ), HasDerivAt f f' a → HasDerivAt g g' a → HasDerivAt (fun x => f x + g x) (f' + g') a",
    "∀ m n : ℕ, Nat.gcd m n ∣ m",
    "∀ u : ℕ → ℝ, Monotone u → ∀ M : ℝ, (∀ n, u n ≤ M) → ∃ L, Filter.Tendsto u Filter.atTop (nhds L)",
    "∀ x : ℝ, Real.sqrt (x ^ 2) = |x|",
    "∀ z : ℝ × ℝ, z.1 = z.1",
    "∀ x : ℕ, x % 2 = 0 ∨ x % 2 = 1",
    "∀ s : Finset ℕ, s.card ≥ 0",
    "∀ x : ℝ, x⁻¹ * x = 1 ∨ x = 0",
    "∀ x : ℂ, Complex.abs x ≥ 0",
    "∀ (R : Type*) [CommRing R] (a b : R), a * b = b * a",
    "∀ x : ℝ, if x < 0 then |x| = -x else |x| = x",
    "∀ x : ℝ, ‖x‖ = |x|",
    "∀ A : Set ℝ, Aᶜ ∪ A = Set.univ",
]


@pytest.mark.parametrize("statement", ACCEPT)
def test_ordinary_mathematical_statements_are_accepted(statement):
    assert validate_proposition(statement)


def test_every_catalog_statement_of_the_evaluation_set_is_accepted_or_listed_as_lost():
    manifest = json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())
    lost = []
    for problem in manifest["problems"]:
        formal = problem.get("fixed_lean_statement")
        if not formal:
            continue
        try:
            ap.check_formal_statement(formal, allow_header=True)
        except Exception:  # noqa: BLE001
            lost.append(problem["id"])
    # the `let` statement is the only loss: `let` is outside the allow-list
    assert lost == ["la_v6_nonzero_maps_zero_composite"]


def test_adversarial_case_statements_are_accepted():
    cases = json.loads((ROOT / "testdata/fidelity-adversarial-v1/cases.json").read_text())["cases"]
    for case in cases:
        assert validate_proposition(case["faithful"]) and validate_proposition(case["bad"])


def test_a_header_with_a_proof_is_only_stripped_for_catalog_statements():
    header = "theorem t (n : ℕ) : n + 0 = n := by\n  simp"
    assert ap.check_formal_statement(header, allow_header=True) == "∀ (n : ℕ), n + 0 = n"
    with pytest.raises(Exception):  # noqa: B017 - any rejection
        ap.check_formal_statement(header)  # a model-written statement may not carry a header


def test_statement_with_a_top_level_assignment_suffix_is_not_recorded_as_a_proposition():
    # the earlier `let` branch let `:= by …` ride along: the declared type was only the prefix
    with pytest.raises(StatementRejected):
        validate_proposition("let x := 1; x = x := by simp")
