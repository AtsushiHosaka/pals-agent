"""Contract tests for the textbook catalog tool; no Lean compile or network access."""

from __future__ import annotations

import argparse
import json

import catalog
import pytest
import yaml

from pals_agent import openmath as om

VOCABULARY = {"dvd": {"args": ["term", "term"], "returns": "prop", "meaning": "a divides b"}}


def _card(openmath: str) -> dict:
    return {"openmath": openmath}


def test_builtin_symbols_stay_in_the_deployed_profile() -> None:
    card = _card("(forall (a b) (-> (and (in a N) (in b N) (> a 0)) (<= (gcd a b) a)))")
    xml, tier = catalog.openmath_for(card, VOCABULARY)
    assert tier == "generic_now"
    assert om.validate_canonical_retrieval_openmath_xml(xml) == xml


def test_vocabulary_symbols_are_rejected_by_the_unmodified_runtime() -> None:
    xml, tier = catalog.openmath_for(_card("(forall (a b) (dvd a b))"), VOCABULARY)
    assert tier == "needs_vocabulary"
    with pytest.raises(om.MathXMLValidationError):
        om.validate_canonical_retrieval_openmath_xml(xml)


def test_extended_profile_restores_the_runtime_tables() -> None:
    before = dict(om._SUPPORTED_SYMBOLS)
    with catalog.extended_profile(VOCABULARY):
        assert len(om._SUPPORTED_SYMBOLS) == len(before) + 1
    assert before == om._SUPPORTED_SYMBOLS


def test_unbound_variable_is_rejected() -> None:
    with pytest.raises(catalog.CardError, match="neither bound"):
        catalog.openmath_for(_card("(= x 0)"), VOCABULARY)


def test_apply_text_refuses_lean_fields(tmp_path, monkeypatch) -> None:
    cards = tmp_path / "cards"
    cards.mkdir()
    original = [{"id": "a", "statement": "旧", "target": "True", "proof": "by trivial"}]
    (cards / "d.yaml").write_text(yaml.safe_dump(original, allow_unicode=True))
    monkeypatch.setattr(catalog, "CARDS", cards)
    patch = tmp_path / "patch.yaml"
    patch.write_text(yaml.safe_dump({"a": {"target": "False"}}))
    with pytest.raises(SystemExit, match="only"):
        catalog.command_apply_text(argparse.Namespace(domain="d", patch=str(patch)))
    patch.write_text(yaml.safe_dump({"a": {"statement": "新"}}, allow_unicode=True))
    catalog.command_apply_text(argparse.Namespace(domain="d", patch=str(patch)))
    updated = yaml.safe_load((cards / "d.yaml").read_text())[0]
    assert (updated["statement"], updated["target"]) == ("新", "True")


def test_stored_answer_splits_paragraphs_at_sentence_ends() -> None:
    answer = "第一段落である。\n第二段落で\n$x=1$\nである。\n\n第三段落である。\n"
    assert catalog.stored_answer({"answer": answer}) == (
        "第一段落である。\n\n第二段落で\n$x=1$\nである。\n\n第三段落である。"
    )


def test_committed_drafts_match_their_tier() -> None:
    drafts = json.loads((catalog.GENERATED / "drafts.json").read_text())["drafts"]
    for draft in drafts:
        if draft["tier"] == "generic_now":
            xml = draft["openmath_xml"]
            assert om.validate_canonical_retrieval_openmath_xml(xml) == xml
        elif draft["tier"] == "needs_vocabulary":
            with pytest.raises(om.MathXMLValidationError):
                om.validate_canonical_retrieval_openmath_xml(draft["openmath_xml"])
