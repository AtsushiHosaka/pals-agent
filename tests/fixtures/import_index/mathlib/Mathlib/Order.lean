module

/-! The order basics. -/

@[expose] public section

theorem Order.le_self {a : Nat} : a ≤ a := Nat.le_refl a
