import Mathlib

theorem one_div_succ_explicit_N (ε : ℝ) (hε : 0 < ε) :
    ∀ n : ℕ, ⌈1 / ε⌉₊ ≤ n → |1 / ((n : ℝ) + 1) - 0| < ε := by
  intro n hn
  have hpos : (0 : ℝ) < (n : ℝ) + 1 := by positivity
  rw [sub_zero, abs_of_pos (by positivity), div_lt_iff₀ hpos]
  have h1 : 1 / ε ≤ (n : ℝ) := le_trans (Nat.le_ceil _) (by exact_mod_cast hn)
  rw [div_le_iff₀ hε] at h1
  linarith
