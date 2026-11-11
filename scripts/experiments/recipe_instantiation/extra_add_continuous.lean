theorem recipe_add_continuous_epsilon_delta : ∀ (f g : ℝ → ℝ), Continuous f → Continuous g → Continuous (fun x : ℝ => f x + g x) := by
  intro f g hf hg
  rw [continuous_iff_continuousAt]
  intro a
  rw [Metric.continuousAt_iff]
  intro ε hε
  have hε2 : 0 < ε / 2 := by positivity
  obtain ⟨δ₁, hδ₁, h₁⟩ := Metric.continuousAt_iff.mp (continuous_iff_continuousAt.mp hf a) (ε / 2) hε2
  obtain ⟨δ₂, hδ₂, h₂⟩ := Metric.continuousAt_iff.mp (continuous_iff_continuousAt.mp hg a) (ε / 2) hε2
  refine ⟨min δ₁ δ₂, lt_min hδ₁ hδ₂, ?_⟩
  intro x hx
  have e1 := h₁ (lt_of_lt_of_le hx (min_le_left _ _))
  have e2 := h₂ (lt_of_lt_of_le hx (min_le_right _ _))
  rw [Real.dist_eq] at e1 e2 ⊢
  calc |f x + g x - (f a + g a)| = |(f x - f a) + (g x - g a)| := by congr 1; ring
    _ ≤ |f x - f a| + |g x - g a| := abs_add_le _ _
    _ < ε := by linarith
