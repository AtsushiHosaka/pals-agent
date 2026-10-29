import Mathlib

theorem idempotent_decomposition_unique {K V : Type*} [Field K]
    [AddCommGroup V] [Module K V] (p : V →ₗ[K] V)
    (hp : p.comp p = p) (x : V) :
    ∃ u ∈ LinearMap.range p, ∃ v ∈ LinearMap.ker p,
      x = u + v ∧ ∀ u' ∈ LinearMap.range p, ∀ v' ∈ LinearMap.ker p,
        x = u' + v' → u' = u ∧ v' = v := by
  have hid (z : V) : p (p z) = p z := LinearMap.congr_fun hp z
  refine ⟨p x, ⟨x, rfl⟩, x - p x, ?_, ?_, ?_⟩
  · change p (x - p x) = 0
    rw [map_sub, hid, sub_self]
  · abel
  · intro u hu v hv hx
    obtain ⟨z, rfl⟩ := hu
    have hv0 : p v = 0 := hv
    have heq : p x = p z := by
      rw [hx, map_add, hid, hv0, add_zero]
    constructor
    · exact heq.symm
    · rw [heq, hx]
      abel
