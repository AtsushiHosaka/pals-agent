import Mathlib

theorem continuous_mul_add_self (f g : ℝ → ℝ) (hf : Continuous f) (hg : Continuous g) :
    Continuous (fun x => f x * g x + f x) := (hf.mul hg).add hf
