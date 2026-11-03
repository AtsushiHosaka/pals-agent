from __future__ import annotations

import time

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_source_policy import (
    declared_theorem_names,
    find_source_violation,
    strip_lean_comments_and_strings,
    with_auditable_examples,
)

FORGED = "theorem forged_false : (1 : Nat) = 2 := by simp\n"
PAYLOAD = "(IO.Process.exit 0 : IO Unit)"


@pytest.mark.parametrize(
    "source",
    [
        # The reproduced exploit and its command-position variants.
        f"open Nat in #eval {PAYLOAD}\n{FORGED}",
        f"section\nopen Nat in #eval {PAYLOAD}\nend\n{FORGED}",
        f"namespace N\nsection S\n  #eval {PAYLOAD}\nend S\nend N\n{FORGED}",
        f"set_option maxRecDepth 512 in #eval {PAYLOAD}\n{FORGED}",
        f"theorem t : True := trivial #eval {PAYLOAD}\n{FORGED}",
        f"def x := 1;#eval {PAYLOAD}\n{FORGED}",
        f"#exit\n{FORGED}",
        f"#eval! {PAYLOAD}\n{FORGED}",
        f"#guard_msgs in #eval {PAYLOAD}\n{FORGED}",
        f"#unknown_future_command x\n{FORGED}",
    ],
)
def test_number_sign_commands_are_rejected_at_any_position(source: str) -> None:
    violation = find_source_violation(source)

    assert violation is not None
    assert violation.code == "lean.disallowed_interactive_command"


@pytest.mark.parametrize(
    ("snippet", "token"),
    [
        (f"run_cmd {PAYLOAD}", "run_cmd"),
        (f"run_elab {PAYLOAD}", "run_elab"),
        (f"run_meta {PAYLOAD}", "run_meta"),
        (f"open Nat in run_meta {PAYLOAD}", "run_meta"),
        (f"example : True := by\n  run_tac {PAYLOAD}\n  trivial", "run_tac"),
        (f"example : True := by\n  conv => run_conv {PAYLOAD}\n  trivial", "run_conv"),
        (f"example : True := by_elab do {PAYLOAD}", "by_elab"),
        ("initialize x : IO.Ref Nat ← IO.mkRef 0", "initialize"),
        ("builtin_initialize x : IO.Ref Nat ← IO.mkRef 0", "builtin_initialize"),
        ("elab_rules : tactic | _ => pure ()", "elab_rules"),
        ('elab "x" : tactic => pure ()', "elab"),
        ('macro "x" : tactic => `(tactic| trivial)', "macro"),
        ("simproc reduceFoo (_) := fun _ => pure .continue", "simproc"),
        ("dsimproc reduceFoo (_) := fun _ => pure .continue", "dsimproc"),
        ("simproc_decl reduceFoo (_) := fun _ => pure .continue", "simproc_decl"),
        ("cbv_simproc reduceFoo (_) := fun _ => pure .continue", "cbv_simproc"),
        ("grind_propagator foo := fun _ => pure ()", "grind_propagator"),
        ("example : Nat := eval_expr% 1", "eval_expr"),
        ("declare_config_elab elabFoo Foo", "declare_config_elab"),
        ("register_simp_attr foo", "register_simp_attr"),
        ("compile_inductive% Nat", "compile_inductive"),
        ('add_aesop_rules safe (by trivial)', "add_aesop_rules"),
        ("sudo set_option debug.skipKernelTC true", "sudo"),
        ("unsafe def bad : Nat := unsafeCast ()", "unsafe"),
        ("def bad : Nat := match (IO.Process.exit 0 : IO Unit) x with | _ => 1", "IO"),
        ("open IO in\ndef bad := Process.exit 0", "IO"),
        ("example : True := by\n  polyrith", "polyrith"),
    ],
)
def test_code_execution_family_is_rejected(snippet: str, token: str) -> None:
    violation = find_source_violation(f"{snippet}\n{FORGED}")

    assert violation is not None
    assert violation.code in {
        "lean.disallowed_metaprogramming",
        "lean.disallowed_syntax_quotation",
        "lean.disallowed_trusted_declaration",
    }
    assert token in violation.message or violation.code.endswith("syntax_quotation")


@pytest.mark.parametrize(
    "source",
    [
        "theorem t : 2 ^ 40 > 0 := by native_decide",
        "theorem t : 2 ^ 40 > 0 := by decide +native",
        "theorem t : 2 ^ 40 > 0 := by decide (config := { native := true })",
        "theorem t : True := Lean.ofReduceBool f true rfl",
        "theorem t (x : BitVec 8) : x = x := by bv_decide",
    ],
)
def test_native_evaluation_is_rejected(source: str) -> None:
    violation = find_source_violation(source)

    assert violation is not None
    assert violation.code == "lean.disallowed_native_evaluation"


@pytest.mark.parametrize(
    "attribute",
    [
        "@[implemented_by evil] def f : Nat := 0",
        '@[extern "exit"] def f : Nat := 0',
        "@[csimp] theorem f : Nat.add = Nat.add := rfl",
        "@[init evil] def f : IO Unit := pure ()",
        "@[builtin_init evil] def f : IO Unit := pure ()",
        "@[command_elab Lean.Parser.Command.check] def f := 0",
        "@[term_elab foo] def f := 0",
        "@[tactic foo] def f := 0",
        "@[macro foo] def f := 0",
        "@[norm_num Nat.succ _] def f := 0",
        "@[positivity _] def f := 0",
        "@[simproc] def f := 0",
        "@[aesop safe tactic] def f := 0",
        "@[simp, implemented_by evil] def f : Nat := 0",
        "@[«implemented_by» evil] def f : Nat := 0",
        "@[local command_elab foo] def f := 0",
        "@[to_additive (attr := command_elab foo)] def f := 0",
        "attribute [implemented_by evil] f",
        "attribute [local command_elab foo] f",
        "attribute[scoped tactic foo] f",
        "open Nat in @[implemented_by evil] def f : Nat := 0",
    ],
)
def test_unlisted_attributes_are_rejected(attribute: str) -> None:
    violation = find_source_violation(attribute)

    assert violation is not None
    assert violation.code in {"lean.disallowed_attribute", "lean.disallowed_metaprogramming"}


@pytest.mark.parametrize(
    "option",
    [
        "set_option debug.skipKernelTC true",
        "set_option bootstrap.inductiveCheckResultingUniverse false",
        "set_option compiler.extract_closed false",
        "set_option «debug.skipKernelTC» true",
        "set_option interpreter.prefer_native true",
    ],
)
def test_unlisted_options_are_rejected(option: str) -> None:
    violation = find_source_violation(f"{option} in\n{FORGED}")

    assert violation is not None
    assert violation.code == "lean.disallowed_option"


@pytest.mark.parametrize(
    "source",
    [
        # Lean reads each of these as code followed by `#eval`; the former
        # stripper treated the `#eval` as string or comment content.
        f"def a := '\"'\n#eval {PAYLOAD}\ndef b := '\"'\n{FORGED}",
        f"def a := '\\\"'\n#eval {PAYLOAD}\ndef b := '\\\"'\n{FORGED}",
        f'def s := r"\\"\n#eval {PAYLOAD}\n-- "\n{FORGED}',
        f'def s := r#"x"#\n#eval {PAYLOAD}\n{FORGED}',
        f"def «\"» := 1\n#eval {PAYLOAD}\ndef «\"x» := 1\n{FORGED}",
        f"def «--» := 1 #eval {PAYLOAD}\n{FORGED}",
        f"def «/-» := 1\n#eval {PAYLOAD}\ndef «-/» := 1\n{FORGED}",
        f"def a := '«' run_cmd {PAYLOAD} '»'\n{FORGED}",
        f'example := f ⁻¹\'"\' a " #eval {PAYLOAD} -- "\n{FORGED}',
        f'def s := s!"{{ "a" }}"\n{FORGED}',
        "def a := '\"'\naxiom bad : False\ndef b := '\"'\ntheorem t : False := bad",
        'def s := "unterminated',
        "/- unterminated",
        "def a := «unterminated",
    ],
)
def test_lexically_ambiguous_sources_are_rejected(source: str) -> None:
    assert find_source_violation(source) is not None


@pytest.mark.parametrize(
    "source",
    [
        'notation "a--" => (1 : Nat)\ntheorem t : a-- #eval 1\n  = 1 := rfl',
        'infixl:65 " /- " => Nat.add',
        'infix " x " => Nat.add',
        'infixr:65 " x " => Nat.add',
        'prefix:max "x" => Nat.succ',
        'prefix "x" => Nat.succ',
        'postfix:max "x" => Nat.succ',
        'local notation "x" => Nat.zero',
        'scoped notation "x" => Nat.zero',
        'notation3 "x" => Nat.zero',
        'binder_predicate x " > " y:term => `($x > $y)',
    ],
)
def test_token_defining_commands_are_rejected(source: str) -> None:
    violation = find_source_violation(source)

    assert violation is not None
    assert violation.code in {
        "lean.disallowed_metaprogramming",
        "lean.disallowed_syntax_quotation",
    }


@pytest.mark.parametrize(
    "source",
    [
        "example : True := by\n  aesop (add safe tactic evil)",
        "example : True := by\n  aesop (config := { maxRuleApplications := 1 }) (add norm evil)",
    ],
)
def test_aesop_inline_rule_additions_are_rejected(source: str) -> None:
    violation = find_source_violation(source)

    assert violation is not None
    assert violation.code == "lean.disallowed_metaprogramming"


def test_module_system_header_is_rejected() -> None:
    violation = find_source_violation("module\n\npublic import Mathlib\n")

    assert violation is not None
    assert violation.code == "lean.disallowed_metaprogramming"


@pytest.mark.parametrize(
    "source",
    [
        "def a := #[1, 2, 3]\ntheorem t : a.size = 3 := rfl",
        "def a := #[]\n#[1].size",
        "theorem t (h : 1 = 1 ∧ 2 = 2) : 1 = 1 := h.1",
        "open Finset in\ntheorem t (s : Finset ℕ) (h : #s = 0) : s = ∅ := by simpa using h",
        "open Finset in\ntheorem t (s : Finset ℕ) :\n  #s = #s := rfl",
        "open Finset in\ntheorem t (s t : Finset ℕ) : #(s ∪ t) ≤ #s + #t := card_union_le s t",
        "open Finset in\nexample (s : Finset ℕ) : #{x ∈ s | x = 0} ≤ #s := card_filter_le _ _",
        "open Finset in\nexample (s₁ : Finset ℕ) : #s₁ = #s₁ := rfl",
        "open Cardinal in\nexample : #ℕ = ℵ₀ := mk_nat",
        "open Cardinal in\nexample (α : Type) : #α = #α := rfl",
        "example : (#v[1, 2]).size = 2 := rfl",
        "example (f : ℕ → ℕ) (s : Set ℕ) : f '' s = f '' s := rfl",
        "example (f : ℕ → ℕ) (s : Set ℕ) : f ⁻¹' s = f ⁻¹' s := rfl",
        "example (x' x'' : ℕ) (h : x' = x'') : x'' = x' := h.symm",
        "example : 'a' = 'a' := rfl",
        'example : "a#eval run_cmd --" = "a#eval run_cmd --" := rfl',
        "example : (6 : ℕ) / 2 = 3 := by norm_num",
        "/-- doc #eval run_cmd -/\ntheorem t : True := trivial",
        "/-! module doc #eval -/\ntheorem t : True := trivial",
        "/- nested /- #eval -/ run_cmd -/\ntheorem t : True := trivial",
        "-- #eval run_cmd native_decide\ntheorem t : True := trivial",
        "@[simp] theorem t : 1 + 1 = 2 := rfl",
        "@[simp, reducible] def f := 1",
        "@[simp ←] theorem t : 1 + 1 = 2 := rfl",
        "@[local simp] theorem t : 1 + 1 = 2 := rfl",
        "@[ext] structure P where\n  x : ℕ",
        "@[to_additive] theorem t {G} [Group G] (a : G) : a = a := rfl",
        "attribute [local instance] Classical.propDecidable",
        "attribute [-simp] Nat.add_eq",
        "attribute [local simp] Nat.add_comm in\ntheorem t : True := trivial",
        "set_option maxHeartbeats 400000 in\ntheorem t : True := trivial",
        "set_option linter.unusedVariables false\ntheorem t : True := trivial",
        "set_option pp.all true in\ntheorem t : True := trivial",
        "example : True := by\n  aesop",
        "example : True := by\n  aesop (config := { maxRuleApplications := 10 })",
        "example (f : ℕ → ℕ) (h : ∀ a, f a = 0) : f 1 = 0 := by simp [h]",
        "example : True := by\n  first | trivial | decide",
        "theorem relabel_thing (elaborate : ℕ) : elaborate = elaborate := rfl",
        "def initial := 1\ndef evaluate (x : ℕ) := x",
        "example (l : List ℕ) (h : l <+: l) : l.length = l.length := rfl",
        "noncomputable section\nopen Classical in\ndef p : Prop := True\nend",
    ],
)
def test_legitimate_lean_syntax_stays_accepted(source: str) -> None:
    assert find_source_violation(source) is None


def test_stripper_keeps_lines_and_blanks_literals() -> None:
    stripped = strip_lean_comments_and_strings(
        'a -- run_cmd\n/- #eval\n -/ b "#eval\nx" c\n'
    )

    assert "#eval" not in stripped
    assert "run_cmd" not in stripped
    assert stripped.split("\n")[0].strip() == "a"
    assert stripped.count("\n") == 4


def test_stripper_treats_primed_identifier_followed_by_comment_as_code() -> None:
    assert strip_lean_comments_and_strings("x' -- y").strip() == "x'"


def test_declared_theorem_names_covers_modifiers_and_ignores_literals() -> None:
    source = "\n".join(
        [
            "namespace N",
            "theorem a : True := trivial",
            "@[simp] protected lemma N.b : True := trivial",
            "private theorem c.{u} : True := trivial",
            "theorem _root_.d : True := trivial",
            "theorem «e f» : True := trivial",
            "-- theorem hidden : True := trivial",
            'def s := "theorem hidden2"',
            "example : True := trivial",
            "end N",
        ]
    )

    assert declared_theorem_names(source) == ("a", "N.b", "c", "d", "«e f»")


def test_examples_become_named_declarations_outside_literals_only() -> None:
    source = "\n".join(
        [
            "-- example in a comment",
            'def note := "example"',
            "example : True := trivial",
            "noncomputable example : True := trivial",
            "def «example» := 1",
            "def counterexample := 1",
            "def Foo.example := 1",
        ]
    )

    assert with_auditable_examples(source).splitlines() == [
        "-- example in a comment",
        'def note := "example"',
        "noncomputable def pals_audit_0 : True := trivial",
        "noncomputable def pals_audit_1 : True := trivial",
        "def «example» := 1",
        "def counterexample := 1",
        "def Foo.example := 1",
    ]


def test_source_without_examples_is_returned_unchanged() -> None:
    source = 'theorem t : True := trivial -- example\ndef s := "example"\n'

    assert with_auditable_examples(source) == source


def test_verifier_rejects_policy_violation_before_invoking_lean() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify(
        f"open Nat in #eval {PAYLOAD}\n{FORGED}"
    )

    assert result.success is False
    assert [item.code for item in result.diagnostics] == ["lean.disallowed_interactive_command"]


def test_sketch_verifier_applies_the_same_policy() -> None:
    result = LeanVerifier(lean_binary="missing-lean").verify_sketch(
        f"run_meta {PAYLOAD}\nexample : True := by\n  sorry"
    )

    assert result.success is False
    assert result.diagnostics[0].code == "lean.disallowed_metaprogramming"


@pytest.mark.parametrize(
    "source",
    [
        '/--/ " -/\nmacro_rules | _ => _ -- "\ntheorem t : True := trivial\n',
        '/-!/ " -/\nrun_cmd pure () -- "\n',
        "def t : Set Nat := ∅ᶜinfix:50 \" = \" => f\n",
        "def t : Set Nat := ∅ᶜset_option debug.skipKernelTC true\n",
        "def t := 1run_elab pure ()\n",
        'def x : String := s! "{(by_elab foo : Nat)}"\n',
        'def x : String := s!\n  "{foo}"\n',
        'def x : String := s! /- gap -/ "{foo}"\n',
        "def v : Nat := eval% 2^10\n",
        'def v := include_str "/etc/hosts"\n',
        "def v := 1\nsimproc_decl foo (bar) := baz\n",
    ],
)
def test_lexer_disagreements_found_in_review_are_rejected(source: str) -> None:
    assert find_source_violation(source) is not None


@pytest.mark.parametrize(
    "source",
    [
        "/-- doc -/\ntheorem t : True := trivial\n",
        "/-! module doc -/\ntheorem t : True := trivial\n",
        "theorem t (h' : x ≠ y) (x₁ : Nat) : x₁ = x₁ := rfl\n",
        "theorem t (sᶜ : Set Nat) : sᶜ = sᶜ := rfl\n",
        "theorem t : (fun x => x !) 3 = 6 := rfl\n",
        "theorem t (run_elaborate : Nat) : run_elaborate = run_elaborate := rfl\n",
    ],
)
def test_lexer_fixes_keep_legitimate_syntax(source: str) -> None:
    assert find_source_violation(source) is None


@pytest.mark.parametrize(
    "source",
    ["1" * 480_000, "aesop (" * 68_000, "@[simp] " * 60_000],
)
def test_policy_stays_fast_on_adversarial_input(source: str) -> None:
    started = time.monotonic()
    find_source_violation(source)
    assert time.monotonic() - started < 5


@pytest.mark.parametrize(
    "source",
    [
        "def w := {n : Int //- n = n}\n#eval 1\n-- -/\n",
        "def w := {n : Int ///- n = n}\n#eval 1\n-- -/\n",
        "def w := Nat \\/- x\n#eval 1\n-- -/\n",
        "def a := 1 <-- x\n",
        "run_cmd/- -/do pure ()\n",
        "theorem t : 2 = 2 := by/- -/native_decide\n",
        "set_option/- -/debug.skipKernelTC true\n",
    ],
)
def test_comment_forms_lean_reads_differently_are_rejected(source: str) -> None:
    assert find_source_violation(source) is not None


@pytest.mark.parametrize(
    "source",
    [
        "theorem t : True := trivial -- note\n",
        "theorem t : True := by trivial--note\n",
        "theorem t (a /- first -/ : Nat) : a = a := rfl\n",
        "theorem t : (/- empty -/ 1 : Nat) = 1 := rfl\n",
        "/- header -/\ntheorem t : True := trivial\n",
    ],
)
def test_ordinary_comments_stay_accepted(source: str) -> None:
    assert find_source_violation(source) is None
