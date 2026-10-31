import Mathlib.Analysis.Calculus.Deriv.Abs

open Filter Topology

theorem requested_absolute_value_not_differentiable : ¬ DifferentiableAt ℝ (abs : ℝ → ℝ) 0 := by
  exact not_differentiableAt_abs_zero
