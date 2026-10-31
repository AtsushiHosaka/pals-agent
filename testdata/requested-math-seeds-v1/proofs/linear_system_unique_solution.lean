import Mathlib.Data.Real.Basic
import Mathlib.Tactic

theorem requested_linear_system_unique_solution (x y : ℝ) :
    (3 * x + 2 * y = 7 ∧ x - y = -1) ↔ (x = 1 ∧ y = 2) := by
  constructor
  · rintro ⟨h₁, h₂⟩
    constructor <;> linarith
  · rintro ⟨rfl, rfl⟩
    norm_num
