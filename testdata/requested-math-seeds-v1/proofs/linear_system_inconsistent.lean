import Mathlib.Data.Real.Basic
import Mathlib.Tactic.Linarith

theorem requested_linear_system_inconsistent :
    ¬ ∃ x y : ℝ, x + y = 1 ∧ 2 * x + 2 * y = 3 := by
  rintro ⟨x, y, h₁, h₂⟩
  linarith
