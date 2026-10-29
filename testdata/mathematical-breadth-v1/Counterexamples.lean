import Mathlib

theorem monotonicity_needed_for_unique_root :
    ∃ f : ℝ → ℝ, Continuous f ∧ f (-2) < 0 ∧ 0 < f 2 ∧
      f (-1) = 0 ∧ f 0 = 0 ∧ f 1 = 0 ∧ (-1 : ℝ) ≠ 1 := by
  refine ⟨fun x => x ^ 3 - x, by fun_prop, ?_, ?_, ?_, ?_, ?_, ?_⟩ <;> norm_num

theorem complex_differentiability_needed :
    (∀ z : ℂ, (1 : ℝ) ≤ ‖(1 : ℂ) + ‖z‖‖) ∧
    ((1 : ℂ) + ‖(1 : ℂ)‖) ≠ ((1 : ℂ) + ‖(0 : ℂ)‖) := by
  constructor
  · intro z
    rw [← Complex.ofReal_one, ← Complex.ofReal_add, Complex.norm_real]
    rw [Real.norm_eq_abs, abs_of_nonneg (by positivity)]
    exact le_add_of_nonneg_right (norm_nonneg z)
  · norm_num
