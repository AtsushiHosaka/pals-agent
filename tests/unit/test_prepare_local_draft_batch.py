from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPOSITORY_ROOT / "pals-scripts" / "prepare-local-draft-batch.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_local_draft_batch", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cards_from_payload() -> Callable[..., list[dict[str, Any]]]:
    script = _load_script()
    return cast(Callable[..., list[dict[str, Any]]], script.__dict__["cards_from_payload"])


@pytest.mark.parametrize(
    "schema_version",
    (
        "pals.typed-math-v1-authoring-manifest.v1",
        "pals.typed-math-matrix-v1-authoring-manifest.proposal.v1",
        "pals.typed-real-analysis-v1-authoring-manifest-proposal.v1",
        "pals.typed-finite-graph-v1-authoring-manifest.proposal.v1",
        "pals.typed-future-v9-authoring-manifest.experimental.v1",
    ),
)
def test_generic_loader_rejects_every_typed_authoring_manifest_before_card_selection(
    schema_version: str,
) -> None:
    payload = {"schema_version": schema_version, "cards": []}

    with pytest.raises(ValueError, match="typed authoring manifests are forbidden"):
        _cards_from_payload()(payload, cards_key="does-not-exist")


def test_generic_loader_keeps_non_typed_manifest_card_selection() -> None:
    payload = {
        "schema_version": "pals.generic-draft-candidates.v1",
        "cards": [
            {
                "id": "generic-card",
                "canonical_statement": "A generic statement.",
                "openmath_xml": "<OMOBJ/>",
                "proof_strategy": "Use the definition.",
                "sketch_steps": ["Write the definition."],
            }
        ],
    }

    cards = _cards_from_payload()(payload, cards_key="cards")

    assert cards == payload["cards"]
