import Mathlib

theorem square_continuous_explicit_epsilon_delta : Continuous (fun x : ℝ => x ^ 2) := by
  rw [Metric.continuous_iff]
  intro a ε hε
  have hden : 0 < 2 * |a| + 1 := by positivity
  refine ⟨min 1 (ε / (2 * |a| + 1)), lt_min one_pos (div_pos hε hden), ?_⟩
  intro x hx
  rw [Real.dist_eq] at hx ⊢
  have hone : |x - a| < 1 := lt_of_lt_of_le hx (min_le_left _ _)
  have hdelta : |x - a| < ε / (2 * |a| + 1) := lt_of_lt_of_le hx (min_le_right _ _)
  have hx_abs : |x| ≤ |a| + 1 := by
    have htri : |x| ≤ |x - a| + |a| := by
      calc |x| = |(x - a) + a| := by ring_nf
        _ ≤ |x - a| + |a| := abs_add_le _ _
    linarith
  have hsum : |x + a| ≤ 2 * |a| + 1 := by
    have htri : |x + a| ≤ |x| + |a| := abs_add_le x a
    linarith
  have hfactor : |x ^ 2 - a ^ 2| = |x - a| * |x + a| := by
    rw [← abs_mul]
    congr 1
    ring
  calc |x ^ 2 - a ^ 2| = |x - a| * |x + a| := hfactor
    _ ≤ |x - a| * (2 * |a| + 1) := mul_le_mul_of_nonneg_left hsum (abs_nonneg _)
    _ < ε / (2 * |a| + 1) * (2 * |a| + 1) := mul_lt_mul_of_pos_right hdelta hden
    _ = ε := by field_simp
