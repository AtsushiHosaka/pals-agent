import Mathlib

theorem sample_comp_injective {α β γ : Type*} (f : α → β) (g : β → γ)
    (hf : Function.Injective f) (hg : Function.Injective g) :
    Function.Injective (g ∘ f) := by
  intro x y hxy
  have hgfx :
      g (f x) = g (f y) := hxy
  have hfxy :
      f x = f y := hg hgfx
  exact hf hfxy
