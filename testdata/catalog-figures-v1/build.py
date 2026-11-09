"""Bind figures.yaml to the exact answer bytes of its cards and write recipe-figures-v1.json.

Usage: build.py CARDS_DIR. Copy the result to pals-api `app/domain/recipe_figures_v1.json`.
A figure that names a point its answer does not mention is rejected here, before review.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

from pals_agent.figure_calls import figure_labels, labels_occur_in, validate_figure_call

HERE = Path(__file__).parent
SCHEMA_VERSION = "pals.recipe-figures.v1"


def stored_answer(cards: Path, recipe_id: str) -> str:
    prefix, domain, card_id = recipe_id.split(".")
    if prefix != "textbook":
        raise ValueError(f"{recipe_id}: unknown Recipe ID")
    deck = yaml.safe_load((cards / f"{domain}.yaml").read_text())
    card = next(card for card in deck if card["id"] == card_id)
    # catalog.py seals `card["answer"].strip()` as the search entry's answer.
    return card["answer"].strip()


def build(cards: Path) -> dict:
    source = yaml.safe_load((HERE / "figures.yaml").read_text())
    rows = []
    for recipe_id, call in sorted(source["figures"].items()):
        validate_figure_call(call)
        answer = stored_answer(cards, recipe_id)
        if not labels_occur_in(call, answer):
            missing = sorted(figure_labels(call))
            raise ValueError(f"{recipe_id}: a label of {missing} is not in the stored answer")
        rows.append({
            "recipe_id": recipe_id,
            "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            "visualization": call,
        })
    return {"schema_version": SCHEMA_VERSION, "figures": rows}


if __name__ == "__main__":
    document = build(Path(sys.argv[1]))
    target = HERE / "recipe-figures-v1.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"{len(document['figures'])} figures")
