from pals_agent.patch_repair import MAX_EDITS, apply_patch, numbered_listing, parse_patch

SRC = "a\nb\nc\nd\ne\n"


def test_replace_one_and_range() -> None:
    assert apply_patch(SRC, "REPLACE 2\nB\nEND", protected=0) == "a\nB\nc\nd\ne\n"
    assert apply_patch(SRC, "REPLACE 2-3\nX\nEND", protected=0) == "a\nX\nd\ne\n"


def test_empty_body_deletes_and_fences_are_ignored() -> None:
    assert apply_patch(SRC, "```\nREPLACE 4-5\nEND\n```", protected=0) == "a\nb\nc\n"


def test_several_edits_apply_against_the_original_numbering() -> None:
    patch = "REPLACE 4\nD\nEND\nREPLACE 1\nA1\nA2\nEND"
    assert apply_patch(SRC, patch, protected=0) == "A1\nA2\nb\nc\nD\ne\n"


def test_rejects_malformed_or_unsafe_patches() -> None:
    for patch in (
        "",
        "just prose",
        "REPLACE 2\nno end",
        "REPLACE 9\nx\nEND",  # out of range
        "REPLACE 0\nx\nEND",
        "REPLACE 3-2\nx\nEND",
        "REPLACE 2-3\nx\nEND\nREPLACE 3\ny\nEND",  # overlap
        "REPLACE 1\nx\nEND\n" * (MAX_EDITS + 1),
        "REPLACE 1\n" + "x" * 7000 + "\nEND",
        "REPLACE 1\nx\nEND\nstray text",
    ):
        assert apply_patch(SRC, patch, protected=0) is None, patch


def test_parse_and_numbered_listing() -> None:
    assert parse_patch("REPLACE 1-2\nq\nEND") == [(1, 2, ["q"])]
    assert numbered_listing("a\nb").splitlines() == ["   1| a", "   2| b"]


REAL = """

import Mathlib
open Real

theorem t (x : ℝ) (h : 0 < x) :
    0 < x ^ 2 := by
  have h1 : 0 < x ^ 2 := by
    positivity
  exact h1
"""


def test_protected_region_is_the_header_through_the_proof_start() -> None:
    from pals_agent.patch_repair import protected_through

    lines = REAL.splitlines()
    assert lines[protected_through(REAL) - 1].rstrip().endswith(":= by")
    assert protected_through("import Mathlib\n") == 1  # no declaration: everything protected


def test_leading_blank_lines_keep_the_numbering_of_the_compiled_source() -> None:
    n = next(i for i, line in enumerate(REAL.splitlines(), 1) if "positivity" in line)
    patched = apply_patch(REAL, f"REPLACE {n}\n    nlinarith [sq_nonneg x]\nEND")
    assert patched is not None and "nlinarith [sq_nonneg x]" in patched
    assert patched.splitlines()[n - 1].strip() == "nlinarith [sq_nonneg x]"
    # the stripped source numbers the same line differently: callers must pass the exact string
    # Lean compiled (two leading blank lines shift every line number by two)
    assert "positivity" in REAL.strip().splitlines()[n - 3]


def test_edits_on_the_statement_imports_or_header_are_rejected() -> None:
    lines = REAL.splitlines()
    theorem_line = next(i for i, line in enumerate(lines, 1) if line.startswith("theorem"))
    import_line = next(i for i, line in enumerate(lines, 1) if line.startswith("import"))
    assert apply_patch(REAL, f"REPLACE {theorem_line}\ntheorem t : True := by\nEND") is None
    assert apply_patch(REAL, f"REPLACE {import_line}\nimport Foo\nEND") is None
    assert apply_patch(REAL, f"REPLACE {theorem_line + 1}\n    0 < x ^ 3 := by\nEND") is None


def test_patch_bodies_may_not_add_axioms_options_or_declarations() -> None:
    n = next(i for i, line in enumerate(REAL.splitlines(), 1) if "positivity" in line)
    for body in (
        "axiom bad : False",
        "set_option maxHeartbeats 0 in",
        "native_decide",
        "sorry",
        "import Foo",
        "theorem other : True := trivial",
        "#eval 1",
        "unsafe def f := 1",
    ):
        assert apply_patch(REAL, f"REPLACE {n}\n    {body}\nEND") is None, body
    assert apply_patch(REAL, f"REPLACE {n}\n    positivity -- set_option is only a comment\nEND")
