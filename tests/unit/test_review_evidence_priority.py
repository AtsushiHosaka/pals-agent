"""Review evidence priority and actual guard delegation; no live-model accuracy claim."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import pals_agent.explanations as module
from pals_agent.explanations import (
    ExplanationSection,
    LeanGroundedOutputReviewer,
    LeanLineReference,
    ProofClarification,
    ProofExplanation,
    ProofOutputReviewError,
)

SOURCE = """import Mathlib

-- A blank line and this comment are part of the source coordinates.
theorem normal_index_two (G : Type*) [Group G] (H : Subgroup G) (hi : H.index = 2) :
    ∀ g h : G, h ∈ H → g * h * g⁻¹ ∈ H := by
  have hn : H.Normal := H.normal_of_index_eq_two hi
  intro g h hh
  exact hn.conj_mem h hh g
"""
STATEMENT = "Let G be any group and H a subgroup of index two. Prove H is normal."


class Wire:
    def __init__(self, *decisions: dict):
        self.decisions = list(decisions)
        self.prompts: list[str] = []

    def generate(self, *, model, prompt, timeout_seconds=None):
        self.prompts.append(prompt)
        return json.dumps(self.decisions.pop(0))


def candidate(*, finite: bool = False) -> ProofExplanation:
    return ProofExplanation(
        overview="Let $G$ be a finite group." if finite else "Let $G$ be any group.",
        sections=(ExplanationSection(
            id="normal", title="internal anchor",
            summary=(
                "There are two left and two right cosets. Each coset other than $H$ is its "
                "complement, so $gH=Hg$ for every $g$. Thus $H$ is normal."
            ),
            references=(LeanLineReference(6, 6, SOURCE.splitlines()[5]),),
        ),),
        conclusion="Every $g,h$ with $h\\in H$ satisfies $ghg^{-1}\\in H$.",
        model="fixture", provider="test", prompt="", raw_model_output="{}", elapsed_ms=0,
    )


def review(client: Wire, value: ProofExplanation):
    return LeanGroundedOutputReviewer(client, model="wire", provider="test").review_explanation(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=value, language="en",
    )


def facts(prompt: str) -> dict:
    return json.loads(prompt.split("BEGIN EXACT REFERENCE CHECK\n", 1)[1].split(
        "\nEND EXACT REFERENCE CHECK", 1,
    )[0])


@pytest.mark.parametrize("finite", [False, True])
def test_actual_setup_is_compared_before_the_other_review_requirements(finite):
    value = candidate(finite=finite)
    wire = Wire({"approved": True, "rationale": "scripted wire reply, not an accuracy label"})
    review(wire, value)
    prompt = wire.prompts[0]
    assert prompt.startswith("FIRST: compare the request with the candidate's stated setup")
    assert "For approval, quote a setup span" in prompt
    assert "A valid proof or conclusion does not excuse a strengthened setup" in prompt
    assert prompt.index("FIRST:") < prompt.index("User theorem statement:")
    assert f"User theorem statement:\n{STATEMENT}" in prompt
    payload = json.loads(prompt.split("are not shown):\n", 1)[1])["explanation"]
    assert payload["overview"] == value.overview
    assert payload["sections"][0]["references"][0]["start_line"] == 6


def test_passed_coordinate_fact_is_produced_by_the_existing_exact_validator(monkeypatch):
    calls = []
    original = module._validated_reference

    def checked(payload, source):
        calls.append((payload, source))
        return original(payload, source)

    monkeypatch.setattr(module, "_validated_reference", checked)
    wire = Wire({"approved": True, "rationale": "scripted"})
    review(wire, candidate())
    packet = facts(wire.prompts[0])
    assert len(calls) == 1
    assert calls[0][1] == SOURCE
    assert packet == {
        "checked_references": 1,
        "all_ranges_and_excerpts_match": True,
        "invalid_reference_fields": [],
    }
    assert "Do not override a passed exact-coordinate fact by recounting lines" in wire.prompts[0]


@pytest.mark.parametrize("missing", [False, True])
def test_direct_unvalidated_objects_are_not_described_as_having_passed_coordinates(missing):
    value = candidate()
    references = () if missing else (LeanLineReference(5, 5, SOURCE.splitlines()[5]),)
    bad = replace(value.sections[0], references=references)
    wire = Wire({"approved": False, "rationale": "source coordinates do not match"})
    with pytest.raises(ProofOutputReviewError):
        review(wire, replace(value, sections=(bad,)))
    packet = facts(wire.prompts[0])
    assert packet["all_ranges_and_excerpts_match"] is False
    assert packet["invalid_reference_fields"] == (
        [] if missing else ["explanation.sections[0].references[0]"]
    )


def test_math_span_whitespace_rule_does_not_claim_complete_format_validation():
    wire = Wire({"approved": True, "rationale": "scripted"})
    review(wire, candidate())
    prompt = wire.prompts[0]
    assert "TeX whitespace inside matched math delimiters does not move text outside" in prompt
    assert "Still reject actual bare expressions, broken delimiters or invalid TeX" in prompt
    assert "format_validation_passed" not in facts(prompt)
    assert "Keep rejecting wrong mathematics" in prompt
    assert "a correct conclusion\ncannot excuse an invalid body or source mismatch" in prompt


def test_passed_coordinates_never_override_a_negative_semantic_verdict_or_add_a_vote():
    wire = Wire(
        {"approved": False, "rationale": "an essential mathematical implication is missing"},
        {"approved": True, "rationale": "must remain unused"},
    )
    with pytest.raises(ProofOutputReviewError) as result:
        review(wire, candidate())
    assert result.value.category == "rejected"
    assert len(wire.prompts) == 1
    assert len(wire.decisions) == 1


def test_priority_packet_is_not_added_to_clarification_questions():
    value = candidate()
    clarification = ProofClarification(
        section_id="normal", question="What if the group is additionally assumed finite?",
        answer="That is an explicit stronger hypothesis for this new question.",
        key_points=("The original theorem permits infinite groups.",),
        references=value.sections[0].references, model="fixture", provider="test",
        prompt="", raw_model_output="{}", elapsed_ms=0,
    )
    wire = Wire({"approved": True, "rationale": "scripted"})
    LeanGroundedOutputReviewer(wire, model="wire", provider="test").review_clarification(
        theorem_statement=STATEMENT, lean_code=SOURCE, explanation=value,
        clarification=clarification, language="en",
    )
    prompt = wire.prompts[0]
    assert not prompt.startswith("FIRST:")
    assert "BEGIN EXACT REFERENCE CHECK" not in prompt
    payload = json.loads(prompt.split("are not shown):\n", 1)[1])
    assert payload["clarification"]["question"] == clarification.question
