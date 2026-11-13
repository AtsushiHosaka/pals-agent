import Mathlib

theorem dual_sum (R : Type*) [CommRing R] (e : R) (h : e * e = 0) (n : ℕ) :
    (∑ k ∈ Finset.range n, (1 + e) ^ k) = (n : R) + (n.choose 2 : R) * e := by
  have hp : ∀ k : ℕ, (1 + e) ^ k = 1 + (k : R) * e := by
    intro k
    induction k with
    | zero => simp
    | succ k ih =>
      rw [pow_succ, ih]
      push_cast
      have : (k : R) * e * e = 0 := by rw [mul_assoc, h, mul_zero]
      linear_combination this
  simp_rw [hp]
  rw [Finset.sum_add_distrib, ← Finset.sum_mul]
  simp only [Finset.sum_const, Finset.card_range, nsmul_eq_mul, mul_one]
  have hc : (∑ i ∈ Finset.range n, (i : R)) = (n.choose 2 : R) := by
    have h2 : (∑ i ∈ Finset.range n, i) = n.choose 2 := by
      rw [Finset.sum_range_id, Nat.choose_two_right]
    rw [← h2]
    push_cast
    rfl
  rw [hc]
