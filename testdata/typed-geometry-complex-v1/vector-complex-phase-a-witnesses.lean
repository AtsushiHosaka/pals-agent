import Mathlib

structure Vector2 where
  x : ℝ
  y : ℝ

def vectorAdd (u v : Vector2) : Vector2 := ⟨u.x + v.x, u.y + v.y⟩

def vectorScale (a : ℝ) (u : Vector2) : Vector2 := ⟨a * u.x, a * u.y⟩

def dot (u v : Vector2) : ℝ := u.x * v.x + u.y * v.y

def determinant2 (u v : Vector2) : ℝ := u.x * v.y - u.y * v.x

-- manifest card: typed_vector2_component_addition
example : vectorAdd (Vector2.mk 1 2) (Vector2.mk 3 (-1)) = Vector2.mk 4 1 := by
  norm_num [vectorAdd]

-- manifest card: typed_vector2_scalar_multiple
example : vectorScale 3 (Vector2.mk 2 (-1)) = Vector2.mk 6 (-3) := by
  norm_num [vectorScale]

-- manifest card: typed_vector2_dot_product_orthogonality
example : dot (Vector2.mk 1 2) (Vector2.mk 2 (-1)) = 0 := by
  norm_num [dot]

-- manifest card: typed_vector2_triangle_area_determinant
example : |determinant2 (Vector2.mk 2 0) (Vector2.mk 0 3)| / 2 = 3 := by
  norm_num [determinant2]

-- manifest card: typed_complex_cartesian_multiplication
example : ((1 : ℂ) + 2 * Complex.I) * (3 - Complex.I) = 5 + 5 * Complex.I := by
  calc
    ((1 : ℂ) + 2 * Complex.I) * (3 - Complex.I) =
        3 + 5 * Complex.I - 2 * Complex.I ^ 2 := by ring
    _ = 5 + 5 * Complex.I := by rw [Complex.I_sq]; ring

-- manifest card: typed_complex_conjugate_norm_square
example (z : ℂ) : z * star z = (Complex.normSq z : ℂ) := by
  simpa only [Complex.star_def] using Complex.mul_conj z

-- manifest card: typed_complex_multiply_i_quarter_turn
example : ((1 : ℂ) + 2 * Complex.I) * Complex.I = (-2 : ℂ) + Complex.I := by
  calc
    ((1 : ℂ) + 2 * Complex.I) * Complex.I =
        (1 : ℂ) * Complex.I + (2 : ℂ) * Complex.I ^ 2 := by ring
    _ = (-2 : ℂ) + Complex.I := by rw [Complex.I_sq]; ring

-- manifest card: typed_complex_argument_quadrant_two
example : 0 < Complex.arg ((-1 : ℂ) + Complex.I) := by
  by_contra h
  have hle : Complex.arg ((-1 : ℂ) + Complex.I) ≤ 0 := le_of_not_gt h
  have hnonneg : 0 ≤ Complex.arg ((-1 : ℂ) + Complex.I) := by
    rw [Complex.arg_nonneg_iff]
    norm_num
  have hzero : Complex.arg ((-1 : ℂ) + Complex.I) = 0 := le_antisymm hle hnonneg
  have parts := Complex.arg_eq_zero_iff.mp hzero
  norm_num at parts
