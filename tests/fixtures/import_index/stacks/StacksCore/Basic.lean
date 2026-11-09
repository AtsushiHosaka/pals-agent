module

public import Mathlib.Algebra.Ring

/-! # Core lemma -/

@[expose] public section

theorem Core.ring_lemma {R : Type*} [Ring R] (a : R) : Ring.double a = a + a := by
  sorry
