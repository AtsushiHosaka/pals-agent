import Mathlib

theorem requested_linear_injective_iff_zero_kernel {K V W : Type*} [Field K]
    [AddCommGroup V] [AddCommGroup W] [Module K V] [Module K W] (f : V →ₗ[K] W) :
    Function.Injective f ↔ ∀ x, f x = 0 → x = 0 := by
  constructor
  · intro hinj x hx
    apply hinj
    simpa using hx
  · intro hzero x y hxy
    have hsub : f (x - y) = 0 := by rw [map_sub, hxy, sub_self]
    exact sub_eq_zero.mp (hzero (x - y) hsub)
