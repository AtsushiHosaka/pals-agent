import pytest

from pals_agent.lean_target import (
    LeanTargetDeclaration,
    extract_single_target_declaration,
)


def test_extract_single_target_declaration_returns_the_executable_proposition() -> None:
    target = extract_single_target_declaration(
        "-- theorem decoy : False := by contradiction\n"
        'def note : String := "lemma decoy : False := by contradiction"\n'
        "theorem target (n : Nat) : n = n := by\n"
        "  rfl\n"
    )

    assert target == LeanTargetDeclaration(
        kind="theorem",
        name="target",
        proposition="n = n",
    )


def test_extract_single_target_declaration_rejects_zero_or_multiple_candidates() -> None:
    assert extract_single_target_declaration("def helper : Nat := 1") is None
    assert extract_single_target_declaration(
        "theorem first : True := by trivial\n"
        "lemma second : True := by trivial\n"
    ) is None


@pytest.mark.parametrize("proposition", [
    "let n : Nat := 1; n = n",
    "let n : Nat := 1\n    n = n",
    "let n : Nat := 1; let m : Nat := n; m = n",
    "let n : Nat := let m : Nat := 1; m; n = n",
    "(let n : Nat := 1; n = n)",
    "let f : Nat → Nat := fun n => n; f 1 = 1",
    "let n : Nat := if True then 1 else 0; n = n",
])
def test_let_initializer_is_not_the_outer_proof_assignment(proposition: str) -> None:
    source = f"theorem target : {proposition} := by rfl"
    assert extract_single_target_declaration(source) == LeanTargetDeclaration(
        kind="theorem", name="target", proposition=" ".join(proposition.split()),
    )


def test_matrix_layout_let_preserves_the_complete_two_sided_target() -> None:
    proposition = (
        "let E : Matrix (Fin 2) (Fin 2) K :=\n"
        "      fun i j => if h : i = j then (0 : K) else (1 : K)\n"
        "    E * E = 1 ∧ E * E = 1"
    )
    source = f"theorem target (K : Type) [Field K] :\n    {proposition} := by\n  dsimp"
    result = extract_single_target_declaration(source)
    assert result is not None
    assert result.proposition == " ".join(proposition.split())
    assert result.proposition.endswith("E * E = 1 ∧ E * E = 1")


@pytest.mark.parametrize("proposition", [
    "let n : Nat := by have h : Nat := 1; exact h; n = n",
    "let n : Nat := match 1 with | k => k; n = n",
    "let f : Nat → Nat := do return 1; f 1 = 1",
    "let rec f (n : Nat) : Nat := n; f 1 = 1",
    "letI inst : Inhabited Nat := ⟨1⟩; True",
    "have h : Nat := 1; h = h",
])
def test_unsupported_unparenthesized_term_blocks_fail_closed(proposition: str) -> None:
    # A local assignment inside these blocks must never become a truncated QA target.
    assert extract_single_target_declaration(f"example : {proposition} := by rfl") is None


def test_parenthesized_initializer_can_contain_a_tactic_local_assignment() -> None:
    proposition = "let n : Nat := (by have h : Nat := 1; exact h); n = n"
    target = extract_single_target_declaration(f"example : {proposition} := rfl")
    assert target == LeanTargetDeclaration(kind="example", name=None, proposition=proposition)


def test_keyword_decoys_do_not_create_let_initializer_debt() -> None:
    source = (
        "theorem target (outlet let' : Nat) :\n"
        " /- let n := 1; have fake := 2 -/ outlet = outlet := by rfl"
    )
    target = extract_single_target_declaration(source)
    assert target is not None
    assert target.proposition == "outlet = outlet"
