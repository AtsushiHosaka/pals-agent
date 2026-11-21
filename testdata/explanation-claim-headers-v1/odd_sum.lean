import Mathlib

theorem sample_sum_of_first_odd_numbers (n : ℕ) :
    ∑ i ∈ Finset.range n, (2 * i + 1) = n ^ 2 := by
  induction n with
  | zero => simp
  | succ k ih =>
    have hstep :
        ∑ i ∈ Finset.range (k + 1), (2 * i + 1)
          = ∑ i ∈ Finset.range k, (2 * i + 1) + (2 * k + 1) := by
      rw [Finset.sum_range_succ]
    rw [hstep, ih]
    ring
