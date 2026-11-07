module

/-! # Flat morphisms of schemes

Flatness of a morphism of schemes, Tag 01U2.
-/

@[expose] public section

add_to_stacks 01U2 Module.Flat
add_to_stacks 0AAA Demo.FlatLike

namespace AlgebraicGeometry

/-- A morphism of schemes is flat if its stalk maps are flat. -/
@[stacks 01U2]
theorem Scheme.Hom.flat_iff_stalkMap_flat (f : X ⟶ Y) : Flat f ↔ ∀ x, StalkMapFlat f x := by
  sorry

end AlgebraicGeometry
