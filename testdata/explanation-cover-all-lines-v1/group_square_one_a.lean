import Mathlib.Algebra.Group.Basic

theorem pals_target_ef91c2d5853b6dd0e414face198ad534
    {G : Type*} [Group G] (h : ∀ g : G, g * g = 1) :
    ∀ a b : G, a * b = b * a := by
  intro a b
  have ha : a * a = 1 := h a
  have hb : b * b = 1 := h b
  have hab : (a * b) * (a * b) = 1 := h (a * b)
  have hababab : a * b * a * b = 1 := by
    simpa [mul_assoc] using hab
  have hainv : a⁻¹ = a := by
    calc
      a⁻¹ = a⁻¹ * 1 := by simp
      _ = a⁻¹ * (a * a) := by rw [ha]
      _ = (a⁻¹ * a) * a := by simp [mul_assoc]
      _ = 1 * a := by rw [inv_mul_cancel]
      _ = a := by simp
  have hbinv : b⁻¹ = b := by
    calc
      b⁻¹ = b⁻¹ * 1 := by simp
      _ = b⁻¹ * (b * b) := by rw [hb]
      _ = (b⁻¹ * b) * b := by simp [mul_assoc]
      _ = 1 * b := by rw [inv_mul_cancel]
      _ = b := by simp
  have hleft : a * (a * b * a * b) = a * 1 :=
    congrArg (fun x : G => a * x) hababab
  have h_bab : b * a * b = a := by
    calc
      b * a * b = (a * a) * (b * a * b) := by rw [ha]; simp
      _ = a * (a * b * a * b) := by simp [mul_assoc]
      _ = a * 1 := hleft
      _ = a := by simp
  have hright : (b * a * b) * b = a * b :=
    congrArg (fun x : G => x * b) h_bab
  have hcomm : b * a = a * b := by
    simpa [mul_assoc, hb] using hright
  exact hcomm.symm
