import Mathlib

theorem recipe_const_mul_continuous_epsilon_delta : ∀ (c : ℝ) (f : ℝ → ℝ), Continuous f → Continuous (fun x : ℝ => c * f x) := by
  intro c f hf
  rw [continuous_iff_continuousAt]
  intro a
  rw [Metric.continuousAt_iff]
  intro ε hε
  have hC : 0 < |c| + 1 := by positivity
  obtain ⟨δ, hδ, h⟩ := Metric.continuousAt_iff.mp (continuous_iff_continuousAt.mp hf a) (ε / (|c| + 1)) (div_pos hε hC)
  refine ⟨δ, hδ, ?_⟩
  intro x hx
  have e := h hx
  rw [Real.dist_eq] at e ⊢
  have h1 : |c * f x - c * f a| = |c| * |f x - f a| := by rw [← mul_sub, abs_mul]
  have h2 : |c| * |f x - f a| ≤ (|c| + 1) * |f x - f a| :=
    mul_le_mul_of_nonneg_right (by linarith) (abs_nonneg _)
  have h3 : |f x - f a| * (|c| + 1) < ε := (lt_div_iff₀ hC).mp e
  rw [h1]
  linarith
