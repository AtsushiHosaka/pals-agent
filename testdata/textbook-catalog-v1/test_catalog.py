"""Contract tests for the textbook catalog tool; no Lean compile or network access."""

from __future__ import annotations

import argparse
import json
import re

import catalog
import pytest
import yaml

from pals_agent import openmath as om

VOCABULARY = {
    "unsealed_dvd": {"args": ["term", "term"], "returns": "prop", "meaning": "a divides b"}
}


def _card(openmath: str) -> dict:
    return {"openmath": openmath}


def test_builtin_symbols_stay_in_the_deployed_profile() -> None:
    card = _card("(forall (a b) (-> (and (in a N) (in b N) (> a 0)) (<= (gcd a b) a)))")
    xml, tier = catalog.openmath_for(card, VOCABULARY)
    assert tier == "generic_now"
    assert om.validate_canonical_retrieval_openmath_xml(xml) == xml


def test_vocabulary_outside_the_sealed_registry_is_rejected_by_the_runtime() -> None:
    xml, tier = catalog.openmath_for(_card("(forall (a b) (unsealed_dvd a b))"), VOCABULARY)
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


def test_aliases_share_a_signature_and_never_reach_the_generated_vocabulary() -> None:
    vocabulary = catalog.load_vocabulary()
    generated = json.loads((catalog.GENERATED / "vocabulary.json").read_text())["symbols"]
    for source, target in catalog.ALIASES.items():
        assert (vocabulary[source]["args"], vocabulary[source]["returns"]) == (
            vocabulary[target]["args"],
            vocabulary[target]["returns"],
        )
        assert source not in generated
    assert {"module_over", "vector_space", "morphism_comp"}.isdisjoint(catalog.ALIASES)


def test_generated_vocabulary_is_inside_the_sealed_registry() -> None:
    generated = json.loads((catalog.GENERATED / "vocabulary.json").read_text())["symbols"]
    for name in generated:
        assert (om.PALS_OPENMATH_CDBASE, "pals2", name) in om._SUPPORTED_SYMBOLS, (
            f"{name} is unsealed: run pals-scripts/reseal-openmath-v4.py"
        )


def test_draft_ids_fit_the_api_contract_and_stay_unique() -> None:
    assert catalog.draft_id_for("gap.short") == "gap_short"
    long_id = catalog.draft_id_for("textbook." + "x" * 70)
    assert len(long_id) == 64 and long_id != catalog.draft_id_for("textbook." + "x" * 71)
    drafts = json.loads((catalog.GENERATED / "drafts.json").read_text())["drafts"]
    ids = [draft["id"] for draft in drafts]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) for value in ids)


def test_committed_drafts_match_their_tier() -> None:
    drafts = json.loads((catalog.GENERATED / "drafts.json").read_text())["drafts"]
    for draft in drafts:
        if draft["tier"] == "generic_now":
            xml = draft["openmath_xml"]
            assert om.validate_canonical_retrieval_openmath_xml(xml) == xml
        elif draft["tier"] == "needs_vocabulary":
            with pytest.raises(om.MathXMLValidationError):
                om.validate_canonical_retrieval_openmath_xml(draft["openmath_xml"])
