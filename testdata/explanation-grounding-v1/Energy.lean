import Mathlib.Data.Real.Basic
import Mathlib.Tactic

/- Original synthetic optimization case. These definitions specify the objects;
they assert no probabilistic, exponential or analytic interpretation. -/
def sampleEnergy (a b c t : ℝ) : ℝ :=
  (t - a) ^ 2 + (t - b) ^ 2 + (t - c) ^ 2

noncomputable def energyCentre (a b c : ℝ) : ℝ := (a + b + c) / 3

noncomputable def energyMinimum (a b c : ℝ) : ℝ :=
  ((a - b) ^ 2 + (b - c) ^ 2 + (c - a) ^ 2) / 3

theorem sample_energy_unique_minimum (a b c : ℝ) :
    (∀ t : ℝ, energyMinimum a b c ≤ sampleEnergy a b c t) ∧
    (∀ t : ℝ, sampleEnergy a b c t = energyMinimum a b c ↔
      t = energyCentre a b c) := by
  have decomposition :
      ∀ t : ℝ, sampleEnergy a b c t =
        3 * (t - energyCentre a b c) ^ 2 + energyMinimum a b c := by
    intro t
    dsimp [sampleEnergy, energyCentre, energyMinimum]
    ring
  constructor
  · intro t
    nlinarith [decomposition t, sq_nonneg (t - energyCentre a b c)]
  · intro t
    constructor
    · intro hminimum
      have hzero :
          (t - energyCentre a b c) ^ 2 = 0 := by
        nlinarith [decomposition t]
      exact sub_eq_zero.mp (sq_eq_zero_iff.mp hzero)
    · intro hcentre
      rw [hcentre, decomposition]
      ring
