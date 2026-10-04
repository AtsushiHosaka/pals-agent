"""Recover layout whitespace only, while publishing the exact bound source substring."""

import hashlib

import pytest
import rfc8785

from pals_agent.material_context import MaterialContext, MaterialContextError

PROJECT = "33333333-3333-4333-8333-333333333333"
MATERIAL = "44444444-4444-4444-8444-444444444444"


def context(text):
    body = {
        "project_id": PROJECT,
        "sources": [{
            "material_id": MATERIAL,
            "filename": "20240301_Krystal_Geck.pdf",
            "content_sha256": "a" * 64,
            "page": 4,
            "text": text,
        }],
    }
    return MaterialContext.parse(
        dict(body, snapshot_sha256=hashlib.sha256(rfc8785.dumps(body)).hexdigest()),
        project_id=PROJECT,
    )


def citation(excerpt, **overrides):
    return dict(material_id=MATERIAL, page=4, excerpt=excerpt, **overrides)


@pytest.mark.parametrize(
    ("original", "quoted"),
    [
        ("(e, α∨\r\n)α", "(e, α∨)α"),
        ("x = 2\r\ny", "x = 2\ny"),
        ("x\t=\u30002 y", "x=2y"),
        ("α β γ", "α  β\nγ"),
    ],
)
def test_layout_whitespace_recovers_only_the_original_source_span(original, quoted):
    source = "Header\n" + original + "\nFooter"
    result = context(source).validate_citations([citation(quoted)])
    assert result == [{
        "material_id": MATERIAL,
        "filename": "20240301_Krystal_Geck.pdf",
        "content_sha256": "a" * 64,
        "page": 4,
        "excerpt": original,
    }]
    assert result[0]["excerpt"] in source


@pytest.mark.parametrize("quoted", ["x=3y", "x≠2y", "X=2y", "x=２y", "x=2"])
def test_symbol_digit_case_and_missing_text_changes_are_not_repaired(quoted):
    # Missing text may be a valid exact substring; this fixture makes x=2 absent
    # and recovery ambiguous because it occurs in two longer source equations.
    source = "x = 2 y; x = 2 z" if quoted == "x=2" else "x = 2 y"
    with pytest.raises(MaterialContextError, match="material_citation_invalid"):
        context(source).validate_citations([citation(quoted)])


def test_multiple_normalized_matches_are_rejected_even_when_layout_differs():
    with pytest.raises(MaterialContextError, match="material_citation_invalid"):
        context("x = 2 y; x\r\n=2\ty").validate_citations([citation("x=2y")])


def test_recovered_span_over_raw_excerpt_limit_is_rejected():
    with pytest.raises(MaterialContextError, match="material_citation_invalid"):
        context("x" + " " * 500 + "y").validate_citations([citation("xy")])


@pytest.mark.parametrize("page", [3, True])
def test_whitespace_recovery_cannot_move_to_an_unbound_page(page):
    value = citation("x=2y")
    value["page"] = page
    with pytest.raises(MaterialContextError, match="material_citation_invalid"):
        context("x = 2 y").validate_citations([value])


def test_whitespace_recovery_cannot_change_material_identity():
    value = citation("x=2y")
    value["material_id"] = PROJECT
    with pytest.raises(MaterialContextError, match="material_citation_invalid"):
        context("x = 2 y").validate_citations([value])


def test_exact_original_excerpt_remains_byte_identical():
    original = "(e, α∨\r\n)α"
    assert context(original).validate_citations([citation(original)])[0]["excerpt"] == original


def test_duplicate_recovered_page_is_rejected():
    with pytest.raises(MaterialContextError, match="material_citation_invalid"):
        context("x = 2 y").validate_citations([citation("x=2y"), citation("x = 2 y")])
