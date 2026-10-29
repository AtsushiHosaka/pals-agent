import Mathlib

theorem unique_intermediate_root (f : ℝ → ℝ) (a b : ℝ)
    (hab : a ≤ b) (hc : ContinuousOn f (Set.Icc a b))
    (hm : StrictMonoOn f (Set.Icc a b)) (ha : f a < 0) (hb : 0 < f b) :
    ∃! x, x ∈ Set.Icc a b ∧ f x = 0 := by
  obtain ⟨x, hx, hfx⟩ := intermediate_value_Icc hab hc ⟨le_of_lt ha, le_of_lt hb⟩
  refine ⟨x, ⟨hx, hfx⟩, ?_⟩
  intro y hy
  exact hm.injOn hy.1 hx (hy.2.trans hfx.symm)
