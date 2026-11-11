"""Offline contract checks for the dedicated x^2 continuity Recipe source.

Everything here is local: no database, provider, signing key or production verifier. Pins that
need a real admitted compiler receipt use obviously synthetic values and never stand for
publication evidence. Real Lean compilation is the separate opt-in test at the end.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import pytest
import rfc8785

from pals_agent.explanations import (
    _reject_lean_source_terms,
)
from pals_agent.http_transport import HttpResponse
from pals_agent.lean_source_policy import find_source_violation
from pals_agent.lean_target import extract_single_target_declaration
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.recipe_exact_input import PINS as NATURAL_POWER_PINS
from pals_agent.recipe_exact_input import candidate_matches, eligible
from pals_agent.recipe_local_retrieval import rank
from pals_agent.recipe_semantic import SemanticReuseError, attempt
from pals_agent.recipe_semantic_contract import (
    CONTENT_SCHEMA,
    SCHEMA_VERSION,
    digest,
    parse,
    prompts,
    read_batch,
)
from tests.unit.test_recipe_exact_input import request

ROOT = Path(__file__).resolve().parents[2] / "testdata/square-continuity-recipe-v1"
SEEDS = Path(__file__).resolve().parents[2] / "testdata/requested-math-seeds-v1"
RECIPE_ID = "continuity.square.explicit-epsilon-delta"
CLAIM_ID = "00000000-0000-4000-8000-000000000002"

# Drift pins: the same constants are asserted by the API repository's contract tests.
CARD_SHA256 = "8a3378edfe82d1add7e4dc39c14bb9e4f7ece06f8d966be9d631abd84080682c"
MANIFEST_SHA256 = "2b1db0f70b206c03a3eca2118c51ac682d856914ec56d5e8d971e0392cdec613"
MATERIALIZED_SHA256 = "e2da4f1afaa5a1b627197b216e4e2f5cc40638fcf2e4f38f64033670b4becba1"
ANSWER_SHA256 = "57cd701b970841728a828a9456beae94e53cf4a5b20d83cbc7e3ed257e573bde"
SEED_DRAFT_XML_SHA256 = "e5cc2280d3c7f7120c50593d7d0be859b26e08b253f55221787eee1048e60efd"
SYNTHETIC_ENTRY_SHA256 = "152a3019f71c5d4afa883d76bce1e3bff578200c19448c3d9a621b87841571a2"


def publication_module():
    spec = importlib.util.spec_from_file_location(
        "square_continuity_publication", ROOT / "publication.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


publication = publication_module()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def card() -> dict:
    return json.loads((ROOT / "card.json").read_bytes())


def synthetic_receipt(manifest: dict) -> dict:
    """Test-only receipt shaped like the real one; its command digest is deliberately fake."""
    return {
        "schema_version": "pals.recipe-admission-compiler-receipt.v1",
        "materialized_source_sha256": sha(publication.materialize(manifest)),
        "toolchain_fingerprint_sha256": sha(rfc8785.dumps(manifest["toolchain"]["fingerprint"])),
        "compiler_command_sha256": "0" * 64,
        "compiler_result": {
            "schema_version": "pals.recipe-admission-compiler-result.v1",
            "verification_succeeded": True,
            "diagnostic_codes": ["lean.verified"],
        },
    }


def synthetic_entry() -> dict:
    value = card()
    manifest = publication.authoring_manifest(value)
    return publication.search_candidate(value, manifest, synthetic_receipt(manifest))


def escaped(text: str) -> str:
    """How a string appears inside the JSON data block of a judge prompt."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def candidate_row(entry: dict) -> dict:
    """The API's search-result shape for this entry, built from the same bytes."""
    value = card()
    manifest = publication.authoring_manifest(value)
    return {
        "recipe_id": entry["recipe_id"],
        "recipe_revision": entry["recipe_revision"],
        "entry_sha256": sha(rfc8785.dumps(entry)),
        "statement": entry["statement"],
        "domain": entry["domain"],
        "assumptions": entry["assumptions"],
        "quantifiers": entry["quantifiers"],
        "conclusion": entry["conclusion"],
        "proof_method_tag": entry["proof_method_tag"],
        "output_language": "ja",
        "target_source": value["target_source"],
        "lean_code": publication.materialize(manifest).decode(),
        "lean_sha256": entry["lean_sha256"],
        "answer": entry["answer"],
        "answer_sha256": entry["answer_sha256"],
        "compiler_receipt_sha256": entry["compiler_receipt_sha256"],
        "toolchain_sha256": entry["toolchain_sha256"],
    }


def batch_for(row_list: list[dict], r: dict) -> dict:
    rows = sorted(row_list, key=lambda row: (row["recipe_id"], row["recipe_revision"]))
    batch = {
        "schema_version": "pals.recipe-catalog-batch.v1",
        "request_id": r["id"],
        "claim_id": CLAIM_ID,
        "request_revision": 1,
        "request_context_sha256": digest(
            {k: r[k] for k in ("statement", "context_turns", "output_language")}
        ),
        "output_language": "ja",
        "toolchain_sha256": rows[0]["toolchain_sha256"],
        "complete": True,
        "truncated": False,
        "reason": None,
        "total_count": len(rows),
        "recipes": rows,
    }
    batch["batch_sha256"] = digest(
        {
            "schema_version": CONTENT_SCHEMA,
            **{k: batch[k] for k in ("output_language", "toolchain_sha256", "recipes")},
        }
    )
    return batch


# ---------------------------------------------------------------- source, manifest, entry


def test_card_claims_no_lifecycle_beyond_authored():
    value = card()
    assert value["status"] == "authored_awaiting_execution"
    assert value["lifecycle"] == {
        "authored": True,
        "independently_reviewed": False,
        "admitted": False,
        "retrievable": False,
        "runtime_verified": False,
        "deployed": False,
    }


def test_authored_artifacts_do_not_drift():
    assert sha((ROOT / "card.json").read_bytes()) == CARD_SHA256
    path = ROOT / "publication" / (RECIPE_ID + ".json")
    assert sha(path.read_bytes()) == MANIFEST_SHA256
    manifest = publication.authoring_manifest(card())
    assert path.read_bytes() == rfc8785.dumps(manifest)
    assert sha(publication.materialize(manifest)) == MATERIALIZED_SHA256
    assert sha(card()["answer"].encode()) == ANSWER_SHA256


def test_manifest_is_the_exact_closed_single_target_with_explicit_scope():
    value = card()
    manifest = publication.authoring_manifest(value)
    assert manifest["recipe_id"] == RECIPE_ID == value["id"]
    assert manifest["toolchain"] == publication.EXPECTED_TOOLCHAIN
    assert manifest["source_author_principal"] == publication.AUTHOR
    assert manifest["author_profile"]["source_author_principal"] == publication.AUTHOR
    source = publication.materialize(manifest).decode()
    declaration = extract_single_target_declaration(source)
    assert declaration is not None and declaration.kind == "example"
    # Domain and codomain R, the exponent is the literal 2, and nothing is assumed beyond that.
    assert declaration.proposition == "Continuous (fun x : ℝ => x ^ 2)"
    assert declaration.proposition == value["target_source"]
    assert find_source_violation(source) is None
    assert not re.search(r"\b(?:sorry|sorryAx|admit|axiom|unsafe|native_decide)\b", source)
    # The elementary proof must not close with a shortcut continuity lemma.
    assert not re.search(r"continuous_id|Continuous\.pow|continuous_pow|fun_prop", source)
    assert "Metric.continuous_iff" in source


def test_existing_seed_draft_states_the_same_proposition_as_the_recipe_target():
    """The API repository checks the matcher against this exact Draft XML pin."""
    seed = json.loads(
        (ROOT.parents[1] / "pals_agent/seed/dsp_drafts.json").read_text(encoding="utf-8")
    )
    draft = next(item for item in seed if item["id"] == "continuous_square")
    assert sha(draft["openmath_xml"].encode()) == SEED_DRAFT_XML_SHA256
    assert (
        'name="continuous_on"' in draft["openmath_xml"] and "<OMI>2</OMI>" in draft["openmath_xml"]
    )
    assert "continuous on ℝ" in draft["matched_prompt"] and "x^2" in draft["matched_prompt"]
    assert "δ = min 1 (ε / (2 * |x| + 1))" in draft["proof_strategy"]


def test_theorem_file_and_manifest_share_one_proof_body():
    value = card()
    theorem = (ROOT / value["source_path"]).read_text()
    assert len(re.findall(r"^theorem\s+", theorem, re.M)) == 1
    assert theorem.startswith("import Mathlib\n")
    assert publication.proof_body(value) in theorem


def test_search_entry_binds_receipt_and_stored_answer_without_inventing_evidence():
    value = card()
    manifest = publication.authoring_manifest(value)
    receipt = synthetic_receipt(manifest)
    entry = publication.search_candidate(value, manifest, receipt)
    assert entry["schema_version"] == "pals.recipe-search-entry.v1"
    assert entry["output_language"] == "ja"
    assert entry["proof_method_tag"] == "epsilon_delta"
    assert entry["answer"] == value["answer"] and entry["answer_sha256"] == ANSWER_SHA256
    assert entry["lean_sha256"] == MATERIALIZED_SHA256
    assert entry["compiler_receipt_sha256"] == sha(rfc8785.dumps(receipt))
    assert not {"review", "review_signature", "embedding"} & set(entry)
    assert len(entry["search_text"].encode()) < 20_000
    lowered = entry["search_text"].lower()
    for phrase in ("x squared", "square function", "epsilon delta", "x^2", "x²", "二乗", "2乗"):
        assert phrase in lowered
    for field in ("materialized_source_sha256", "toolchain_fingerprint_sha256"):
        with pytest.raises(ValueError, match="identity mismatch"):
            publication.search_candidate(value, manifest, {**receipt, field: "f" * 64})
    with pytest.raises(ValueError, match="identity mismatch"):
        publication.search_candidate(value, manifest, {**receipt, "extra": True})
    failed = {
        **receipt,
        "compiler_result": {**receipt["compiler_result"], "verification_succeeded": False},
    }
    with pytest.raises(ValueError, match="successful closed"):
        publication.search_candidate(value, manifest, failed)
    changed = {**manifest, "target_source": "Continuous (fun x : ℝ => x ^ 3)"}
    with pytest.raises(ValueError, match="identity mismatch"):
        publication.search_candidate(value, changed, synthetic_receipt(changed))
    wrong_toolchain = {**manifest["toolchain"], "toolchain_id": "other-toolchain"}
    with pytest.raises(ValueError, match="frozen compiler"):
        publication.search_candidate(value, {**manifest, "toolchain": wrong_toolchain}, receipt)


def test_an_observed_toolchain_replaces_the_frozen_binding_only_when_explicit(tmp_path):
    value = card()
    observed = {
        "toolchain_id": publication.EXPECTED_TOOLCHAIN["toolchain_id"] + "-next",
        "fingerprint": {
            **publication.EXPECTED_TOOLCHAIN["fingerprint"],
            "verifier_sha256": "ab" * 32,
        },
    }
    path = tmp_path / "toolchain.json"
    path.write_bytes(rfc8785.dumps(observed))
    toolchain = publication.load_toolchain(path)
    manifest = publication.authoring_manifest(value, toolchain)
    receipt = synthetic_receipt(manifest)
    entry = publication.search_candidate(value, manifest, receipt, toolchain)
    assert entry["toolchain_sha256"] != synthetic_entry()["toolchain_sha256"]
    assert manifest["proof_body"] == publication.authoring_manifest(value)["proof_body"]
    with pytest.raises(ValueError, match="frozen compiler"):
        publication.search_candidate(value, manifest, receipt)  # default is still the frozen one
    path.write_bytes(rfc8785.dumps({**observed, "extra": 1}))
    with pytest.raises(ValueError, match="fingerprint shape"):
        publication.load_toolchain(path)
    bad = {**observed, "fingerprint": {**observed["fingerprint"], "verifier_sha256": "zz"}}
    path.write_bytes(rfc8785.dumps(bad))
    with pytest.raises(ValueError, match="fingerprint shape"):
        publication.load_toolchain(path)
    assert publication.load_toolchain(None) == publication.EXPECTED_TOOLCHAIN


# ---------------------------------------------------------------- the stored answer


def test_answer_is_an_explicit_epsilon_delta_proof_accepted_by_the_repo_validators():
    answer = card()["answer"]
    # The text gate was replaced by the independent checklist review (explanation semantic gate);
    # the structural Lean-vocabulary check remains.
    _reject_lean_source_terms(answer, "stored answer")
    assert r"\delta=\min\left\{1,\frac{\varepsilon}{2|a|+1}\right\}" in answer
    assert "|x^2-a^2|=|x-a||x+a|" in answer
    assert r"\le|x-a|(2|a|+1)<\varepsilon" in answer
    for bound in (r"|x+a|<2|a|+1", r"|x|\le|x-a|+|a|<|a|+1"):
        assert bound in answer
    # Presentation: Japanese proof prose, inline KaTeX only, no headings, bullets or code.
    assert re.search(r"[ぁ-んァ-ヶ一-龠]", answer)
    assert "$$" not in answer and answer.count("$") % 2 == 0
    assert not re.search(r"^(#|\s*[-*•]|\s*\d+[.)])", answer, re.M)
    assert "`" not in answer and "\\\\" not in answer
    for paragraph in answer.strip().split("\n\n"):
        assert paragraph.strip().endswith("。")
    # Variables are bound before use. The definition quantifies epsilon and delta in order
    # and only then fixes an arbitrary epsilon, so the opening does not pre-fix epsilon.
    assert answer.startswith("$a$ を任意の実数とします。")
    assert "任意の $\\varepsilon>0$ に対して、ある $\\delta>0$ が存在し" in answer
    assert answer.index("となることです。") < answer.index("そこで $\\varepsilon>0$ を任意に取り")
    assert "すべての実数 $x$" in answer
    # delta shrinks with |a|, not with a: a negative a of large modulus is not "large".
    assert "$|a|$ が大きいほど小さくなる" in answer and "$a$ が大きいほど" not in answer
    # Only claims the Lean target supports: pointwise continuity, nothing about uniformity.
    for foreign in ("一様", "微分", "導関数", "コンパクト"):
        assert foreign not in answer


def test_delta_choice_and_every_stated_bound_hold_in_exact_arithmetic():
    """Independent of Lean: check the answer's own inequalities on a dense exact grid."""
    points = [Fraction(n, 7) for n in range(-60, 61)] + [Fraction(10**6), Fraction(-(10**6), 3)]
    epsilons = [
        Fraction(1, 10**6),
        Fraction(1, 100),
        Fraction(1, 2),
        Fraction(1),
        Fraction(37, 5),
        Fraction(10**5),
    ]
    fractions = [Fraction(k, 64) for k in range(1, 64)] + [Fraction(999999, 10**6)]
    checked = 0
    for a in points:
        for epsilon in epsilons:
            delta = min(Fraction(1), epsilon / (2 * abs(a) + 1))
            assert delta > 0
            for t in fractions:
                for x in (a + t * delta, a - t * delta):
                    assert abs(x - a) < delta <= 1
                    assert abs(x) < abs(a) + 1
                    assert abs(x + a) < 2 * abs(a) + 1
                    assert abs(x * x - a * a) == abs(x - a) * abs(x + a)
                    assert abs(x * x - a * a) <= abs(x - a) * (2 * abs(a) + 1) < epsilon
                    checked += 1
    assert checked == 94_464


def test_delta_must_depend_on_the_point_as_the_answer_remarks():
    """A point-independent delta fails for large a, so the answer's a-dependence is not cosmetic."""
    epsilon = Fraction(1)
    for delta in (Fraction(1, 10), Fraction(1, 1000)):
        a = Fraction(10**4)
        x = a + delta / 2
        assert abs(x - a) < delta and abs(x * x - a * a) >= epsilon


# ---------------------------------------------------------------- retrieval and judge contract


def seed_rows() -> list[dict]:
    cases = json.loads((SEEDS / "corpus.json").read_bytes())["cases"]
    return [
        {
            "entry_sha256": sha(case["statement"].encode()),
            "statement": case["statement"],
            "recipe_id": case["id"],
        }
        for case in cases
    ]


def card_row() -> dict:
    value = card()
    return {
        "entry_sha256": sha(value["statement"].encode()),
        "statement": value["statement"],
        "recipe_id": RECIPE_ID,
    }


def window(question: str, rows: list[dict]) -> list[str]:
    by_pin = {row["entry_sha256"]: row["recipe_id"] for row in rows}
    return [by_pin[pin] for pin in rank(rows, question)]


def test_exact_statement_and_paraphrases_rank_the_card_in_the_review_window():
    value = card()
    rows = [*seed_rows(), card_row()]
    questions = [
        value["statement"],
        *value["question_variants"]["ja"],
        *value["question_variants"]["en"],
    ]
    assert len(questions) == 12
    for question in questions:
        ranked = window(question, rows)
        assert len(ranked) == 5
        # Ranking only chooses a window for the two judges; it never accepts a match.
        assert RECIPE_ID in ranked[:3], question
    assert window(value["statement"], rows)[0] == RECIPE_ID


def test_every_hard_negative_is_distinct_and_excluded_by_a_stored_scope_field():
    """Table audit: the dimension each wrong statement changes is stated in this card's fields.

    Real rejection is the two independent judges' job and is NOT exercised offline.
    """
    value = card()
    fields = "\n".join(
        [
            value["statement"],
            value["domain"],
            value["conclusion"],
            *value["assumptions"],
            *value["quantifiers"],
        ]
    )
    negatives = {item["id"]: item for item in value["hard_negatives"]}
    assert set(negatives) == {
        "cube",
        "restricted_domain",
        "uniform",
        "differentiable",
        "existence",
        "at_zero_only",
        "at_zero",
        "rational_power",
        "natural_power",
        "complex_square",
        "lipschitz",
        "shifted_square",
        "without_epsilon_delta",
    }
    variants = set(value["question_variants"]["ja"] + value["question_variants"]["en"])
    for item in negatives.values():
        assert item["statement"] != value["statement"] and item["statement"] not in variants
        assert item["dimension"] in {"objects", "domain", "quantifiers", "conclusion", "method"}
        assert item["reason"].strip()
    assert "x^3" not in fields and "x^3" in negatives["cube"]["statement"].replace(" ", "")
    assert "[0,1]" in negatives["restricted_domain"]["statement"] and "[0,1]" not in fields
    assert "一様" in negatives["uniform"]["statement"] and "一様" not in fields
    assert "依存してよい" in fields  # pointwise: delta may depend on a
    assert "微分可能" in negatives["differentiable"]["statement"] and "微分" not in fields
    assert "任意の実数 $a$ と任意の $\\varepsilon>0$" in fields
    assert (
        "存在" in negatives["existence"]["statement"]
        and "x^2-1" in negatives["existence"]["statement"]
    )
    assert "でのみ" in negatives["at_zero_only"]["statement"] and "でのみ" not in fields
    assert "すべての点で連続" in fields
    assert "x=0" in negatives["at_zero"]["statement"] and "x=0" not in fields
    assert "有理数" in negatives["rational_power"]["statement"] and "有理数" not in fields
    assert "任意の自然数" in negatives["natural_power"]["statement"] and "自然数 $n$" not in fields
    assert "複素数" in negatives["complex_square"]["statement"] and "複素数" not in fields
    assert "リプシッツ" in negatives["lipschitz"]["statement"] and "リプシッツ" not in fields
    assert "(x-1)^2" in negatives["shifted_square"]["statement"] and "(x-1)" not in fields
    # A request that excludes the stored method conflicts with the card's declared method.
    assert "使わず" in negatives["without_epsilon_delta"]["statement"]
    assert value["proof_method_tag"] == "epsilon_delta" and "使わず" not in fields
    assert "\\mathbb{R}" in fields


def test_exact_input_profile_for_natural_powers_never_covers_the_square_card():
    """No exact-input registry exists for this card: every request still needs both judges."""
    entry = synthetic_entry()
    value = card()
    for statement in (value["statement"], *value["question_variants"]["ja"]):
        assert not eligible(request(statement))
    assert not candidate_matches(candidate_row(entry))
    assert entry["recipe_id"] != NATURAL_POWER_PINS["recipe_id"]


def verdict(row: dict, action: str = "reuse") -> dict:
    reuse = action == "reuse"
    return {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "tasks": [{"kind": "prove", "answer_relation": "proves_assertion"}] if reuse else [],
        "recipe_id": row["recipe_id"] if reuse else None,
        "recipe_revision": row["recipe_revision"] if reuse else None,
        "request_scope": {
            "objects_and_types": ["f : Real -> Real", "f(x)=x^2"],
            "domain": "Real",
            "assumptions": [],
            "quantifiers_and_dependencies": ["continuity at every real point"],
            "conclusion": row["target_source"],
            "required_method": None,
        },
        "source_target_sha256": sha(row["target_source"].encode()) if reuse else None,
        "checks": dict.fromkeys(
            ("objects", "domain", "assumptions", "quantifiers", "conclusion", "method"), reuse
        ),
        "answer_qa": reuse,
        "relevant_conventions": [],
        "unresolved": [],
        "rationale": "Scripted fixture for the offline contract test, not a model judgment.",
    }


class ScriptedTransport:
    """Scripted per-role provider replies on the real client path; no network, no spend."""

    def __init__(self, assessment: dict, review: dict):
        self.replies = {"assessment": assessment, "review": review}
        self.bodies: list[dict] = []

    def request(self, **kwargs):
        body = json.loads(kwargs["body"])
        if kwargs["url"].endswith("/input_tokens"):
            return HttpResponse(200, b'{"object":"response.input_tokens","input_tokens":1000}')
        self.bodies.append(body)
        role = "review" if "ROLE: Act as an adversarial" in body["input"] else "assessment"
        result = {
            "object": "response",
            "status": "completed",
            "model": body["model"],
            "id": "resp_review_square" if role == "review" else "resp_assessment_square",
            "error": None,
            "incomplete_details": None,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 60,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 10},
            },
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(self.replies[role])}],
                }
            ],
        }
        return HttpResponse(200, json.dumps(result).encode())


def run_attempt(statement: str, assessment: dict, review: dict):
    r = request(statement)
    row = candidate_row(synthetic_entry())
    batch = batch_for([row], r)
    transport = ScriptedTransport(assessment, review)
    client = OpenAIResponsesClient(api_key="isolated-test", transport=transport)
    result = attempt(client, r, CLAIM_ID, lambda: batch, deadline=time.monotonic() + 30)
    return r, row, batch, transport, result


@pytest.mark.parametrize(
    "statement",
    [
        "なんでxの二乗は連続なんですか。",
        "x^2の連続性を証明してください。",
        "Prove that x² is continuous.",
    ],
)
def test_two_scripted_approvals_return_the_stored_answer_and_catalog_binding(statement):
    row = candidate_row(synthetic_entry())
    approve = verdict(row)
    r, row, batch, transport, result = run_attempt(statement, approve, copy.deepcopy(approve))
    assert result.answer is not None and len(transport.bodies) == 2
    assert result.answer["text"] == card()["answer"]
    assert result.answer["evidence_kind"] == "lean_catalog" and result.answer["sources"] == []
    assert result.answer["lean"] == {
        "source": "catalog",
        "recipe_id": RECIPE_ID,
        "recipe_revision": 1,
        "entry_sha256": row["entry_sha256"],
        "lean_sha256": MATERIALIZED_SHA256,
        "answer_sha256": ANSWER_SHA256,
        "compiler_receipt_sha256": row["compiler_receipt_sha256"],
        "toolchain_sha256": row["toolchain_sha256"],
    }
    assert "formal_job_id" not in result.evidence
    for body in transport.bodies:
        # The judges see the exact scope fields, target and stored proof they must compare.
        prompt = body["input"]
        assert escaped(statement) in prompt
        assert escaped(card()["quantifiers"][0]) in prompt
        assert "Continuous (fun x : ℝ => x ^ 2)" in prompt
        assert escaped(r"\delta=\min") in prompt


@pytest.mark.parametrize("negative", [item["statement"] for item in card()["hard_negatives"]])
def test_reuse_needs_both_scripted_approvals_and_the_selected_target_hash(negative):
    """Aggregation rule only: it holds for any statement and says nothing about the judges.

    The replies are scripted, so this cannot show that the real judges reject a hard negative.
    """
    row = candidate_row(synthetic_entry())
    approve, decline = verdict(row), verdict(row, "miss")
    for assessment, review in ((approve, decline), (decline, approve), (decline, decline)):
        *_, result = run_attempt(negative, assessment, review)
        assert result.answer is None
    # A judge naming a different target hash (a different proposition) is a hard failure.
    wrong = dict(approve, source_target_sha256=sha(b"Continuous (fun x : \xe2\x84\x9d => x ^ 3)"))
    with pytest.raises(SemanticReuseError):
        run_attempt(negative, wrong, copy.deepcopy(approve))


def test_prompts_for_every_hard_negative_carry_the_statement_and_the_stored_scope():
    r_row = candidate_row(synthetic_entry())
    for item in card()["hard_negatives"]:
        r = request(item["statement"])
        batch = batch_for([r_row], r)
        assert read_batch(r, CLAIM_ID, batch) == [r_row]
        built = prompts(
            r,
            batch,
            {},
            assessment_session="00000000-0000-4000-8000-0000000000a1",
            review_session="00000000-0000-4000-8000-0000000000b1",
            retrieved_entry_sha256s=[r_row["entry_sha256"]],
        )
        for text in built.values():
            assert escaped(item["statement"]) in text and "epsilon_delta" in text
            assert "No specialization" in text and "pointwise versus uniform" in text


def test_a_judge_cannot_select_a_recipe_outside_the_shown_window():
    row = candidate_row(synthetic_entry())
    r = request("x^2の連続性を証明してください。")
    batch = batch_for([row], r)
    raw = json.dumps(verdict(row))
    assert (
        parse(raw, batch, retrieved_entry_sha256s=[row["entry_sha256"]])["recipe_id"]
        == RECIPE_ID
    )
    other = dict(row, recipe_id="requested.natural_power_continuous", entry_sha256="1" * 64)
    two = batch_for([row, other], r)
    with pytest.raises(ValueError, match="response_selected_outside_retrieval_subset"):
        parse(raw, two, retrieved_entry_sha256s=[other["entry_sha256"]])


# ---------------------------------------------------------------- real Lean (opt-in)


@pytest.mark.skipif(
    not (os.environ.get("PALS_SQUARE_LEAN_PROJECT") and os.environ.get("PALS_SQUARE_LEAN_BINARY")),
    reason="needs the pinned Lean v4.32.0-rc1 binary and a compiled Mathlib project",
)
def test_real_pinned_lean_compiles_exact_materialized_source_with_standard_axioms(tmp_path):
    output = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "verify.py"),
            "--project",
            os.environ["PALS_SQUARE_LEAN_PROJECT"],
            "--lean-binary",
            os.environ["PALS_SQUARE_LEAN_BINARY"],
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT.parents[1])},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(output.read_text())
    assert report["materialized_source_sha256"] == MATERIALIZED_SHA256
    assert report["materialized_exit_code"] == 0 and report["materialized_diagnostics"] == ""
    assert set(report["axioms"]) <= {"propext", "Classical.choice", "Quot.sound"}
    assert report["admitted"] is False and report["reviewed"] is False
