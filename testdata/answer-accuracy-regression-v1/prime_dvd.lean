import Mathlib

theorem prime_dvd_mul_split (p a b : ℕ) (hp : p.Prime) (h : p ∣ a * b) : p ∣ a ∨ p ∣ b :=
  (Nat.Prime.dvd_mul hp).mp h
