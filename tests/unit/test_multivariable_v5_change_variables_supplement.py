"""Evidence and semantic placement for the same-profile coordinate-change supplement."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from pals_agent.typed_local_catalog import load_typed_local_catalog_manifest
from pals_agent.typed_multivariable_v5 import validate_canonical_typed_multivariable_v5_openmath_xml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/multivariable-v5-change-variables-supplement.json"


def payload():
    return json.loads(MANIFEST.read_text())


@pytest.mark.parametrize("index", [0, 1])
def test_canonical_cards_and_full_sketch(index):
    card = payload()["cards"][index]
    assert (
        validate_canonical_typed_multivariable_v5_openmath_xml(card["openmath_xml"])
        == card["openmath_xml"]
    )
    assert 4 <= len(card["sketch_steps"]) <= 10
    assert all(s not in card["lean_witness"] for s in ["sorry", "admit", "axiom"])


def test_exact_bundle_and_all_pins():
    data = payload()
    evidence = data["evidence"]
    source = (
        "import Mathlib\n\n"
        + "\n\n".join(
            "-- manifest card: "
            + c["id"]
            + "\n"
            + c["lean_target"]
            + " := "
            + c["lean_witness"].rstrip()
            for c in data["cards"]
        )
        + "\n"
    )
    assert (ROOT / evidence["witness_path"]).read_text() == source
    for key, path in [
        ("witness", evidence["witness_path"]),
        ("validator", "pals-agent/pals_agent/typed_multivariable_v5.py"),
        (
            "registry",
            "pals-agent/pals_agent/content_dictionaries/typed-multivariable-v5-registry.json",
        ),
    ]:
        assert (
            evidence[key + "_sha256"]
            == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        )
    old = json.loads((ROOT / "docs/multivariable-v5-batch.json").read_text())
    for key in ["validator_sha256", "registry_sha256", "toolchain", "mathlib_revision"]:
        assert evidence[key] == old["evidence"][key]
    assert {c["id"] for c in data["cards"]}.isdisjoint(c["id"] for c in old["cards"])
    assert {c["openmath_xml"] for c in data["cards"]}.isdisjoint(
        c["openmath_xml"] for c in old["cards"]
    )


def test_local_loader_accepts_multiple_manifests_same_profile():
    original = load_typed_local_catalog_manifest(
        ROOT / "docs/multivariable-v5-batch.json", repository_root=ROOT
    )
    supplement = load_typed_local_catalog_manifest(MANIFEST, repository_root=ROOT)
    assert original.profile == supplement.profile
    assert len(supplement.cards) == 2


def test_negative_pairing_and_reproducible_generator():
    data = payload()
    negatives = json.loads(
        (ROOT / "docs/multivariable-v5-change-variables-supplement-negatives.json").read_text()
    )
    assert {c["id"] for c in data["cards"]} == {c["positive_card_id"] for c in negatives["cases"]}
    assert negatives["status"] == "authored_counterexamples_not_retrieval_evaluated"
    assert (
        runpy.run_path(
            str(ROOT / "pals-scripts/generate-multivariable-v5-change-variables-supplement.py")
        )["cards"]
        == data["cards"]
    )


def test_change_of_variables_dependencies_remain_explicit():
    cards = payload()["cards"]
    counterexample = cards[0]
    assert "x ≠ y" in counterexample["lean_target"]
    assert "¬ Set.InjOn f s" in counterexample["lean_target"]
    synthesis = cards[1]
    assert "E (f x)" in synthesis["lean_target"]
    assert "Set.InjOn g (f '' s)" in synthesis["lean_target"]
    assert "MeasureTheory.IntegrableOn F" in synthesis["lean_target"]
    assert synthesis["openmath_xml"].count('name="jacobian_weighted"') == 4
