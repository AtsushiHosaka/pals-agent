import hashlib
import importlib.util
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


def _build_module():
    spec = importlib.util.spec_from_file_location("catalog_figures_build", ROOT / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stored_answer_splits_paragraphs_at_sentence_ends(tmp_path):
    pytest.importorskip("yaml")
    answer = "第一段落である。\n第二段落で\n$x=1$\nである。\n\n第三段落である。\n"
    (tmp_path / "deck.yaml").write_text(
        json.dumps([{"id": "card", "answer": answer}], ensure_ascii=False), encoding="utf-8"
    )
    assert _build_module().stored_answer(tmp_path, "textbook.deck.card") == (
        "第一段落である。\n\n第二段落で\n$x=1$\nである。\n\n第三段落である。"
    )


def test_digests_match_the_generated_search_candidates():
    # A catalog answer with another digest silently loses its figure, so compare the real bytes.
    path = ROOT.parent / "textbook-catalog-v1/generated/search-candidates.json"
    if not path.exists():
        pytest.skip("the textbook catalog is on another branch")
    stored = {row["recipe_id"]: row["answer"] for row in json.loads(path.read_text())["candidates"]}
    for row in GENERATED["figures"]:
        if row["recipe_id"] in stored:
            digest = hashlib.sha256(stored[row["recipe_id"]].encode("utf-8")).hexdigest()
            assert digest == row["answer_sha256"], row["recipe_id"]
