module

public import Mathlib.RingTheory.Flat.Basic
import StacksCore.Tactic.StacksAttribute

/-!
# Flat modules and a decoy

Tag 00DJ is the definition of a flat module. This sentence has a "string-like" quote and a -- dash run.

## References

* [Stacks Project, Tag 00DK](https://stacks.math.columbia.edu/tag/00DK)
-/

@[expose] public section

universe u

/- A plain block comment with a decoy `theorem fake : False := by` inside
   /- nested -/ still a comment -/
-- theorem line_comment_decoy : False := by sorry

add_to_stacks 00DJ Module.Flat
add_to_stacks 00DJ "(2) tensor exact" Demo.flat_tensor_injective
add_to_stacks 0ZZZ "relative name" Helper.thing

namespace Demo

variable {R : Type u} [CommRing R] (M : Type*) [AddCommGroup M] [Module R M]
variable {N : Type*} [AddCommGroup N]

/-- A module is *flat* when tensoring preserves injections (Stacks 00DH). -/
@[stacks 00DH "definition", simp]
def FlatLike : Prop := ∀ (N : Type u), True

/-- Flatness is preserved by `{`, "quotes" and commas: a, b, c. -/
@[stacks 00DM "3, a part of the correctness",
  stacks_fixed 00DN]
theorem flat_tensor_injective [Module.Flat R M] (x : M) (hx : x = x) :
    x = x := by
  rfl

/-- Lemma with a universe list and a default argument. -/
lemma universe_demo.{v} (n : ℕ := 3) {α : Type v} (a : α) : a = a := rfl

@[simp]
lemma flat_of_free (hM : Module.Free R M) :
    Module.Flat R M := inferInstance

private lemma hidden_helper : True := trivial

instance : Inhabited (Fin 1) := ⟨0⟩

instance instNamed : Inhabited (Fin 2) := ⟨0⟩

/-- A structure with documented fields. -/
@[stacks 00DH]
structure Presentation (R : Type u) [CommRing R] extends Inhabited (Fin 1) where
  /-- Number of generators. -/
  gens : ℕ
  /-- Number of relations. -/
  rels : ℕ

section Inner

variable (S : Type*) [CommRing S]

theorem inner_thing [Algebra R S] : Nonempty (R →+* S) := ⟨algebraMap R S⟩

end Inner

theorem after_section (x : N) : x = x := rfl

open Function in
theorem uses_open_in (f : ℕ → ℕ) (h : Injective f) : Injective f := h

theorem _root_.Elsewhere.root_named : True := trivial

def matched : ℕ → ℕ
  | 0 => 1
  | n + 1 => n

end Demo

add_to_ega "IV 5.9.1" "ega link" Demo.flat_of_free
