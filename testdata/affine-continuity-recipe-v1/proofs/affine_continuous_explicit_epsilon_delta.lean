import Mathlib

theorem affine_continuous_explicit_epsilon_delta : ∀ (a b : ℝ), Continuous (fun x : ℝ => a * x + b) := by
  intro a b
  rw [continuous_iff_continuousAt]
  intro p
  rw [Metric.continuousAt_iff]
  intro ε hε
  -- δ = ε / (|a| + 1), positive even when a = 0; the intercept b cancels.
  have hC : 0 < |a| + 1 := by positivity
  refine ⟨ε / (|a| + 1), div_pos hε hC, ?_⟩
  intro x hx
  rw [Real.dist_eq] at hx ⊢
  have h1 : |(a * x + b) - (a * p + b)| = |a| * |x - p| := by
    rw [← abs_mul]
    congr 1
    ring
  have h2 : |a| * |x - p| ≤ (|a| + 1) * |x - p| :=
    mul_le_mul_of_nonneg_right (by linarith) (abs_nonneg _)
  have h3 : |x - p| * (|a| + 1) < ε := (lt_div_iff₀ hC).mp hx
  rw [h1]
  linarith
