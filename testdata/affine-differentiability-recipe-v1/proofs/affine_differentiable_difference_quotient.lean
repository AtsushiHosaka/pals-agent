import Mathlib

theorem affine_differentiable_difference_quotient : ∀ (a b : ℝ), Differentiable ℝ (fun x : ℝ => a * x + b) := by
  intro a b x
  -- The difference quotient is the constant a, so the remainder
  -- f z - f x - (z - x) * a is identically zero and trivially o(z - x).
  have h : HasDerivAt (fun x : ℝ => a * x + b) a x := by
    rw [hasDerivAt_iff_isLittleO]
    have : (fun z : ℝ => (a * z + b) - (a * x + b) - (z - x) • a) = fun _ => 0 := by
      funext z
      simp
      ring
    rw [this]
    exact Asymptotics.isLittleO_zero _ _
  exact h.differentiableAt
