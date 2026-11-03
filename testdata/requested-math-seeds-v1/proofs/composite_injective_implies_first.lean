import Mathlib.Logic.Function.Basic

theorem requested_composite_injective_implies_first {A B C : Type*} (f : A → B) (g : B → C)
    (h : Function.Injective (g ∘ f)) : Function.Injective f := by
  intro x y hxy
  apply h
  change g (f x) = g (f y)
  rw [hxy]
