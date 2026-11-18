"""Mechanical instantiation of a stored universal Recipe; pure, no model, no Lean needed."""

import json
from pathlib import Path

import pytest

from pals_agent.recipe_instantiation import (
    GENERAL_NAME,
    INSTANCE_NAME,
    InstantiationRejected,
    instantiate,
    render_answer,
    universal_parameters,
)

VECTORS = json.loads(
    (Path(__file__).parents[1] / "fixtures/recipe_instantiation_vectors.json").read_text()
)
POWER = VECTORS["natural_power_continuous"]["source"]


@pytest.mark.parametrize("value", ["2", "3"])
def test_example_form_recipe_becomes_named_general_theorem_plus_one_application(value):
    expected = VECTORS["natural_power_continuous"]["instances"][value]
    instance = instantiate(POWER, [{"variable": "n", "value": value}])
    renamed = POWER.replace("example :", f"theorem {GENERAL_NAME} :").rstrip("\n")
    assert instance.source == renamed + expected["tail"]
    assert instance.proposition == expected["proposition"]
    assert instance.bindings == (("n", value),)
    assert INSTANCE_NAME in instance.source
    assert instance.source_sha256 != instance.proposition_sha256


@pytest.mark.parametrize("name", ["named_signature_binders",
                                  "partial_prefix_leaves_remaining_forall"])
def test_signature_binders_and_partial_prefix(name):
    vector = VECTORS[name]
    instance = instantiate(vector["source"], vector["bindings"])
    assert instance.proposition == vector["proposition"]
    assert instance.source == vector["source"].rstrip("\n") + vector["tail"]


def test_parameters_are_the_numeric_prefix_only():
    assert [(p.name, p.kind) for p in universal_parameters(POWER)] == [("n", "Nat")]
    mixed = "theorem t : ∀ (n : ℕ) (f : ℝ → ℝ), f 0 = f 0 := fun n f => rfl\n"
    assert [p.name for p in universal_parameters(mixed)] == ["n"]
    assert universal_parameters("theorem t : ∃ n : ℕ, n = n := ⟨0, rfl⟩\n") == ()
    assert universal_parameters("def f := 1\n") == ()


@pytest.mark.parametrize("source", [
    # existential witness is not a universal parameter
    "theorem t : ∃ n : ℕ, n = n := ⟨0, rfl⟩\n",
    # hypothesis / extra assumption binder
    "theorem t (n : ℕ) (h : 0 < n) : 0 < n + 1 := Nat.succ_pos n\n",
    # implicit binder cannot be applied explicitly
    "theorem t {n : ℕ} : n = n := rfl\n",
    # untyped binder
    "theorem t : ∀ n, n = n := fun _ => rfl\n",
    # two declarations
    "theorem a : True := trivial\ntheorem b (n : Nat) : n = n := rfl\n",
    # namespaces rename the general theorem
    "namespace Foo\ntheorem t (n : Nat) : n = n := rfl\nend Foo\n",
    "variable (n : Nat)\ntheorem t : n = n := rfl\n",
    # reserved names
    f"theorem {GENERAL_NAME} (n : Nat) : n = n := rfl\n",
])
def test_unsupported_recipe_shapes_reject(source):
    with pytest.raises(InstantiationRejected):
        instantiate(source, [{"variable": "n", "value": "2"}])


@pytest.mark.parametrize("bindings", [
    [],  # nothing to apply
    [{"variable": "m", "value": "2"}],  # not the leading parameter
    [{"variable": "n", "value": "-1"}],  # negative natural
    [{"variable": "n", "value": "1/2"}],  # rational power is not a natural literal
    [{"variable": "n", "value": "0.5"}],
    [{"variable": "n", "value": "x"}],  # no variable or compound terms
    [{"variable": "n", "value": "2 + 1"}],
    [{"variable": "n", "value": "02"}],
    [{"variable": "n", "value": 2}],
    [{"variable": "n", "value": "2"}, {"variable": "n", "value": "3"}],  # too many
    [{"variable": "n", "value": "2", "extra": 1}],
    [{"variable": "n"}],
    "n=2",
])
def test_ill_typed_or_non_literal_arguments_reject(bindings):
    with pytest.raises(InstantiationRejected):
        instantiate(POWER, bindings)


def test_real_binder_accepts_signed_integer_but_never_a_nat_negative():
    source = "theorem t (c : ℝ) : c + 0 = c := add_zero c\n"
    assert "t (-3)" in instantiate(source, [("c", "-3")]).source
    assert instantiate(source, [("c", "-3")]).proposition == "(-3) + 0 = (-3)"
    with pytest.raises(InstantiationRejected):
        instantiate("theorem t (c : Nat) : c + 0 = c := rfl\n", [("c", "-3")])


@pytest.mark.parametrize("statement", [
    "∀ n : ℕ, n = n",  # n rebound by a quantifier inside the body
    "(fun n : ℕ => n) 0 = 0",  # n rebound by a lambda
    "∃ n : ℕ, n = 0",
    "∑ n in Finset.range 3, n = 3",
    "n.succ = n + 1",  # field notation cannot take a literal
    "f (n := 0) = 0",  # named argument
    "{n | n = 1} = {1}",
])
def test_substituted_name_must_not_be_rebound_or_projected(statement):
    source = f"theorem t (n : Nat) : {statement} := by sorry\n"
    with pytest.raises(InstantiationRejected):
        instantiate(source, [("n", "2")])


def test_remaining_binder_depending_on_substituted_variable_rejects():
    source = "theorem t (n : Nat) (v : Fin n) : v = v := rfl\n"
    with pytest.raises(InstantiationRejected):
        instantiate(source, [("n", "2")])


def test_comment_or_string_inside_statement_is_not_guessed():
    source = "theorem t (n : Nat) : n = n /- why -/ := rfl\n"
    with pytest.raises(InstantiationRejected):
        instantiate(source, [("n", "2")])


def test_commented_out_declarations_and_names_are_ignored():
    source = "-- theorem other (m : Nat) : m = m\ntheorem t (n : Nat) : n = n := rfl\n"
    assert instantiate(source, [("n", "4")]).proposition == "4 = 4"


def test_instantiation_is_a_pure_function_of_bytes():
    left = instantiate(POWER, [("n", "2")])
    assert left == instantiate(POWER, [{"variable": "n", "value": "2"}])
    assert instantiate(POWER, [("n", "3")]).source_sha256 != left.source_sha256


@pytest.mark.parametrize(("language", "intro"), [
    ("ja", "この主張は"), ("en", "special case"), ("zh-Hans", "特例"), ("zh-Hant", "特例"),
])
def test_wrapper_reuses_stored_answer_verbatim_in_every_language(language, intro):
    stored = "$n=0$では連続。帰納法により任意の$n$で連続。"
    text = render_answer(language, "任意の自然数$n$で$x^n$は連続", (("n", "2"),), stored)
    assert stored in text and "$n=2$" in text and intro in text
    assert text.startswith(text.split("\n\n", 1)[0]) and text.count(stored) == 1
    assert text == render_answer(language, "任意の自然数$n$で$x^n$は連続", [("n", "2")], stored)


@pytest.mark.parametrize("bad", [("n_1", "2"), ("n", "2.5"), ("n", "x"), ("nn", "2")])
def test_wrapper_refuses_to_display_unsafe_substitutions(bad):
    with pytest.raises(InstantiationRejected):
        render_answer("ja", "S", [bad], "A")
    with pytest.raises(InstantiationRejected):
        render_answer("fr", "S", [("n", "2")], "A")


@pytest.mark.parametrize(("source", "bindings", "code"), [
    ("theorem t (n : Nat) (h : 0 < n) : 0 < n + 1 := Nat.succ_pos n\n",
     [("n", "2")], "inst_premise_unprovable"),
    ("theorem t (n : Nat) : n = n := rfl\n", [("n", "-1")], "inst_type_mismatch"),
    ("theorem t (n : Nat) : (fun n : Nat => n) 0 = 0 := rfl\n", [("n", "2")], "inst_capture"),
    ("theorem t : ∃ n : Nat, n = n := ⟨0, rfl⟩\n", [("n", "2")], "inst_limit_exceeded"),
    ("namespace A\ntheorem t (n : Nat) : n = n := rfl\nend A\n", [("n", "2")],
     "inst_unsupported_shape"),
])
def test_rejections_carry_a_typed_inst_classification(source, bindings, code):
    with pytest.raises(InstantiationRejected) as caught:
        instantiate(source, bindings)
    assert caught.value.code == code


def test_shared_module_is_byte_identical_across_repositories():
    """pals-agent and pals-api carry the same grammar; changing one without the other fails here.

    Update `module_sha256` in the shared vectors in BOTH repositories together with the module.
    """
    import hashlib

    source = (Path(__file__).parents[2] / "pals_agent/recipe_instantiation.py").read_bytes()
    assert hashlib.sha256(source).hexdigest() == VECTORS["module_sha256"]


HYPOTHESIS_RECIPE = (
    "import Mathlib\n\ntheorem pow_le_pow_general (a b : ℝ) (ha : 0 ≤ a) (hab : a ≤ b) (n : ℕ) :\n"
    "    a ^ n ≤ b ^ n := pow_le_pow_left₀ ha hab n\n"
)


def test_elaborated_wrapper_closes_hypotheses_with_a_fixed_closer_list():
    from pals_agent.recipe_instantiation import check_alignment, elaborate

    proposition = "∀ n : ℕ, (3 : ℝ) ^ n ≤ 5 ^ n"
    instance = elaborate(HYPOTHESIS_RECIPE, proposition)
    assert "exact pow_le_pow_general _ _ _ _ _" in instance.source
    lines = instance.source.rstrip().splitlines()
    apply_at = next(i for i, line in enumerate(lines) if "intros; apply" in line)
    assert lines[apply_at] == (
        "  | (intros; apply pow_le_pow_general <;> first | assumption | fun_prop | positivity"
        " | (norm_num; done) | linarith | (simp; done))"
    )
    # before every `(by ..)` alternative: a `by` inside a term logs instead of throwing, so
    # `first` could not fall back to the apply alternative from behind it
    assert all("(by " not in line for line in lines[:apply_at])
    assert any("(by norm_num)" in line for line in lines[apply_at + 1 :])
    assert instance.bindings == () and check_alignment(HYPOTHESIS_RECIPE, instance)
    # the closers never leave the declared statement: it is the request, nothing else
    assert f"theorem pals_recipe_instance : {proposition} := by" in instance.source


def test_without_mathlib_no_side_goal_closers_are_emitted():
    from pals_agent.recipe_instantiation import elaborate

    plain = "theorem t (n : Nat) (h : 0 < n) : 0 < n := h\n"
    assert "intros; apply" not in elaborate(plain, "∀ n : Nat, 0 < n → 0 < n").source
