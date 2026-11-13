"""Worker-side layout normalisation against the parser in the deployed verifier image.

The deployed verifier (commit 189b4437) restates a theorem by cutting its signature at the first
line-leading ``|``. These tests load that exact parser from a frozen fixture and show that the
normalised layout restates to the full statement, while the current parser reads both layouts the
same way. Nothing here imports the frozen module from runtime code.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from pals_agent import lean_layout
from pals_agent.lean_layout import normalise_signature_layout
from pals_agent.lean_source_policy import mask_lean_comments_and_strings, statement_reference

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "deployed_verifier_lean_source_policy.py"
)
_SPEC = importlib.util.spec_from_file_location("deployed_verifier_lean_source_policy", _FIXTURE)
assert _SPEC and _SPEC.loader
deployed = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = deployed
_SPEC.loader.exec_module(deployed)

HEADER = "import Mathlib\n\n"

# (name, source, must_change). `must_change` False: left byte-identical.
CORPUS: list[tuple[str, str, bool]] = [
    (
        "abs_on_own_line",
        HEADER
        + "theorem t (μ m σ : ℝ) (h : 0 < σ) :\n    |μ - m| ≤ σ := by\n  sorry\n",
        True,
    ),
    (
        "several_bars",
        HEADER
        + "theorem t (a b c : ℝ) :\n    |a - b| +\n    |b - c| +\n    |a - c| ≤ 3 := by\n  sorry\n",
        True,
    ),
    (
        "continuation_lines_start_with_bar",
        HEADER
        + "theorem t (a b : ℝ) :\n    a = b ∧\n    |a| ≤ 1 ∧\n    |b| ≤ 1 ∧\n"
        "    |a - b| ≤ 2 := by\n"
        "  sorry\n",
        True,
    ),
    (
        "helper_and_main",
        HEADER
        + "lemma helper (x : ℝ) :\n    |x| ≥ 0 := by\n  exact abs_nonneg x\n\n"
        "theorem main (μ m σ : ℝ) :\n    |μ - m| ≤ σ → |m - μ| ≤ σ := by\n  sorry\n",
        True,
    ),
    ("example", HEADER + "example (x : ℝ) :\n    |x| ≥ 0 := by\n  positivity\n", True),
    (
        "binders_span_lines",
        HEADER
        + "theorem t (μ m\n    σ : ℝ) (h :\n      0 < σ) :\n    |μ - m| ≤ σ := by\n  sorry\n",
        True,
    ),
    (
        "let_in_type",
        HEADER
        + "theorem t (x : ℝ) :\n    let y := x + 1;\n    |y - x| ≤ 1 := by\n  intro y\n  sorry\n",
        True,
    ),
    (
        "let_in_binder",
        HEADER
        + "theorem t (f : ℝ → ℝ) (h : let g := f;\n    g 0 = 0) :\n    |f 0| ≤ 1 := by\n  sorry\n",
        True,
    ),
    (
        "abs_of_application",
        HEADER
        + "theorem t (f : (ℝ → ℝ) → ℝ → ℝ) :\n    |f (fun x => x) 1| ≤ 1 := by\n  sorry\n",
        True,
    ),
    (
        "norm_and_dvd",
        HEADER
        + "theorem t (x : ℝ) (a b : ℕ) (h : a ∣ b) :\n    ‖x‖ ≤ |x| ∧\n"
        "    |x| ≤ ‖x‖ := by\n  sorry\n",
        True,
    ),
    (
        "equation_compiler_untouched",
        HEADER
        + "theorem t : ∀ n : ℕ, n + 0 = n\n  | 0 => rfl\n  | n + 1 => rfl\n",
        False,
    ),
    (
        "equation_compiler_after_abs",
        HEADER
        + "theorem t : ∀ n : ℕ, |(n : ℝ)| = n\n  | 0 => by simp\n  | n + 1 => by simp\n",
        False,
    ),
    (
        "equation_compiler_with_binders",
        HEADER
        + "theorem t (f : ℕ → ℕ) (hf : ∀ n, f n = n) : ∀ n : ℕ, f n = n\n  | 0 => hf 0\n"
        "  | n + 1 => hf (n + 1)\n",
        False,
    ),
    (
        "match_arms_in_body",
        HEADER
        + "theorem t (n : ℕ) : n = n := by\n  match n with\n  | 0 => rfl\n  | k + 1 => rfl\n",
        False,
    ),
    (
        "bar_lines_in_proof_body",
        HEADER
        + "theorem t (x : ℝ) : 0 ≤ |x| := by\n  have h : 0 ≤\n    |x| := abs_nonneg x\n  exact h\n",
        False,
    ),
    (
        "set_builder_bar_at_line_start",
        HEADER
        + "theorem t (p : ℝ → Prop) :\n    {x : ℝ\n      | p x} ⊆ Set.univ := by\n"
        "  intro x _\n  trivial\n",
        False,
    ),
    (
        "char_literal_bar",
        HEADER + "theorem t (c : Char) (h : c = '|') :\n    c = '|' := by\n  exact h\n",
        False,
    ),
    (
        "comment_line_before_bar",
        HEADER + "theorem t (x : ℝ) : -- the bound\n    |x| ≥ 0 := by\n  positivity\n",
        False,
    ),
    (
        "comment_only_line_before_bar",
        HEADER + "theorem t (x : ℝ) :\n    -- the bound\n    |x| ≥ 0 := by\n  positivity\n",
        False,
    ),
    (
        "block_comment_before_bar",
        HEADER + "theorem t (x : ℝ) :\n    /- the bound -/ |x| ≥ 0 := by\n  positivity\n",
        False,
    ),
    (
        "string_in_comment_text",
        HEADER + 'theorem t (x : ℝ) :\n    |x| ≥ 0 := by\n  -- "|\n  positivity\n',
        True,
    ),
    ("no_assignment", HEADER + "theorem t (x : ℝ) :\n    |x| ≥ 0\n", False),
    (
        "where_clause",
        HEADER
        + "theorem t (x : ℝ) :\n    |x| ≥ 0 := by\n  exact h x\nwhere\n"
        "  h (y : ℝ) : 0 ≤ |y| := abs_nonneg y\n",
        True,
    ),
    (
        "namespace_section_mutual",
        HEADER
        + "namespace Foo\nsection S\nvariable (x : ℝ)\n\n"
        "theorem t :\n    |x| ≥ 0 := by\n  positivity\n\n"
        "theorem u : ∀ n : ℕ, n = n\n  | 0 => rfl\n  | n + 1 => rfl\nend S\nend Foo\n"
        "mutual\ntheorem v (y : ℝ) :\n    |y| ≥ 0 := by\n  positivity\nend\n",
        True,
    ),
    (
        "private_attributed_theorem",
        HEADER + "@[simp] private theorem t (x : ℝ) :\n    |x| ≥ 0 := by\n  positivity\n",
        True,
    ),
    (
        "crlf",
        HEADER.replace("\n", "\r\n")
        + "theorem t (x : ℝ) :\r\n    |x| ≥ 0 := by\r\n  positivity\r\n",
        True,
    ),
]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _code_stream(source: str) -> str:
    return _squash(mask_lean_comments_and_strings(source))


@pytest.mark.parametrize(("name", "source", "must_change"), CORPUS, ids=[c[0] for c in CORPUS])
def test_deployed_parser_restates_the_full_statement(
    name: str, source: str, must_change: bool
) -> None:
    normalised = normalise_signature_layout(source)
    assert (normalised != source) is must_change
    if name == "no_assignment":
        # A declaration without ``:=`` has no signature end for the current parser: left alone.
        assert normalised == source
        return
    reference = statement_reference(source)
    assert reference is not None
    expected = _squash(reference)
    if name in {
        "comment_line_before_bar",
        "comment_only_line_before_bar",
        "block_comment_before_bar",
    }:
        # A bar behind a comment is left alone: the deployed parser is no worse off than before.
        assert normalised == source
        return
    restated = deployed.statement_reference(normalised)
    assert restated is not None
    assert _squash(restated) == expected
    assert ": :=" not in restated and not re.search(r":\s*:=\s*sorry", restated)
    # The current parser reads the normalised layout as it read the original.
    current = statement_reference(normalised)
    assert current is not None
    assert _squash(current) == expected


def test_deployed_parser_really_fails_on_the_unnormalised_conclusion() -> None:
    source = HEADER + "theorem t (μ m σ : ℝ) :\n    |μ - m| ≤ σ := by\n  sorry\n"
    broken = deployed.statement_reference(source)
    assert broken is not None
    assert re.search(r":\s*:=\s*sorry", broken)
    fixed = deployed.statement_reference(normalise_signature_layout(source))
    assert fixed is not None
    assert "|μ - m| ≤ σ" in fixed


def test_example_is_audited_with_the_full_type() -> None:
    source = HEADER + "example (x : ℝ) :\n    |x| ≥ 0 := by\n  positivity\n"
    audited = deployed.with_auditable_examples(normalise_signature_layout(source))
    restated = deployed.statement_reference(audited)
    assert restated is not None and "|x| ≥ 0" in restated


@pytest.mark.parametrize(("name", "source", "_"), CORPUS, ids=[c[0] for c in CORPUS])
def test_only_whitespace_changes(name: str, source: str, _: bool) -> None:
    normalised = normalise_signature_layout(source)
    assert _code_stream(normalised) == _code_stream(source)
    # Comments and strings are carried over unchanged and in order.
    def literals(text: str) -> list[str]:
        masked = mask_lean_comments_and_strings(text)
        return [
            _squash("".join(a for a, b in zip(text, masked, strict=True) if a != b))
        ]

    assert literals(normalised) == literals(source)


@pytest.mark.parametrize(("name", "source", "_"), CORPUS, ids=[c[0] for c in CORPUS])
def test_idempotent(name: str, source: str, _: bool) -> None:
    once = normalise_signature_layout(source)
    assert normalise_signature_layout(once) == once


def test_untouched_sources_are_byte_identical() -> None:
    for name, source, must_change in CORPUS:
        if not must_change:
            assert normalise_signature_layout(source) == source, name


def test_joined_line_is_a_single_space() -> None:
    normalised = normalise_signature_layout(
        HEADER + "theorem t (μ m σ : ℝ) :\n    |μ - m| ≤ σ := by\n  sorry\n"
    )
    assert normalised == HEADER + "theorem t (μ m σ : ℝ) : |μ - m| ≤ σ := by\n  sorry\n"


def test_proof_body_comment_with_bar_is_preserved() -> None:
    source = HEADER + 'theorem t (x : ℝ) :\n    |x| ≥ 0 := by\n  -- "|"\n  positivity\n'
    assert normalise_signature_layout(source).endswith('-- "|"\n  positivity\n')


@pytest.mark.parametrize(
    "source",
    [
        "",
        "|",
        "theorem",
        "theorem t :\n  |",
        "theorem t : (\n  |x| := by",
        "theorem t : ∀ x,\n  | := => |",
        "/- unterminated\ntheorem t :\n |x| := by",
        'theorem t : "unterminated\n |x| := by',
        "theorem t : '\n|x| := by",
        "example :\n  |",
        "theorem t {x : ℝ} : \n   | := let := \n | let let",
    ],
)
def test_malformed_input_never_raises(source: str) -> None:
    result = normalise_signature_layout(source)
    assert isinstance(result, str)
    assert normalise_signature_layout(result) == result


def test_any_internal_failure_returns_the_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(lean_layout, "_signature", boom)
    source = HEADER + "theorem t (x : ℝ) :\n    |x| ≥ 0 := by\n  positivity\n"
    assert normalise_signature_layout(source) == source


def _bar_file(count: int) -> str:
    conclusion = " ∧\n".join(f"    |x - {index}| ≤ {index + 1}" for index in range(count))
    return HEADER + f"theorem t (x : ℝ) :\n{conclusion} := by\n  sorry\n"


def test_work_is_linear_in_the_number_of_bar_lines() -> None:
    small: dict[str, int] = {}
    large: dict[str, int] = {}
    source_small, source_large = _bar_file(1500), _bar_file(3000)
    assert lean_layout._normalise(source_small, small) != source_small
    assert lean_layout._normalise(source_large, large) != source_large
    for counter, source in ((small, source_small), (large, source_large)):
        assert counter["scan"] <= len(source)
        assert counter["gap"] <= len(source)
    ratio = (large["scan"] + large["gap"]) / (small["scan"] + small["gap"])
    assert 1.8 < ratio < 2.2
    # Every bar is joined, none is left line-leading.
    result = lean_layout._normalise(source_large, None)
    assert not re.search(r"\n\s*\|", result.split(":= by")[0])


def test_comment_before_bar_is_not_pulled_into_the_comment() -> None:
    source = HEADER + "theorem t (x : ℝ) : -- note\n    |x| ≥ 0 := by\n  positivity\n"
    result = normalise_signature_layout(source)
    assert "-- note |x|" not in result
    assert result == source
