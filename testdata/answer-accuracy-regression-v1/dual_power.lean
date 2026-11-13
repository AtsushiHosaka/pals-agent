import Mathlib

theorem dual_power (R : Type*) [CommRing R] (e : R) (h : e * e = 0) (n : ℕ) :
    (1 + e) ^ n = 1 + (n : R) * e := by
  induction n with
  | zero => simp
  | succ k ih =>
    rw [pow_succ, ih]
    push_cast
    have : (k : R) * e * e = 0 := by rw [mul_assoc, h, mul_zero]
    linear_combination this
