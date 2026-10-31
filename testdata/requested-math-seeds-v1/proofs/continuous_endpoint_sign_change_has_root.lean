import Mathlib.Topology.Order.IntermediateValue
import Mathlib.Topology.Instances.Real.Lemmas

open Filter Topology

theorem requested_continuous_endpoint_sign_change_has_root (f : ℝ → ℝ) (a b : ℝ)
    (hab : a ≤ b) (hf : ContinuousOn f (Set.Icc a b)) (ha : f a < 0) (hb : 0 < f b) :
    ∃ x ∈ Set.Icc a b, f x = 0 := by
  exact intermediate_value_Icc hab hf ⟨le_of_lt ha, le_of_lt hb⟩
