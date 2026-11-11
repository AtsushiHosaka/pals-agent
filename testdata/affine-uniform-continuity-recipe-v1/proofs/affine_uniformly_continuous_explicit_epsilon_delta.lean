import Mathlib

theorem affine_uniformly_continuous_explicit_epsilon_delta : ∀ (a b : ℝ), UniformContinuous (fun x : ℝ => a * x + b) := by
  intro a b
  rw [Metric.uniformContinuous_iff]
  intro ε hε
  -- δ = ε / (|a| + 1) depends on neither x nor y; the intercept b cancels.
  have hC : 0 < |a| + 1 := by positivity
  refine ⟨ε / (|a| + 1), div_pos hε hC, ?_⟩
  intro x y hxy
  rw [Real.dist_eq] at hxy ⊢
  have h1 : |(a * x + b) - (a * y + b)| = |a| * |x - y| := by
    rw [← abs_mul]
    congr 1
    ring
  have h2 : |a| * |x - y| ≤ (|a| + 1) * |x - y| :=
    mul_le_mul_of_nonneg_right (by linarith) (abs_nonneg _)
  have h3 : |x - y| * (|a| + 1) < ε := (lt_div_iff₀ hC).mp hxy
  rw [h1]
  linarith
