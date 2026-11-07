import Mathlib

theorem linear_uniformly_continuous_explicit_epsilon_delta : ∀ (c : ℝ), UniformContinuous (fun x : ℝ => c * x) := by
  intro c
  rw [Metric.uniformContinuous_iff]
  intro ε hε
  -- δ = ε / (|c| + 1) depends on neither x nor y.
  have hC : 0 < |c| + 1 := by positivity
  refine ⟨ε / (|c| + 1), div_pos hε hC, ?_⟩
  intro x y hxy
  rw [Real.dist_eq] at hxy ⊢
  have h1 : |c * x - c * y| = |c| * |x - y| := by rw [← mul_sub, abs_mul]
  have h2 : |c| * |x - y| ≤ (|c| + 1) * |x - y| :=
    mul_le_mul_of_nonneg_right (by linarith) (abs_nonneg _)
  have h3 : |x - y| * (|c| + 1) < ε := (lt_div_iff₀ hC).mp hxy
  rw [h1]
  linarith
