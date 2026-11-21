import Mathlib

theorem sample_pairwise_products_le_squares (a b c : ℝ) :
    a * b + b * c + c * a ≤ a ^ 2 + b ^ 2 + c ^ 2 := by
  have hab :
      0 ≤ (a - b) ^ 2 := sq_nonneg _
  have hbc :
      0 ≤ (b - c) ^ 2 := sq_nonneg _
  have hca :
      0 ≤ (c - a) ^ 2 := sq_nonneg _
  nlinarith [hab, hbc, hca]
