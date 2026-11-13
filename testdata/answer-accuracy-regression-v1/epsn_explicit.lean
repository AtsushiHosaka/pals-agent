import Mathlib

theorem one_div_succ_epsilon_N (ε : ℝ) (hε : 0 < ε) :
    ∃ N : ℕ, ∀ n : ℕ, N ≤ n → |1 / ((n : ℝ) + 1) - 0| < ε := by
  obtain ⟨N, hN⟩ := exists_nat_gt (1 / ε)
  refine ⟨N, fun n hn => ?_⟩
  have hpos : (0 : ℝ) < (n : ℝ) + 1 := by positivity
  rw [sub_zero, abs_of_pos (by positivity), div_lt_iff₀ hpos]
  have h1 : 1 / ε < (n : ℝ) + 1 := by
    have : (N : ℝ) ≤ n := by exact_mod_cast hn
    linarith
  rw [div_lt_iff₀ hε] at h1
  linarith
