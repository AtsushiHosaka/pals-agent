import Mathlib.LinearAlgebra.FiniteDimensional.Lemmas

theorem requested_rank_nullity {K V W : Type*} [DivisionRing K]
    [AddCommGroup V] [AddCommGroup W] [Module K V] [Module K W]
    [FiniteDimensional K V] (f : V →ₗ[K] W) :
    Module.finrank K (LinearMap.range f) + Module.finrank K (LinearMap.ker f) =
      Module.finrank K V := by
  exact f.finrank_range_add_finrank_ker
