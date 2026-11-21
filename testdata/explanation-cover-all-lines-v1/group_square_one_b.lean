import Mathlib.Algebra.Group.Basic

theorem pals_target_c6b63a0efadfcfce9349f78d24aacdae
    {G : Type*} [Group G] (h : ∀ g : G, g * g = 1) :
    ∀ a b : G, a * b = b * a := by
  intro a b
  have ha : a * a = 1 := h a
  have hb : b * b = 1 := h b
  have ha_inv : a⁻¹ = a := by
    have haux := congrArg (fun x : G => a⁻¹ * x) ha
    simpa [mul_assoc] using haux.symm
  have hb_inv : b⁻¹ = b := by
    have haux := congrArg (fun x : G => b⁻¹ * x) hb
    simpa [mul_assoc] using haux.symm

  have hab : (a * b) * (a * b) = 1 := h (a * b)
  have hab_inv : (a * b)⁻¹ = a * b := by
    have haux := congrArg (fun x : G => (a * b)⁻¹ * x) hab
    simpa [mul_assoc] using haux.symm

  have hprod : (a * b)⁻¹ = b * a := by
    rw [mul_inv_rev, hb_inv, ha_inv]
  calc
    a * b = (a * b)⁻¹ := hab_inv.symm
    _ = b * a := hprod
