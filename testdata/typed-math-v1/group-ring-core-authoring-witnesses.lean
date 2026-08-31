import Mathlib

example : ∀ {G : Type*} [Group G] (a b : G), (a * b)⁻¹ = b⁻¹ * a⁻¹ := by
  intro G _ a b
  exact mul_inv_rev a b

example : ∀ {G : Type*} [Group G] (a : G), a⁻¹ * a = 1 := by
  intro G _ a
  simp

example : ∀ {R : Type*} [CommRing R] (x : R), x + -x = 0 := by
  intro R _ x
  simp
