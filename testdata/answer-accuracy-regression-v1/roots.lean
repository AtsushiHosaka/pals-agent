import Mathlib

theorem roots_quadratic : {x : ℝ | x ^ 2 - 5 * x + 6 = 0} = {2, 3} := by
  ext x
  simp only [Set.mem_setOf_eq, Set.mem_insert_iff, Set.mem_singleton_iff]
  constructor
  · intro h
    have : (x - 2) * (x - 3) = 0 := by linear_combination h
    rcases mul_eq_zero.mp this with h1 | h1
    · left; linarith
    · right; linarith
  · rintro (rfl | rfl) <;> norm_num
