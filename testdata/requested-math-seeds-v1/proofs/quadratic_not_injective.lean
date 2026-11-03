import Mathlib.Data.Real.Basic
import Mathlib.Tactic.NormNum

theorem requested_quadratic_not_injective : ¬ Function.Injective (fun x : ℝ => x ^ 2) := by
  intro h
  have heq : (-1 : ℝ) = 1 := h (by norm_num)
  norm_num at heq
