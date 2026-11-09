module

public import Mathlib.Order

public theorem Order.le_self_dup {a : Nat} : a ≤ a := Nat.le_refl a

public theorem Order.le_self {a : Nat} : a ≤ a := Nat.le_refl a
