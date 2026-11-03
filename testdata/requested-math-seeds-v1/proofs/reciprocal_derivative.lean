import Mathlib.Analysis.Calculus.Deriv.Inv
import Mathlib.Data.Real.Basic

open Filter Topology

theorem requested_reciprocal_derivative (x : ℝ) (hx : x ≠ 0) :
    HasDerivAt (fun y : ℝ => y⁻¹) (-(x ^ 2)⁻¹) x := by
  exact hasDerivAt_inv hx
