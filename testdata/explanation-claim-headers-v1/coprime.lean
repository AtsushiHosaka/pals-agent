import Mathlib.Data.Nat.GCD.Basic
import Mathlib.Tactic

/- Original synthetic divisibility characterization. Naturals include zero. -/
theorem coprime_common_multiples (a b n : ℕ) (hcop : Nat.Coprime a b) :
    (a ∣ n ∧ b ∣ n) ↔ a * b ∣ n := by
  constructor
  · rintro ⟨ha, hb⟩
    obtain ⟨k, rfl⟩ := ha
    have quotient_divisible :
        b ∣ k := by
      exact hcop.symm.dvd_mul_left.mp hb
    obtain ⟨q, hq⟩ := quotient_divisible
    refine ⟨q, ?_⟩
    simp [hq, Nat.mul_assoc]
  · intro hab
    constructor
    · exact dvd_trans (dvd_mul_right a b) hab
    · exact dvd_trans (dvd_mul_left b a) hab
