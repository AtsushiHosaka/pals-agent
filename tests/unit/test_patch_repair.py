from pals_agent.patch_repair import MAX_EDITS, apply_patch, numbered_listing, parse_patch

SRC = "a\nb\nc\nd\ne\n"


def test_replace_one_and_range() -> None:
    assert apply_patch(SRC, "REPLACE 2\nB\nEND") == "a\nB\nc\nd\ne\n"
    assert apply_patch(SRC, "REPLACE 2-3\nX\nEND") == "a\nX\nd\ne\n"


def test_empty_body_deletes_and_fences_are_ignored() -> None:
    assert apply_patch(SRC, "```\nREPLACE 4-5\nEND\n```") == "a\nb\nc\n"


def test_several_edits_apply_against_the_original_numbering() -> None:
    patch = "REPLACE 4\nD\nEND\nREPLACE 1\nA1\nA2\nEND"
    assert apply_patch(SRC, patch) == "A1\nA2\nb\nc\nD\ne\n"


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
        assert apply_patch(SRC, patch) is None, patch


def test_parse_and_numbered_listing() -> None:
    assert parse_patch("REPLACE 1-2\nq\nEND") == [(1, 2, ["q"])]
    assert numbered_listing("a\nb").splitlines() == ["   1| a", "   2| b"]
