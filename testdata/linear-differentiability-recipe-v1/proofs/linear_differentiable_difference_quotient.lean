import Mathlib

theorem linear_differentiable_difference_quotient : ∀ (c : ℝ), Differentiable ℝ (fun x : ℝ => c * x) := by
  intro c x
  -- The difference quotient is the constant c, so the remainder
  -- f z - f x - (z - x) * c is identically zero and trivially o(z - x).
  have h : HasDerivAt (fun x : ℝ => c * x) c x := by
    rw [hasDerivAt_iff_isLittleO]
    have : (fun z : ℝ => (c * z) - (c * x) - (z - x) • c) = fun _ => 0 := by
      funext z
      simp
      ring
    rw [this]
    exact Asymptotics.isLittleO_zero _ _
  exact h.differentiableAt
