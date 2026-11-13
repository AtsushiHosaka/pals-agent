import Mathlib

theorem one_div_succ_tendsto :
    Filter.Tendsto (fun n : ℕ => 1 / ((n : ℝ) + 1)) Filter.atTop (nhds 0) :=
  tendsto_one_div_add_atTop_nhds_zero_nat
