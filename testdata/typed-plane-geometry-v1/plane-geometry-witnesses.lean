import Mathlib

structure Point2 where
  x : ℝ
  y : ℝ

structure Vector2 where
  x : ℝ
  y : ℝ

structure Line2 where
  a : ℝ
  b : ℝ
  c : ℝ

structure Circle2 where
  center : Point2
  radiusSq : ℝ

def distanceSq (p q : Point2) : ℝ :=
  (p.x - q.x) ^ 2 + (p.y - q.y) ^ 2

def incidentPointLine (p : Point2) (line : Line2) : Prop :=
  line.a * p.x + line.b * p.y + line.c = 0

def incidentPointCircle (p : Point2) (circle : Circle2) : Prop :=
  distanceSq p circle.center = circle.radiusSq

def perpendicular (first second : Line2) : Prop :=
  first.a * second.a + first.b * second.b = 0

def parallel (first second : Line2) : Prop :=
  first.a * second.b = first.b * second.a

-- manifest card: typed_plane_distance_self_zero
example : ∀ p : Point2, distanceSq p p = 0 := by
  intro p
  simp [distanceSq]

-- manifest card: typed_plane_line_through_two_points
example :
    ∃ line : Line2,
      incidentPointLine ⟨0, 1⟩ line ∧ incidentPointLine ⟨2, 5⟩ line := by
  refine ⟨⟨-2, 1, -1⟩, ?_⟩
  norm_num [incidentPointLine]

-- manifest card: typed_plane_circle_through_three_points
example :
    ∃ circle : Circle2,
      incidentPointCircle ⟨1, 0⟩ circle ∧ incidentPointCircle ⟨0, 1⟩ circle ∧
        incidentPointCircle ⟨-1, 0⟩ circle := by
  refine ⟨⟨⟨0, 0⟩, 1⟩, ?_⟩
  norm_num [incidentPointCircle, distanceSq]

-- manifest card: typed_plane_perpendicular_symmetric
example : ∀ first second : Line2, perpendicular first second → perpendicular second first := by
  intro first second h
  simpa [perpendicular, add_comm, mul_comm] using h

-- manifest card: typed_plane_parallel_symmetric
example : ∀ first second : Line2, parallel first second → parallel second first := by
  intro first second h
  simpa [parallel, mul_comm] using h.symm
