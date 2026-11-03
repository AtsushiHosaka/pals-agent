import Mathlib.Topology.Instances.Real.Lemmas
import Mathlib.Tactic

open Filter Topology

theorem requested_right_limit_and_discontinuity (f : ℝ → ℝ)
    (hzero : f 0 = 1) (hpos : ∀ x, 0 < x → f x = 0) :
    Tendsto f (𝓝[>] (0 : ℝ)) (𝓝 0) ∧ ¬ ContinuousAt f 0 := by
  have heq : f =ᶠ[𝓝[>] (0 : ℝ)] (fun _ => (0 : ℝ)) := by
    filter_upwards [self_mem_nhdsWithin] with x hx
    exact hpos x hx
  have hlim : Tendsto f (𝓝[>] (0 : ℝ)) (𝓝 0) :=
    tendsto_const_nhds.congr' heq.symm
  refine ⟨hlim, ?_⟩
  intro hc
  have hone : Tendsto f (𝓝[>] (0 : ℝ)) (𝓝 1) := by
    simpa [hzero] using hc.tendsto.mono_left nhdsWithin_le_nhds
  have hfalse : (0 : ℝ) = 1 := tendsto_nhds_unique hlim hone
  norm_num at hfalse
