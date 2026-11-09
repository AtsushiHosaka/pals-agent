module

public import Mathlib.Order

@[expose] public section

class Ring (R : Type*) where
  add : R → R → R
  basicMap : Nat → R

export Ring (basicMap)

def Ring.double {R : Type*} [Ring R] (a : R) : R := Ring.add a a
