import Mathlib.LinearAlgebra.Matrix.Determinant.Basic
import Mathlib.Tactic

theorem requested_determinant_nonzero_decision : Matrix.det (!![(1 : ℝ), 2; 3, 5]) ≠ 0 := by
  norm_num [Matrix.det_fin_two]
