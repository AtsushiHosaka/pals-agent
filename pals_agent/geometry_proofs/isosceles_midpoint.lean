import Mathlib.Geometry.Euclidean.PerpBisector

open scoped RealInnerProductSpace

namespace PalsGeometry

variable {V P : Type*} [NormedAddCommGroup V] [InnerProductSpace ℝ V]
  [MetricSpace P] [NormedAddTorsor V P]

/-- Step 1: a genuine triangle has a nonzero base. -/
theorem base_distinct (A B C : P)
    (h_triangle : ¬ Collinear ℝ ({A, B, C} : Set P)) : B ≠ C :=
  ne₂₃_of_not_collinear h_triangle

/-- Step 2: the apex of a genuine triangle is not the base midpoint. -/
theorem apex_distinct_midpoint (A B C M : P)
    (h_triangle : ¬ Collinear ℝ ({A, B, C} : Set P))
    (h_midpoint : M = midpoint ℝ B C) : A ≠ M := by
  intro h
  apply h_triangle
  rw [h, h_midpoint]
  simpa [Set.insert_comm] using (wbtw_midpoint ℝ B C).collinear

/-- Step 3: equal side lengths put the apex on the perpendicular bisector. -/
theorem apex_mem_perpBisector (A B C : P)
    (h_equal_sides : dist A B = dist A C) : A ∈ AffineSubspace.perpBisector B C :=
  AffineSubspace.mem_perpBisector_iff_dist_eq.mpr h_equal_sides

/-- Step 4: the perpendicular bisector characterization gives orthogonal directions. -/
theorem midpoint_orthogonality (A B C M : P)
    (h_bisector : A ∈ AffineSubspace.perpBisector B C)
    (h_midpoint : M = midpoint ℝ B C) : ⟪A -ᵥ M, C -ᵥ B⟫ = 0 := by
  rw [h_midpoint]
  exact AffineSubspace.mem_perpBisector_iff_inner_eq_zero.mp h_bisector

/-- Step 5: AM and BC are nondegenerate and perpendicular in the affine inner-product model. -/
theorem isosceles_midpoint_perpendicular (A B C M : P)
    (h_triangle : ¬ Collinear ℝ ({A, B, C} : Set P))
    (h_equal_sides : dist A B = dist A C)
    (h_midpoint : M = midpoint ℝ B C) :
    B ≠ C ∧ A ≠ M ∧ ⟪A -ᵥ M, C -ᵥ B⟫ = 0 := by
  have h_base := base_distinct A B C h_triangle
  have h_apex := apex_distinct_midpoint A B C M h_triangle h_midpoint
  have h_bisector := apex_mem_perpBisector A B C h_equal_sides
  have h_orthogonal := midpoint_orthogonality A B C M h_bisector h_midpoint
  exact ⟨h_base, h_apex, h_orthogonal⟩

end PalsGeometry
