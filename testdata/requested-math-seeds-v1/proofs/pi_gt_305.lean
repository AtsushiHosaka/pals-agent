import Mathlib.Analysis.Real.Pi.Bounds
import Mathlib.Tactic.Linarith

open Filter Topology

theorem requested_pi_gt_305 : (3.05 : ℝ) < Real.pi := by
  have h := Real.pi_gt_d2
  linarith
