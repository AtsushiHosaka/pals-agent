import Mathlib.Analysis.SpecialFunctions.Trigonometric.Basic
import Mathlib.Topology.Algebra.Field
import Mathlib.Tactic

open Filter Topology

theorem requested_rational_power_continuous (n : ℕ) :
    Continuous (fun x : ℝ => (x ^ n + Real.sin x) / (1 + x ^ 2)) := by
  apply Continuous.div
  · fun_prop
  · fun_prop
  · intro x
    positivity
