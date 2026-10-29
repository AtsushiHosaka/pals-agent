import Mathlib
open CategoryTheory

theorem pasted_square_cancellation {C : Type*} [Category C]
    {A B D E F G : C} (top : A ⟶ B) (top' : B ⟶ D)
    (left : A ⟶ E) (middle : B ⟶ F) (right : D ⟶ G)
    (bottom : E ⟶ F) (bottom' : F ⟶ G)
    (h₁ : CommSq top left middle bottom)
    (h₂ : CommSq top' middle right bottom') :
    CommSq (top ≫ top') left right (bottom ≫ bottom') := by
  constructor
  calc
    (top ≫ top') ≫ right = top ≫ (top' ≫ right) := Category.assoc _ _ _
    _ = top ≫ (middle ≫ bottom') := by rw [h₂.w]
    _ = (top ≫ middle) ≫ bottom' := (Category.assoc _ _ _).symm
    _ = (left ≫ bottom) ≫ bottom' := by rw [h₁.w]
    _ = left ≫ (bottom ≫ bottom') := Category.assoc _ _ _
