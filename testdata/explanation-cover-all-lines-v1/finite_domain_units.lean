import Mathlib

theorem pals_target_b8862def4da290baa88c7a46684d43c9
    (R : Type*) [CommRing R] [Nontrivial R] [NoZeroDivisors R] [Finite R] :
    ∀ a : R, a ≠ 0 → IsUnit a := by
  intro a ha
  let f : R → R := fun x => a * x

  have hf : Function.Injective f := by
    intro x y hxy
    have hmul : a * x = a * y := hxy
    have hdiff : a * (x - y) = 0 := by
      calc
        a * (x - y) = a * x - a * y := by rw [mul_sub]
        _ = 0 := by rw [hmul, sub_self]
    have hzero : x - y = 0 := (mul_eq_zero.mp hdiff).resolve_left ha
    exact sub_eq_zero.mp hzero

  have hsurj : Function.Surjective f :=
    Finite.surjective_of_injective hf

  have hone : (1 : R) ∈ Set.range f := by
    obtain ⟨b, hb⟩ := hsurj 1
    exact ⟨b, hb⟩

  obtain ⟨b, hb⟩ := hone
  have hab : a * b = 1 := by
    change f b = 1 at hb
    exact hb

  have hunit : IsUnit a := by
    apply isUnit_iff_exists_inv.mpr
    exact ⟨b, hab⟩

  exact hunit
