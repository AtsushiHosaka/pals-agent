import Mathlib.NumberTheory.Niven
import Mathlib.Tactic

open Filter Topology

theorem requested_tan_one_degree_irrational : Irrational (Real.tan (Real.pi / 180)) := by
  intro h
  obtain ⟨q, hq⟩ := h
  have hcpos : 0 < Real.cos (Real.pi / 180) :=
    Real.cos_pos_of_mem_Ioo ⟨by linarith [Real.pi_pos], by linarith [Real.pi_pos]⟩
  have hcne : Real.cos (Real.pi / 180) ≠ 0 := ne_of_gt hcpos
  have hs : Real.sin (Real.pi / 180) = (q : ℝ) * Real.cos (Real.pi / 180) := by
    apply (div_eq_iff hcne).mp
    simpa only [Real.tan_eq_sin_div_cos] using hq.symm
  have hcircle := Real.sin_sq_add_cos_sq (Real.pi / 180)
  have hqden : 0 < 1 + (q : ℝ) ^ 2 := by positivity
  have hc_double : Real.cos (2 * (Real.pi / 180)) =
      (((1 - q ^ 2) / (1 + q ^ 2) : ℚ) : ℝ) := by
    push_cast
    apply (eq_div_iff (ne_of_gt hqden)).mpr
    rw [Real.cos_two_mul]
    rw [hs] at hcircle
    nlinarith
  have hv := niven_angle_div_pi_eq (r := (1 / 90 : ℚ))
    (by
      refine ⟨(1 - q ^ 2) / (1 + q ^ 2), ?_⟩
      convert hc_double using 1 <;> push_cast <;> ring)
    (by norm_num : (1 / 90 : ℚ) ∈ Set.Icc 0 1)
  norm_num at hv
