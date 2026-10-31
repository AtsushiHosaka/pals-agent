import Mathlib.Analysis.Calculus.Deriv.Add
import Mathlib.Data.Real.Basic

open Filter Topology

theorem requested_sum_derivative (f g : ℝ → ℝ) (a f' g' : ℝ)
    (hf : HasDerivAt f f' a) (hg : HasDerivAt g g' a) :
    HasDerivAt (fun x => f x + g x) (f' + g') a := by
  exact hf.fun_add hg
