from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import rfc8785

from pals_agent.typed_draft_catalog import (
    TypedAuthoringManifestError,
    load_typed_authoring_manifest,
    validate_typed_authoring_manifest,
)

AGENT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    AGENT_ROOT / "testdata/typed-math-v1/group-ring-core-authoring-manifest.proposal.json"
)
TYPICAL_THEOREMS_MANIFEST_PATH = (
    AGENT_ROOT
    / "testdata/typed-math-v1/group-ring-typical-theorems-authoring-manifest.proposal.json"
)
_MANIFEST_DIGEST_INPUT = (
    "RFC 8785 canonical JSON serialization of this object with manifest_digest omitted"
)


def _reseal(payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    unsigned.pop("manifest_digest")
    payload["manifest_digest"] = {
        "algorithm": "sha256",
        "input": _MANIFEST_DIGEST_INPUT,
        "sha256": "sha256:" + hashlib.sha256(rfc8785.dumps(unsigned)).hexdigest(),
    }


def test_load_typed_authoring_manifest_validates_all_bound_evidence() -> None:
    payload = load_typed_authoring_manifest(MANIFEST_PATH)

    assert payload["proposal_status"] == "not_admitted_requires_independent_project_review"
    assert [card["id"] for card in payload["cards"]] == [
        "typed_group_inverse_product",
        "typed_group_left_inverse",
        "typed_comm_ring_additive_inverse",
    ]


def test_group_ring_typical_theorems_are_bound_and_do_not_overlap_core() -> None:
    core = load_typed_authoring_manifest(MANIFEST_PATH)
    typical = load_typed_authoring_manifest(TYPICAL_THEOREMS_MANIFEST_PATH)

    assert len(typical["cards"]) == 22
    assert {card["id"] for card in core["cards"]}.isdisjoint(
        card["id"] for card in typical["cards"]
    )
    assert {card["canonical_openmath_xml"] for card in core["cards"]}.isdisjoint(
        card["canonical_openmath_xml"] for card in typical["cards"]
    )


def test_typed_authoring_manifest_rejects_tampered_digest_and_canonical_xml() -> None:
    original = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    digest_tampered = copy.deepcopy(original)
    digest_tampered["cards"][0]["canonical_statement"] = "Tampered."
    with pytest.raises(TypedAuthoringManifestError, match="manifest digest"):
        validate_typed_authoring_manifest(digest_tampered, root=AGENT_ROOT)

    canonical_tampered = copy.deepcopy(original)
    canonical_tampered["cards"][0]["canonical_openmath_xml"] = "<OMOBJ/>"
    _reseal(canonical_tampered)
    with pytest.raises(TypedAuthoringManifestError, match="canonical OpenMath"):
        validate_typed_authoring_manifest(canonical_tampered, root=AGENT_ROOT)


def test_typed_authoring_manifest_rejects_artifact_path_escape() -> None:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    payload["profile"]["lean_toolchain"]["path"] = "../outside.txt"
    _reseal(payload)

    with pytest.raises(TypedAuthoringManifestError, match="escapes the package root"):
        validate_typed_authoring_manifest(payload, root=AGENT_ROOT)
