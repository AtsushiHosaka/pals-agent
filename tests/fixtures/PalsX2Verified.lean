import Mathlib

open scoped Topology

theorem x2_continuous : Continuous (fun y : ℝ => y ^ 2) := by
  rw [Metric.continuous_iff]
  intro x ε hε
  let δ : ℝ := min 1 (ε / (2 * |x| + 1))
  refine ⟨δ, ?_, ?_⟩
  · dsimp [δ]
    have hden : 0 < (2 * |x| + 1 : ℝ) := by
      positivity
    exact lt_min (by positivity) (div_pos hε hden)
  · intro y hy
    have hy1 : |y - x| < 1 := by
      exact lt_of_lt_of_le hy (by simp [δ])
    have hyabs : |y| ≤ |x| + 1 := by
      have htri : |y| ≤ |y - x| + |x| := by
        calc
          |y| = |(y - x) + x| := by ring_nf
          _ ≤ |y - x| + |x| := abs_add_le _ _
      linarith
    have hyplus : |y + x| ≤ 2 * |x| + 1 := by
      have htri : |y + x| ≤ |y| + |x| := abs_add_le _ _
      linarith
    have hfactor : |y ^ 2 - x ^ 2| = |y - x| * |y + x| := by
      have hpoly : y ^ 2 - x ^ 2 = (y - x) * (y + x) := by ring
      rw [hpoly, abs_mul]
    have hbound : |y ^ 2 - x ^ 2| ≤ |y - x| * (2 * |x| + 1) := by
      rw [hfactor]
      exact mul_le_mul_of_nonneg_left hyplus (abs_nonneg (y - x))
    have hδle : δ ≤ ε / (2 * |x| + 1) := by
      simp [δ]
    have hposden : 0 < (2 * |x| + 1 : ℝ) := by
      positivity
    have hmul : |y - x| * (2 * |x| + 1) < ε := by
      have hltδ : |y - x| < ε / (2 * |x| + 1) :=
        lt_of_lt_of_le hy hδle
      calc
        |y - x| * (2 * |x| + 1) <
            (ε / (2 * |x| + 1)) * (2 * |x| + 1) :=
          mul_lt_mul_of_pos_right hltδ hposden
        _ = ε := by field_simp
    have hlt : |y ^ 2 - x ^ 2| < ε := lt_of_le_of_lt hbound hmul
    simpa [Real.dist_eq] using hlt
