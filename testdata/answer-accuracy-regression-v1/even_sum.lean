import Mathlib

theorem even_sum_of_even (a b : ℤ) (ha : Even a) (hb : Even b) : Even (a + b) :=
  ha.add hb
