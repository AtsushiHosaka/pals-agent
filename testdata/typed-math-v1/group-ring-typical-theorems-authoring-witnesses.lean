import Mathlib

example : ∀ {G : Type*} [Group G] (a : G), a⁻¹⁻¹ = a := by
  intro G _ a
  simp

example : ∀ {G : Type*} [Group G], (1 : G)⁻¹ = 1 := by
  intro G _
  simp

example : ∀ {G : Type*} [Group G] (a b c : G), a * b = a * c ↔ b = c := by
  intro G _ a b c
  constructor
  · exact mul_left_cancel
  · intro h
    simp [h]

example : ∀ {G : Type*} [Group G] (a b c : G), b * a = c * a ↔ b = c := by
  intro G _ a b c
  constructor
  · exact mul_right_cancel
  · intro h
    simp [h]

example : ∀ {G : Type*} [Group G] (a x b : G), a * x = b ↔ x = a⁻¹ * b := by
  intro G _ a x b
  constructor
  · intro h
    calc
      x = 1 * x := by simp
      _ = (a⁻¹ * a) * x := by simp
      _ = a⁻¹ * (a * x) := by rw [mul_assoc]
      _ = a⁻¹ * b := by rw [h]
  · intro h
    rw [h]
    simp

example : ∀ {G : Type*} [Group G] (x a b : G), x * a = b ↔ x = b * a⁻¹ := by
  intro G _ x a b
  constructor
  · intro h
    calc
      x = x * 1 := by simp
      _ = x * (a * a⁻¹) := by simp
      _ = (x * a) * a⁻¹ := by rw [mul_assoc]
      _ = b * a⁻¹ := by rw [h]
  · intro h
    rw [h]
    simp [mul_assoc]

example : ∀ {G : Type*} [Group G] (a b : G), a * b = 1 ↔ b = a⁻¹ := by
  intro G _ a b
  constructor
  · intro h
    calc
      b = 1 * b := by simp
      _ = (a⁻¹ * a) * b := by simp
      _ = a⁻¹ * (a * b) := by rw [mul_assoc]
      _ = a⁻¹ * 1 := by rw [h]
      _ = a⁻¹ := by simp
  · intro h
    rw [h]
    simp

example : ∀ {G : Type*} [Group G] (a b : G), (a * b) * b⁻¹ = a := by
  intro G _ a b
  simp [mul_assoc]

example : ∀ {G : Type*} [Group G] (a b : G), a⁻¹ = b⁻¹ ↔ a = b := by
  intro G _ a b
  constructor
  · intro h
    have h' := congrArg Inv.inv h
    simpa using h'
  · intro h
    simp [h]

example : ∀ {R : Type*} [CommRing R] (x : R), - -x = x := by
  intro R _ x
  simp

example : ∀ {R : Type*} [CommRing R], -(0 : R) = 0 := by
  intro R _
  simp

example : ∀ {R : Type*} [CommRing R] (x y z : R), x + y = x + z ↔ y = z := by
  intro R _ x y z
  constructor
  · exact add_left_cancel
  · intro h
    simp [h]

example : ∀ {R : Type*} [CommRing R] (x y z : R), x + y = z ↔ y = z + -x := by
  intro R _ x y z
  constructor
  · intro h
    calc
      y = 0 + y := by simp
      _ = (-x + x) + y := by simp
      _ = -x + (x + y) := by rw [add_assoc]
      _ = -x + z := by rw [h]
      _ = z + -x := by rw [add_comm]
  · intro h
    calc
      x + y = x + (z + -x) := by rw [h]
      _ = (x + -x) + z := by ac_rfl
      _ = 0 + z := by simp
      _ = z := by simp

example : ∀ {R : Type*} [CommRing R] (x y : R), x + y = 0 ↔ x = -y := by
  intro R _ x y
  constructor
  · intro h
    calc
      x = x + 0 := by simp
      _ = x + (y + -y) := by simp
      _ = (x + y) + -y := by rw [add_assoc]
      _ = 0 + -y := by rw [h]
      _ = -y := by simp
  · intro h
    rw [h]
    simp

example : ∀ {R : Type*} [CommRing R] (x y : R), -(x + y) = -x + -y := by
  intro R _ x y
  simp [add_comm]

example : ∀ {R : Type*} [CommRing R] (x y : R), (-x) * y = -(x * y) := by
  intro R _ x y
  simp

example : ∀ {R : Type*} [CommRing R] (x y : R), (-x) * (-y) = x * y := by
  intro R _ x y
  simp

example : ∀ {R : Type*} [CommRing R] (x : R), x * 0 = 0 := by
  intro R _ x
  simp

example : ∀ {R : Type*} [CommRing R] (x y : R), (x + y) * (x + y) = x * x + (x * y + (y * x + y * y)) := by
  intro R _ x y
  ring

example : ∀ {R : Type*} [CommRing R] (x y : R), (x + y) * (x + -y) = x * x + -(y * y) := by
  intro R _ x y
  ring

example : ∀ {R : Type*} [CommRing R] [IsDomain R] (x y : R), x * y = 0 → x = 0 ∨ y = 0 := by
  intro R _ _ x y h
  exact eq_zero_or_eq_zero_of_mul_eq_zero h

example : ∀ {R : Type*} [CommRing R] [IsDomain R] (x : R), x * x = 0 → x = 0 := by
  intro R _ _ x h
  exact mul_self_eq_zero.mp h
