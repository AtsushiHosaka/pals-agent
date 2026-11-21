import Mathlib.Data.Real.Archimedean
import Mathlib.Algebra.Order.Floor.Ring
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.Positivity

theorem pals_target_c743ef6de10e69211fd592758c6605b2 :
    ∀ ε : ℝ, 0 < ε →
      ∃ N : ℕ, ∀ n : ℕ, N ≤ n → |1 / ((n : ℝ) + 1) - 0| < ε := by
  intro ε hε
  have hrecip_pos : 0 < 1 / ε := by
    positivity
  have hceil : 1 / ε ≤ (⌈1 / ε⌉₊ : ℝ) := by
    exact Nat.le_ceil _
  refine ⟨⌈1 / ε⌉₊, ?_⟩
  intro n hn
  have hncast : (⌈1 / ε⌉₊ : ℝ) ≤ (n : ℝ) := by
    exact Nat.cast_le.mpr hn
  have hden_pos : 0 < (n : ℝ) + 1 := by
    positivity
  have hrecip_lt : 1 / ε < (n : ℝ) + 1 := by
    linarith
  have hreverse : 1 / ((n : ℝ) + 1) < 1 / (1 / ε) := by
    exact one_div_lt_one_div_of_lt hrecip_pos hrecip_lt
  have hdouble : 1 / (1 / ε) = ε := by
    simp
  have hterm_pos : 0 < 1 / ((n : ℝ) + 1) := by
    positivity
  have hterm_lt : 1 / ((n : ℝ) + 1) < ε := by
    simpa only [hdouble] using hreverse
  calc
    |1 / ((n : ℝ) + 1) - 0| = 1 / ((n : ℝ) + 1) := by
      rw [sub_zero, abs_of_pos hterm_pos]
    _ < ε := hterm_lt

/- For every positive ε, the chosen N makes every subsequent term lie within
ε of 0. Thus the sequence converges to 0 by the epsilon–N definition.
This completes the proof of convergence. -/
