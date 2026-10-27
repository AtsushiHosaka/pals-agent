import Mathlib

theorem prime_intersection_choice {R : Type*} [CommRing R]
    (I J P : Ideal R) (hp : P.IsPrime) (h : I ⊓ J ≤ P) :
    I ≤ P ∨ J ≤ P := by
  classical
  by_contra hn
  have hI : ¬ I ≤ P := fun hi => hn (Or.inl hi)
  have hJ : ¬ J ≤ P := fun hj => hn (Or.inr hj)
  obtain ⟨x, hxI, hxP⟩ := SetLike.not_le_iff_exists.mp hI
  obtain ⟨y, hyJ, hyP⟩ := SetLike.not_le_iff_exists.mp hJ
  have hxy : x * y ∈ I ⊓ J := by
    constructor
    · exact I.mul_mem_right y hxI
    · exact J.mul_mem_left x hyJ
  rcases hp.mem_or_mem (h hxy) with hx | hy
  · exact hxP hx
  · exact hyP hy
