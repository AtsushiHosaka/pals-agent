import Mathlib

theorem power_differentiable_induction_product_rule : ∀ (n : ℕ), Differentiable ℝ (fun x : ℝ => x ^ n) := by
  intro n
  induction n with
  | zero =>
    -- x ^ 0 = 1 is a constant function.
    simp
  | succ k ih =>
    -- x ^ (k + 1) = x ^ k * x is a product of two differentiable functions.
    have h : (fun x : ℝ => x ^ (k + 1)) = fun x : ℝ => x ^ k * x := by
      funext x
      ring
    rw [h]
    exact ih.mul differentiable_id
