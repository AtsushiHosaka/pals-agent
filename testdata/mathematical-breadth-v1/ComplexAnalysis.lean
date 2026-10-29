import Mathlib

theorem entire_bounded_below_constant (f : ℂ → ℂ) (eps : ℝ)
    (hf : Differentiable ℂ f) (heps : 0 < eps) (hb : ∀ z, eps ≤ ‖f z‖) :
    ∀ z, f z = f 0 := by
  have hn (z : ℂ) : f z ≠ 0 := by
    intro hz
    have h := hb z
    rw [hz, norm_zero] at h
    linarith
  have hg : Differentiable ℂ (fun z => (f z)⁻¹) := hf.inv hn
  have hbounded : Bornology.IsBounded (Set.range (fun z => (f z)⁻¹)) := by
    apply (isBounded_iff_forall_norm_le).mpr
    refine ⟨eps⁻¹, ?_⟩
    rintro y ⟨z, rfl⟩
    rw [norm_inv]
    exact (inv_le_inv₀ (lt_of_lt_of_le heps (hb z)) heps).mpr (hb z)
  intro z
  have hi := hg.apply_eq_apply_of_bounded hbounded z 0
  exact inv_injective hi
