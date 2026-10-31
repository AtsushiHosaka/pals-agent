import Mathlib.Analysis.SpecialFunctions.ExpDeriv
import Mathlib.Tactic

open Filter Topology

theorem requested_exponential_product_derivative (x : ℝ) :
    HasDerivAt (fun y : ℝ => y * Real.exp y) ((x + 1) * Real.exp x) x := by
  convert (hasDerivAt_id x).fun_mul (Real.hasDerivAt_exp x) using 1 <;> first | rfl | (simp only [id_eq]; ring) | ring
