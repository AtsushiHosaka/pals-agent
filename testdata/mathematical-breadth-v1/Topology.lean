import Mathlib

theorem compact_continuous_bijection_inverse {X Y : Type*}
    [TopologicalSpace X] [TopologicalSpace Y] [CompactSpace X] [T2Space Y]
    (f : X → Y) (hf : Continuous f) (hb : Function.Bijective f) :
    ∃ g : Y → X, Continuous g ∧ Function.LeftInverse g f ∧ Function.RightInverse g f := by
  classical
  let e : X ≃ Y := Equiv.ofBijective f hb
  have hclosed : IsClosedMap f := by
    intro s hs
    exact (hs.isCompact.image hf).isClosed
  have he : IsHomeomorph f :=
    isHomeomorph_iff_continuous_isClosedMap_bijective.mpr ⟨hf, hclosed, hb⟩
  refine ⟨e.symm, ?_, e.symm_apply_apply, e.apply_symm_apply⟩
  exact he.homeomorph f |>.symm.continuous
