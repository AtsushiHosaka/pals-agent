import Mathlib.Topology.Algebra.Monoid
import Mathlib.Topology.Instances.Real.Lemmas

open Filter Topology

theorem requested_natural_power_continuous (n : ℕ) : Continuous (fun x : ℝ => x ^ n) := by
  induction n with
  | zero => simpa using (continuous_const : Continuous (fun _ : ℝ => (1 : ℝ)))
  | succ n ih => simpa only [pow_succ, Pi.mul_apply, id_eq] using ih.fun_mul continuous_id
