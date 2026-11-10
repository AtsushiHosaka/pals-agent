import Mathlib

theorem linear_continuous_explicit_epsilon_delta : ∀ (c : ℝ), Continuous (fun x : ℝ => c * x) := by
  intro c
  rw [continuous_iff_continuousAt]
  intro a
  rw [Metric.continuousAt_iff]
  intro ε hε
  -- δ = ε / (|c| + 1), positive even when c = 0.
  have hC : 0 < |c| + 1 := by positivity
  refine ⟨ε / (|c| + 1), div_pos hε hC, ?_⟩
  intro x hx
  rw [Real.dist_eq] at hx ⊢
  have h1 : |c * x - c * a| = |c| * |x - a| := by rw [← mul_sub, abs_mul]
  have h2 : |c| * |x - a| ≤ (|c| + 1) * |x - a| :=
    mul_le_mul_of_nonneg_right (by linarith) (abs_nonneg _)
  have h3 : |x - a| * (|c| + 1) < ε := (lt_div_iff₀ hC).mp hx
  rw [h1]
  linarith
