import Mathlib

theorem inter_subset_of_subset_general {α : Type*} (A B C : Set α) (h : A ⊆ C) :
    A ∩ B ⊆ C := fun x hx => h hx.1
