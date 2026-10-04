"""Constant-curl circulation is a distinct, correctly oriented Green corollary."""

from __future__ import annotations

import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pals_agent.typed_catalog_expansion import validate_expansion_batch
from pals_agent.typed_vector_calculus_v6 import (
    validate_canonical_typed_vector_calculus_v6_openmath_xml as valid,
)

ROOT = Path(__file__).resolve().parents[3]
DATA = json.loads((ROOT / "docs/vector-calculus-v6-supplement.json").read_text())
CARD = DATA["cards"][0]
NS = {"o": "http://www.openmath.org/OpenMath"}


def test_both_same_profile_manifests_load():
    for filename in ["vector-calculus-v6-batch.json", "vector-calculus-v6-supplement.json"]:
        validate_expansion_batch(
            json.loads((ROOT / "docs" / filename).read_text()), repository_root=ROOT
        )


def test_original_five_card_manifest_unchanged():
    assert (
        hashlib.sha256((ROOT / "docs/vector-calculus-v6-batch.json").read_bytes()).hexdigest()
        == "15983be11a49578fd69fc4f9d0f7e2924870de06c5be68f8a2f116e64c426513"
    )


def test_canonical_card_matches_generator():
    assert valid(CARD["openmath_xml"]) == CARD["openmath_xml"]
    assert (
        runpy.run_path(str(ROOT / "pals-scripts/generate-vector-calculus-v6-supplement.py"))[
            "cards"
        ]
        == DATA["cards"]
    )


@pytest.mark.parametrize(
    "key,path",
    [
        ("witness_sha256", "docs/vector-calculus-v6-supplement.lean"),
        ("validator_sha256", "pals-agent/pals_agent/typed_vector_calculus_v6.py"),
        (
            "registry_sha256",
            "pals-agent/pals_agent/content_dictionaries/typed-vector-calculus-v6-registry.json",
        ),
    ],
)
def test_exact_pins(key, path):
    assert (
        DATA["evidence"][key] == "sha256:" + hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    )


def test_bundle():
    expected = (
        "import Mathlib\n\n-- manifest card: "
        + CARD["id"]
        + "\n"
        + CARD["lean_target"]
        + " := "
        + CARD["lean_witness"].rstrip()
        + "\n"
    )
    assert (ROOT / DATA["evidence"]["witness_path"]).read_text() == expected
    assert 4 <= len(CARD["sketch_steps"]) <= 10


def test_curl_hypothesis_and_boundary_orientation():
    root = ET.fromstring(CARD["openmath_xml"])
    apps = root.findall(".//o:OMA", NS)
    names = [n[0].attrib.get("name") for n in apps]
    assert "curl" in names and "divergence" not in names
    assert "countable" in names and "boundary_circulation" in names
    assert names.count("continuous_on") == 2
    assert names.count("set_difference") == 2
    assert "hcurl : ∀ z ∈ Set.Icc a b, B z (1,0) - A z (0,1) = c" in CARD["lean_target"]
    assert "c*(b.1-a.1)*(b.2-a.2)" in CARD["lean_target"]


def test_explicit_advanced_binding_and_negative():
    b = json.loads((ROOT / "docs/vector-calculus-v6-supplement-bindings.json").read_text())[
        "bindings"
    ]
    assert len(b) == 1 and b[0]["draft_id"] == CARD["id"]
    assert b[0]["family_id"] == "univ.multivar.line-surface-integrals"
    assert b[0]["primary_mode"] == "compute_construct" and b[0]["difficulty"] == "advanced"
    n = json.loads((ROOT / "docs/vector-calculus-v6-supplement-negatives.json").read_text())
    assert n["cases"][0]["paired_card_ids"] == [CARD["id"]]
    assert n["status"] == "authored_candidates_not_retrieval_tested"
