import Mathlib.Data.Real.Basic
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.FieldSimp
import Mathlib.Tactic.Ring
import Mathlib.Tactic.NormNum

-- Independently authored structural-test fixture; compile evidence is recorded separately.
theorem reciprocal_minimum :
    (∀ x : ℝ, 0 < x → 2 ≤ x + 1 / x) ∧
    (∀ x : ℝ, 0 < x → (x + 1 / x = 2 ↔ x = 1)) := by
  constructor
  · intro x hx
    have hx0 : x ≠ 0 := ne_of_gt hx
    have hnonneg : 0 ≤ (x - 1) ^ 2 / x :=
      div_nonneg (sq_nonneg (x - 1)) (le_of_lt hx)
    have hidentity : (x - 1) ^ 2 / x = x + 1 / x - 2 := by
      field_simp
      <;> ring
    linarith
  · intro x hx
    constructor
    · intro hequality
      have hx0 : x ≠ 0 := ne_of_gt hx
      have hproduct : (1 / x) * x = 1 := div_mul_cancel₀ 1 hx0
      have hsquare : (x - 1) ^ 2 = 0 := by nlinarith
      have hzero : x - 1 = 0 := (sq_eq_zero_iff).mp hsquare
      linarith
    · rintro rfl
      norm_num
