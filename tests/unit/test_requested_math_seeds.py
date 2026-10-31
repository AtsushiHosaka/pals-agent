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
        assert len(row["answer"].encode("utf-8")) > 120
        assert re.search(r"[ぁ-んァ-ヶ一-龠]", row["question"])
        assert re.search(r"[ぁ-んァ-ヶ一-龠]", row["answer"])
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
    assert "負の" in by_name["requested.right_limit_and_discontinuity"]["question"]
    assert r"\pi/180" in by_name["requested.tan_one_degree_irrational"]["question"]
    assert "浮動小数点" in by_name["requested.pi_gt_305"]["answer"]
    assert "有理数か" in by_name["requested.tan_one_degree_irrational"]["question"]
    assert by_name["requested.tan_one_degree_irrational"]["answer"].startswith("無理数")
    assert r"2\\3" in by_name["requested.determinant_nonzero_decision"]["question"]
    for row in payload["cases"]:
        for field in ("question", "answer"):
            assert not re.search(r"\\\\[A-Za-z]", row[field])


def _publication_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("requested_publication", ROOT / "publication.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_closed_authoring_candidates_preserve_author_and_exact_single_target():
    import rfc8785

    from pals_agent.lean_target import extract_single_target_declaration

    module = _publication_module()
    paths = sorted((ROOT / "publication").glob("*.json"))
    assert len(paths) == 20
    for path in paths:
        manifest = module.read_object(path)
        assert path.read_bytes() == rfc8785.dumps(manifest)
        assert manifest["source_author_principal"] == (
            "pals.principal.v1/codex/requested-math-seeds-20261031"
        )
        assert (
            manifest["author_profile"]["source_author_principal"]
            == manifest["source_author_principal"]
        )
        assert manifest["toolchain"]["toolchain_id"] == "lean-4.32.0-rc1-mathlib-8b62164d-aws-v1"
        source = module.materialize(manifest).decode()
        declaration = extract_single_target_declaration(source)
        assert declaration is not None
        assert declaration.kind == "example"
        assert declaration.proposition == manifest["target_source"]
        assert not re.search(r"\b(?:sorry|sorryAx|admit|axiom|unsafe)\b", source)


def test_search_candidate_requires_receipt_binding_and_keeps_japanese_answer():
    """Pure constructed values test binding, never real compiler/admission evidence."""
    import pytest
    import rfc8785

    module = _publication_module()
    case = json.loads((ROOT / "corpus.json").read_bytes())["cases"][0]
    manifest = module.read_object(ROOT / "publication" / (case["id"] + ".json"))
    receipt = {
        "schema_version": "pals.recipe-admission-compiler-receipt.v1",
        "materialized_source_sha256": module.sha(module.materialize(manifest)),
        "toolchain_fingerprint_sha256": module.sha(
            rfc8785.dumps(manifest["toolchain"]["fingerprint"])
        ),
        "compiler_command_sha256": "0" * 64,
        "compiler_result": {
            "schema_version": "pals.recipe-admission-compiler-result.v1",
            "verification_succeeded": True,
            "diagnostic_codes": [],
        },
    }
    entry = module.search_candidate(case, manifest, receipt)
    assert entry["output_language"] == "ja"
    assert entry["answer"] == case["answer"]
    assert entry["compiler_receipt_sha256"] == module.sha(rfc8785.dumps(receipt))
    assert "review" not in entry and "review_signature" not in entry
    for field in ("materialized_source_sha256", "toolchain_fingerprint_sha256"):
        wrong = {**receipt, field: "f" * 64}
        with pytest.raises(ValueError, match="identity mismatch"):
            module.search_candidate(case, manifest, wrong)
    wrong = {
        **receipt,
        "compiler_result": {**receipt["compiler_result"], "verification_succeeded": False},
    }
    with pytest.raises(ValueError, match="successful closed"):
        module.search_candidate(case, manifest, wrong)
    with pytest.raises(ValueError, match="identity mismatch"):
        module.search_candidate(case, manifest, {**receipt, "extra": True})


def test_publication_output_refuses_existing_file_and_symlink(tmp_path):
    import pytest

    module = _publication_module()
    target = tmp_path / "entry.json"
    module.write_new(target, b"original")
    with pytest.raises(FileExistsError):
        module.write_new(target, b"replacement")
    assert target.read_bytes() == b"original"
    link = tmp_path / "symlink"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        module.write_new(link, b"replacement")
    assert target.read_bytes() == b"original"
