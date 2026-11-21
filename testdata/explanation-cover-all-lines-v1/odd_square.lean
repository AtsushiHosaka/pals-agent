import Mathlib

theorem sample_odd_square_mod_eight (n : ℤ) (h : n % 2 = 1) : n ^ 2 % 8 = 1 := by
  obtain ⟨k, hk⟩ : ∃ k : ℤ, n = 2 * k + 1 := ⟨n / 2, by omega⟩
  have hsq :
      n ^ 2 = 4 * (k * (k + 1)) + 1 := by
    rw [hk]
    ring
  have hprod :
      (k * (k + 1)) % 2 = 0 := by
    rcases Int.emod_two_eq_zero_or_one k with h0 | h1
    · simp [Int.mul_emod, h0]
    · simp [Int.mul_emod, Int.add_emod, h1]
  rw [hsq]
  omega
