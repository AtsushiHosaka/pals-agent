"""Contract checks for authored seeds; actual Lean compilation is a separate run."""

import json
import re
from pathlib import Path

from pals_agent.breadth_evaluation import load_corpus

ROOT = Path(__file__).resolve().parents[2] / "testdata/requested-math-seeds-v1"


def test_twenty_distinct_questions_have_exact_single_theorem_witnesses():
    corpus = load_corpus(ROOT / "corpus.json")
    assert len(corpus.cases) == 20
    assert len({case.theorem_name for case in corpus.cases}) == 20
    for case in corpus.cases:
        assert case.source is not None
        assert len(re.findall(r"^theorem\s+", case.source, re.M)) == 1
        assert not re.search(r"\b(?:sorry|admit|axiom|unsafe)\b", case.source)
        assert "#" not in case.source
        assert case.source_path.startswith("proofs/")


def test_full_answers_hypotheses_and_publication_boundary_are_preserved():
    payload = json.loads((ROOT / "corpus.json").read_text())
    assert {row["family_id"] for row in payload["cases"]} == {
        "real-analysis",
        "calculus",
        "linear-algebra",
        "number-theory",
    }
    for row in payload["cases"]:
        assert row["question"] == row["statement"]
        assert len(row["answer"]) > 100
        assert row["assumptions"] and row["proof_outline"]
        assert not any(
            row["lifecycle"][key]
            for key in (
                "independently_reviewed",
                "admitted",
                "retrievable",
                "runtime_verified",
                "deployed",
            )
        )
    by_name = {row["id"]: row for row in payload["cases"]}
    assert (
        "Values for x<0 are arbitrary"
        in by_name["requested.right_limit_and_discontinuity"]["question"]
    )
    assert "π/180" in by_name["requested.tan_one_degree_irrational"]["question"]
    assert "floating-point" in by_name["requested.pi_gt_305"]["answer"]
