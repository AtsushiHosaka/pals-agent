import json
from pathlib import Path

import pytest

from pals_agent.figure_calls import validate_figure_call

ROOT = Path(__file__).parents[2] / "testdata/catalog-figures-v1"
GENERATED = json.loads((ROOT / "recipe-figures-v1.json").read_text())


def test_generated_catalog_is_closed_and_unique():
    assert GENERATED["schema_version"] == "pals.recipe-figures.v1"
    keys = [(row["recipe_id"], row["answer_sha256"]) for row in GENERATED["figures"]]
    assert keys and len(keys) == len(set(keys))
    for row in GENERATED["figures"]:
        validate_figure_call(row["visualization"])


def test_generated_catalog_matches_its_source():
    yaml = pytest.importorskip("yaml")
    source = yaml.safe_load((ROOT / "figures.yaml").read_text())["figures"]
    assert {row["recipe_id"]: row["visualization"] for row in GENERATED["figures"]} == source
