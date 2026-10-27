import Mathlib.Geometry.Euclidean.PerpBisector
import Mathlib.Analysis.InnerProductSpace.PiL2
import Mathlib.Tactic.NormNum

open scoped RealInnerProductSpace

/- These coordinates are counterexample witnesses, never input premises for a proof request. -/
namespace PalsGeometryNegatives

abbrev Plane := EuclideanSpace ℝ (Fin 2)

def A : Plane := !₂[0, 1]
def B : Plane := !₂[0, 0]
def C : Plane := !₂[2, 0]
def M : Plane := !₂[1, 0]

theorem midpoint_coordinates : M = midpoint ℝ B C := by
  ext i
  fin_cases i <;> norm_num [A, B, C, M, midpoint_eq_smul_add]

theorem missing_equal_sides_not_orthogonal : ⟪A -ᵥ M, C -ᵥ B⟫ ≠ 0 := by
  norm_num [A, B, C, M, PiLp.inner_apply, Fin.sum_univ_two]

theorem collinear_apex_collapses : dist (0 : ℝ) (-1) = dist (0 : ℝ) 1 ∧
    (0 : ℝ) = midpoint ℝ (-1 : ℝ) 1 ∧ ¬ ((0 : ℝ) ≠ 0) := by
  norm_num [Real.dist_eq, midpoint_eq_smul_add]

end PalsGeometryNegatives
namespace PalsGeometryNegatives

theorem missing_equal_sides_noncollinear : ¬ Collinear ℝ ({A, B, C} : Set Plane) := by
  intro h
  obtain ⟨v, hv⟩ := (collinear_iff_of_mem (by simp : B ∈ ({A, B, C} : Set Plane))).mp h
  obtain ⟨r, hr⟩ := hv A (by simp)
  obtain ⟨s, hs⟩ := hv C (by simp)
  have hr0 := congrArg (fun p : Plane => p 0) hr
  have hr1 := congrArg (fun p : Plane => p 1) hr
  have hs0 := congrArg (fun p : Plane => p 0) hs
  norm_num [A, B, C] at hr0 hr1 hs0
  have hr_ne : r ≠ 0 := by
    intro hzero
    simp [hzero] at hr1
  have hv0 : v 0 = 0 := hr0.resolve_left hr_ne
  simp [hv0] at hs0

def B' : Plane := !₂[-1, 0]
def C' : Plane := !₂[1, 0]

theorem missing_midpoint_equal_sides : dist A B' = dist A C' := by
  simp [dist_eq_norm, EuclideanSpace.norm_eq, A, B', C', Fin.sum_univ_two]

theorem missing_midpoint_not_orthogonal : ⟪A -ᵥ C', C' -ᵥ B'⟫ ≠ 0 := by
  norm_num [A, B', C', PiLp.inner_apply, Fin.sum_univ_two]

end PalsGeometryNegatives
namespace PalsGeometryNegatives

theorem missing_midpoint_noncollinear : ¬ Collinear ℝ ({A, B', C'} : Set Plane) := by
  intro h
  obtain ⟨v, hv⟩ := (collinear_iff_of_mem (by simp : B' ∈ ({A, B', C'} : Set Plane))).mp h
  obtain ⟨r, hr⟩ := hv A (by simp)
  obtain ⟨s, hs⟩ := hv C' (by simp)
  have hr1 := congrArg (fun p : Plane => p 1) hr
  have hs0 := congrArg (fun p : Plane => p 0) hs
  have hs1 := congrArg (fun p : Plane => p 1) hs
  norm_num [A, B', C'] at hr1 hs0 hs1
  have hv1_ne : v 1 ≠ 0 := by
    intro hzero
    simp [hzero] at hr1
  have hs_zero : s = 0 := hs1.resolve_right hv1_ne
  norm_num [hs_zero] at hs0

theorem collapsed_base_not_a_triangle : ¬ Collinear ℝ ({(0 : ℝ), 0, 0} : Set ℝ) → False := by
  simp [collinear_singleton]

end PalsGeometryNegatives

namespace PalsGeometryNegatives

/-- A genuine triangle and true midpoint do not suffice without the equal-side hypothesis. -/
theorem missing_equal_sides_counterexample :
    ¬ Collinear ℝ ({A, B, C} : Set Plane) ∧
    M = midpoint ℝ B C ∧ ⟪A -ᵥ M, C -ᵥ B⟫ ≠ 0 :=
  ⟨missing_equal_sides_noncollinear, midpoint_coordinates, missing_equal_sides_not_orthogonal⟩

/-- A genuine isosceles triangle does not suffice when M is not the midpoint. -/
theorem missing_midpoint_counterexample :
    ¬ Collinear ℝ ({A, B', C'} : Set Plane) ∧
    dist A B' = dist A C' ∧ ⟪A -ᵥ C', C' -ᵥ B'⟫ ≠ 0 :=
  ⟨missing_midpoint_noncollinear, missing_midpoint_equal_sides, missing_midpoint_not_orthogonal⟩

end PalsGeometryNegatives
