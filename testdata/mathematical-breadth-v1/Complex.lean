import Mathlib

theorem real_of_unit_reciprocal_sum (z : ℂ) (hz : z ≠ 0) :
    (z + z⁻¹).im = 0 ↔ z.im = 0 ∨ Complex.normSq z = 1 := by
  have hn : Complex.normSq z ≠ 0 := mt Complex.normSq_eq_zero.mp hz
  have hi : (z + z⁻¹).im = z.im - z.im / Complex.normSq z := by
    simp [Complex.inv_im, sub_eq_add_neg, neg_div]
  rw [hi]
  constructor
  · intro h
    have hmul : z.im * (Complex.normSq z - 1) = 0 := by
      field_simp at h
      nlinarith
    rcases mul_eq_zero.mp hmul with hzero | hone
    · exact Or.inl hzero
    · exact Or.inr (by linarith)
  · rintro (hzero | hone)
    · simp [hzero]
    · simp [hone]
