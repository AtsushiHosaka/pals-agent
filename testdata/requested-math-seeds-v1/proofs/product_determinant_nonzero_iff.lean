import Mathlib

theorem requested_product_determinant_nonzero_iff {n : Type*} [Fintype n] [DecidableEq n]
    (A B : Matrix n n ℝ) :
    Matrix.det (A * B) ≠ 0 ↔ Matrix.det A ≠ 0 ∧ Matrix.det B ≠ 0 := by
  rw [Matrix.det_mul, mul_ne_zero_iff]
