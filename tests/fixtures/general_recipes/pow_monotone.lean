import Mathlib

theorem pow_le_pow_general (a b : ℝ) (ha : 0 ≤ a) (hab : a ≤ b) (n : ℕ) :
    a ^ n ≤ b ^ n := pow_le_pow_left₀ ha hab n
