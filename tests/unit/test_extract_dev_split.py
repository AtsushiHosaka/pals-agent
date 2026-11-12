import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "eval"))

from extract_dev_split import extract  # noqa: E402


def test_only_dev_unseen_items_survive() -> None:
    manifest = {
        "faithfulness_rule": "rule",
        "problems": [
            {"id": "a", "split": "dev_unseen", "statement": "s1"},
            {"id": "b", "split": "held_out", "statement": "s2"},
            {"id": "c", "split": "dev_unseen", "statement": "s3"},
        ],
    }
    out = extract(manifest)
    assert [p["id"] for p in out["problems"]] == ["a", "c"]
    assert "s2" not in str(out)
