import Mathlib

theorem sq_sub_sq_general {R : Type*} [CommRing R] (a b : R) :
    a ^ 2 - b ^ 2 = (a + b) * (a - b) := by ring
