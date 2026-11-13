import Mathlib

theorem ratio_sum_ge_two (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 2 ≤ a / b + b / a := by
  rw [div_add_div _ _ hb.ne' ha.ne', le_div_iff₀ (mul_pos hb ha)]
  nlinarith [sq_nonneg (a - b)]
