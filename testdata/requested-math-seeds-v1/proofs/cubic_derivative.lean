import Mathlib

open Filter Topology

theorem requested_cubic_derivative (x : ℝ) :
    HasDerivAt (fun y : ℝ => y ^ 3 - 3 * y) (3 * x ^ 2 - 3) x := by
  simpa [id_eq] using ((hasDerivAt_id x).fun_pow 3).fun_sub ((hasDerivAt_id x).const_mul 3)
