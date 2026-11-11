"""Fast lane: pure parts always; the race and the verifier only with a pinned Lean."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pals_agent.automation_portfolio import PORTFOLIO, Tactic
from pals_agent.fast_lane import (
    THEOREM_NAME,
    FastLane,
    candidate_source,
    speculative_accept,
)
from pals_agent.lean import LeanVerifier
from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean

REAL = pytest.mark.skipif(
    not (
        os.environ.get("PALS_RESIDENT_LEAN")
        and os.environ.get("PALS_RESIDENT_LEAN_PATH")
        and os.environ.get("PALS_RESIDENT_LEAN_PROJECT")
    ),
    reason="needs PALS_RESIDENT_LEAN, PALS_RESIDENT_LEAN_PATH and PALS_RESIDENT_LEAN_PROJECT",
)


def test_candidate_source_is_one_closed_theorem_with_a_deterministic_limit() -> None:
    source = candidate_source("∀ n : ℕ, n + 0 = n", Tactic("simp", "intros; simp", 30000))
    assert source == (
        "import Mathlib\n\nset_option maxHeartbeats 30000 in\n"
        f"theorem {THEOREM_NAME} : ∀ n : ℕ, n + 0 = n := by\n  intros; simp\n"
    )


def test_speculative_acceptance_needs_exit_zero_and_a_clean_output() -> None:
    assert speculative_accept(0, "")
    assert not speculative_accept(1, "")
    assert not speculative_accept(0, "x.lean:1:0: warning: declaration uses 'sorry'")
    assert not speculative_accept(0, "x.lean:3:2: error: unsolved goals")


def test_portfolio_has_cheap_tactics_before_exact() -> None:
    names = [t.name for t in PORTFOLIO]
    assert names.index("norm_num") < names.index("exact?")


@pytest.fixture(scope="module")
def lane(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    lean = os.environ["PALS_RESIDENT_LEAN"]
    scratch = tmp_path_factory.mktemp("fast")
    resident = ResidentLean(
        ResidentConfig(
            lean_binary=lean,
            lean_path=os.environ["PALS_RESIDENT_LEAN_PATH"],
            build_dir=scratch / "b",
            project_dir=Path(os.environ["PALS_RESIDENT_LEAN_PROJECT"]),
            max_children=4,
        )
    )
    resident.start()
    toolchain = Path(lean).parent
    verifier = LeanVerifier(
        lean_binary=lean,
        lake_binary=str(toolchain / "lake"),
        project_dir=Path(os.environ["PALS_RESIDENT_LEAN_PROJECT"]),
        child_path=f"{toolchain}:/usr/bin:/bin",
        elan_home=str(Path.home() / ".elan"),
        scratch_dir=scratch,
        resident=resident,
    )
    yield FastLane(resident, verifier)
    resident.close()


@REAL
def test_a_true_statement_is_closed_and_verified(lane: FastLane) -> None:
    result = lane.prove("∀ n : ℕ, n % 4 = 3 → n % 2 = 1")
    assert result.outcome == "verified" and result.tactic is not None
    assert result.speculative_at_s is not None and result.verified_at_s is not None
    assert result.source is not None and "sorry" not in result.source


@REAL
def test_a_false_statement_is_never_verified(lane: FastLane) -> None:
    result = lane.prove("(2 : ℕ) + 2 = 5")
    assert result.outcome == "miss" and result.verified_at_s is None


@REAL
def test_a_statement_outside_the_grammar_is_refused_before_lean(lane: FastLane) -> None:
    assert lane.prove("(by exact trivial : True)").reason == "statement_not_plain"
