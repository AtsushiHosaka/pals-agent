"""Fast answer: prompt parsing, candidate filtering, and (with a pinned Lean) the whole flow."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pals_agent import fast_answer as fa
from pals_agent.fast_lane import candidate_source

REAL = pytest.mark.skipif(
    not (
        os.environ.get("PALS_RESIDENT_LEAN")
        and os.environ.get("PALS_RESIDENT_LEAN_PATH")
        and os.environ.get("PALS_RESIDENT_LEAN_PROJECT")
    ),
    reason="needs PALS_RESIDENT_LEAN, PALS_RESIDENT_LEAN_PATH and PALS_RESIDENT_LEAN_PROJECT",
)


def test_merged_call_parses_candidates_and_caps_them() -> None:
    reply = {
        "kind": "decide",
        "formal": "  ∀ n : ℕ,\n  n + 0 = n ",
        "tactics": ["intro n\nsimp", "", "omega", "ring", "extra-dropped"],
        "negation_tactics": "not a list",
    }
    merged = fa.merged_call(lambda prompt, schema: reply, "q")
    assert (merged.kind, merged.formal) == ("decide", "∀ n : ℕ, n + 0 = n")
    assert merged.tactics == ["intro n\nsimp", "omega"]  # only the first 3 are read, empty dropped
    assert merged.negation_tactics == []


def test_an_unknown_kind_is_explain_and_oversized_scripts_are_dropped() -> None:
    huge = "simp\n" * 1000
    merged = fa.merged_call(
        lambda p, s: {"kind": "bogus", "formal": "", "tactics": [huge], "negation_tactics": []}, "q"
    )
    assert merged.kind == "explain" and merged.tactics == []


def test_model_text_that_the_verifier_policy_forbids_never_reaches_a_child() -> None:
    bad = fa.model_tactics(["run_cmd IO.println 1"])[0]
    good = fa.model_tactics(["intro n\nsimp"])[0]
    assert not fa.acceptable_source(candidate_source("∀ n : ℕ, n = n", bad))
    assert fa.acceptable_source(candidate_source("∀ n : ℕ, n + 0 = n", good))


def test_multiline_model_tactics_are_indented_into_the_theorem() -> None:
    source = candidate_source("∀ n : ℕ, n + 0 = n", fa.model_tactics(["intro n\nsimp"])[0])
    assert source.endswith("by\n  intro n\n  simp\n")


def test_unknown_gate_modes_are_refused() -> None:
    with pytest.raises(ValueError):
        fa.FastAnswer(  # type: ignore[arg-type]
            resident=None, verifier=type("V", (), {"resident": None})(), model=None,
            scratch=Path("."), gate_mode="nope",
        )


@pytest.fixture(scope="module")
def fast(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean

    lean = os.environ["PALS_RESIDENT_LEAN"]
    scratch = tmp_path_factory.mktemp("fa")
    resident = ResidentLean(
        ResidentConfig(
            lean_binary=lean, lean_path=os.environ["PALS_RESIDENT_LEAN_PATH"],
            build_dir=scratch / "b", max_children=4,
        )
    )
    resident.start()
    toolchain = Path(lean).parent
    verifier = LeanVerifier(
        lean_binary=lean, lake_binary=str(toolchain / "lake"),
        project_dir=Path(os.environ["PALS_RESIDENT_LEAN_PROJECT"]),
        child_path=f"{toolchain}:/usr/bin:/bin", elan_home=str(Path.home() / ".elan"),
        scratch_dir=scratch, resident=resident,
    )
    yield resident, verifier, scratch
    resident.close()


def fake_model(script: dict):  # type: ignore[no-untyped-def]
    """Answers each prompt kind from a script; every merged call returns the same candidates."""

    def call(prompt: str, schema: dict) -> dict:
        if prompt.startswith("Classify the request, translate"):
            return script["merged"]
        if prompt.startswith("Write the explanation"):
            return {"explanation": "Because n + 0 = n by definition."}
        if "paraphrase" in str(schema.get("properties", {})):
            return {"paraphrase": "p", "differences": "none", "faithful": True}
        return {"faithful": script.get("faithful", True), "issue": ""}

    return call


@REAL
def test_a_true_statement_with_a_good_proof_is_answered_and_verified(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {"kind": "prove", "formal": "∀ n : ℕ, n + 0 = n", "tactics": ["intro n\nsimp"],
              "negation_tactics": []}
    answer = fa.FastAnswer(resident, verifier, fake_model({"merged": merged}), scratch,
                           calls=2, gate_mode="terse2")
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert result.outcome == "answered" and result.verified and result.gate is not None
    assert result.gate.passed and result.explanation


@REAL
def test_a_rejecting_review_blocks_the_answer_even_when_lean_proves_it(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {"kind": "prove", "formal": "∀ n : ℕ, n + 0 = n", "tactics": ["intro n\nsimp"],
              "negation_tactics": []}
    model = fake_model({"merged": merged, "faithful": False})
    answer = fa.FastAnswer(resident, verifier, model, scratch, calls=2, gate_mode="terse2")
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert result.outcome == "fallthrough" and result.reason == "fidelity_gate_failed"


@REAL
def test_a_false_statement_with_a_wrong_proof_is_never_answered(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {"kind": "prove", "formal": "(2 : ℕ) + 2 = 5", "tactics": ["norm_num", "simp"],
              "negation_tactics": []}
    answer = fa.FastAnswer(resident, verifier, fake_model({"merged": merged}), scratch, calls=2)
    result = answer.run("Show 2 + 2 = 5.", "en")
    assert result.outcome == "fallthrough" and not result.verified


@REAL
def test_a_question_is_answered_no_by_proving_the_negation(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {"kind": "decide", "formal": "Function.Injective (fun x : ℝ => x ^ 2)",
              "tactics": [], "negation_tactics": [
                  "intro h\nhave := @h 1 (-1) (by norm_num)\nnorm_num at this"]}
    answer = fa.FastAnswer(resident, verifier, fake_model({"merged": merged}), scratch,
                           calls=2, gate_mode="terse2")
    result = answer.run("Is x ↦ x² injective on the reals?", "en")
    assert result.outcome == "answered" and result.answer == "no"
    assert result.proved is not None and result.proved.startswith("¬")
