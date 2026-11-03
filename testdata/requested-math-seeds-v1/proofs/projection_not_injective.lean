import Mathlib.Data.Real.Basic
import Mathlib.Tactic.NormNum

theorem requested_projection_not_injective : ¬ Function.Injective (fun p : ℝ × ℝ => p.1) := by
  intro h
  have hpair : ((0, 0) : ℝ × ℝ) = (0, 1) := h rfl
  have : (0 : ℝ) = 1 := congrArg Prod.snd hpair
  norm_num at this
