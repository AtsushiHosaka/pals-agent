import Mathlib

theorem odd_power_strictly_increasing_sign_cases : ∀ (n : ℕ), StrictMono (fun x : ℝ => x ^ (2 * n + 1)) := by
  intro n x y hxy
  have hm : Odd (2 * n + 1) := ⟨n, rfl⟩
  have hne : 2 * n + 1 ≠ 0 := by omega
  show x ^ (2 * n + 1) < y ^ (2 * n + 1)
  rcases le_or_gt 0 x with hx | hx
  · -- Case 1: 0 ≤ x < y, powers are strictly increasing on the non-negative reals.
    exact pow_lt_pow_left₀ hxy hx hne
  · rcases le_or_gt y 0 with hy | hy
    · -- Case 2: x < y ≤ 0, reflect to 0 ≤ -y < -x and use (-t) ^ m = -(t ^ m) for odd m.
      have h : (-y) ^ (2 * n + 1) < (-x) ^ (2 * n + 1) :=
        pow_lt_pow_left₀ (by linarith) (by linarith) hne
      rw [hm.neg_pow, hm.neg_pow] at h
      linarith
    · -- Case 3: x < 0 < y, an odd power of a negative number is negative.
      have h1 : x ^ (2 * n + 1) < 0 := hm.pow_neg hx
      have h2 : 0 < y ^ (2 * n + 1) := pow_pos hy _
      linarith
