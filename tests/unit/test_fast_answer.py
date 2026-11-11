"""Fast answer: prompt parsing, candidate filtering, and (with a pinned Lean) the whole flow."""

from __future__ import annotations

import os
import sys
import time
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


def approve(request: str, source: str, parts: dict, language: str) -> tuple[bool, str]:  # type: ignore[type-arg]
    return True, ""


def test_unknown_gate_modes_are_refused() -> None:
    with pytest.raises(ValueError):
        fa.FastAnswer(  # type: ignore[arg-type]
            resident=None,
            verifier=type("V", (), {"resident": None})(),
            model=None,
            scratch=Path("."),
            gate_mode="nope",
            explanation_reviewer=approve,
        )


@pytest.fixture(scope="module")
def fast(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean
    from pals_agent.lean_verifier.resident.manager import default_read_roots

    lean = os.environ["PALS_RESIDENT_LEAN"]
    scratch = tmp_path_factory.mktemp("fa")
    resident = ResidentLean(
        ResidentConfig(
            lean_binary=lean,
            lean_path=os.environ["PALS_RESIDENT_LEAN_PATH"],
            build_dir=scratch / "b",
            max_children=4,
            project_dir=Path(os.environ["PALS_RESIDENT_LEAN_PROJECT"]),
            confine=sys.platform.startswith("linux"),
            request_root=scratch,
            read_roots=default_read_roots(lean, os.environ["PALS_RESIDENT_LEAN_PATH"]),
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
    yield resident, verifier, scratch
    resident.close()


def fake_model(script: dict):  # type: ignore[no-untyped-def]
    """Answers each prompt kind from a script; every merged call returns the same candidates."""

    def call(prompt: str, schema: dict) -> dict:
        if prompt.startswith("Classify the request, translate"):
            return script["merged"]
        if prompt.startswith("Write the explanation"):
            return {
                "overview": "Take $n$.",
                "sections": ["Then $n + 0 = n$ by definition of addition."],
                "conclusion": "So the claim holds.",
            }
        if "paraphrase" in str(schema.get("properties", {})):
            return {"paraphrase": "p", "differences": "none", "faithful": True}
        return {"faithful": script.get("faithful", True), "issue": ""}

    return call


@REAL
def test_a_true_statement_with_a_good_proof_is_answered_and_verified(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {
        "kind": "prove",
        "formal": "∀ n : ℕ, n + 0 = n",
        "tactics": ["intro n\nsimp"],
        "negation_tactics": [],
    }
    answer = fa.FastAnswer(
        resident,
        verifier,
        fake_model({"merged": merged}),
        scratch,
        calls=2,
        gate_mode="terse2",
        explanation_reviewer=approve,
    )
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert result.outcome == "answered" and result.verified and result.gate is not None
    assert result.gate.passed and result.explanation


@REAL
def test_a_rejecting_review_blocks_the_answer_even_when_lean_proves_it(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {
        "kind": "prove",
        "formal": "∀ n : ℕ, n + 0 = n",
        "tactics": ["intro n\nsimp"],
        "negation_tactics": [],
    }
    model = fake_model({"merged": merged, "faithful": False})
    answer = fa.FastAnswer(
        resident,
        verifier,
        model,
        scratch,
        calls=2,
        gate_mode="terse2",
        explanation_reviewer=approve,
    )
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert result.outcome == "fallthrough" and result.reason == "fidelity_gate_failed"


@REAL
def test_a_false_statement_with_a_wrong_proof_is_never_answered(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {
        "kind": "prove",
        "formal": "(2 : ℕ) + 2 = 5",
        "tactics": ["norm_num", "simp"],
        "negation_tactics": [],
    }
    answer = fa.FastAnswer(
        resident,
        verifier,
        fake_model({"merged": merged}),
        scratch,
        calls=2,
        explanation_reviewer=approve,
    )
    result = answer.run("Show 2 + 2 = 5.", "en")
    assert result.outcome == "fallthrough" and not result.verified


@REAL
def test_a_question_is_answered_no_by_proving_the_negation(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    merged = {
        "kind": "decide",
        "formal": "Function.Injective (fun x : ℝ => x ^ 2)",
        "tactics": [],
        "negation_tactics": ["intro h\nhave := @h 1 (-1) (by norm_num)\nnorm_num at this"],
    }
    answer = fa.FastAnswer(
        resident,
        verifier,
        fake_model({"merged": merged}),
        scratch,
        calls=2,
        gate_mode="terse2",
        explanation_reviewer=approve,
    )
    result = answer.run("Is x ↦ x² injective on the reals?", "en")
    assert result.outcome == "answered" and result.answer == "no"
    assert result.proved is not None and result.proved.startswith("¬")


def _stub_verifier():  # type: ignore[no-untyped-def]
    return type("V", (), {"resident": None})()


def test_an_answer_without_the_explanation_review_is_refused_unless_named() -> None:
    with pytest.raises(ValueError, match="explanation_reviewer"):
        fa.FastAnswer(None, _stub_verifier(), None, Path("."))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="explanation_reviewer"):
        fa.FastAnswer(  # type: ignore[arg-type]
            None, _stub_verifier(), None, Path("."), explain=False, explanation_reviewer=approve
        )
    fa.FastAnswer(  # the explicit development switch, by name
        None,
        _stub_verifier(),
        None,
        Path("."),
        allow_unreviewed_explanation=True,  # type: ignore[arg-type]
    )
    fa.FastAnswer(None, _stub_verifier(), None, Path("."), explanation_reviewer=approve)  # type: ignore[arg-type]


GOOD_MERGED = {
    "kind": "prove",
    "formal": "∀ n : ℕ, n + 0 = n",
    "tactics": ["intro n\nsimp"],
    "negation_tactics": [],
}


@REAL
def test_a_rejected_explanation_blocks_the_answer_and_falls_through(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    calls: list[dict] = []  # type: ignore[type-arg]

    def reject(request: str, source: str, parts: dict, language: str):  # type: ignore[no-untyped-def,type-arg]
        calls.append(parts)
        return False, "rejected:format"

    answer = fa.FastAnswer(
        resident,
        verifier,
        fake_model({"merged": GOOD_MERGED}),
        scratch,
        calls=2,
        gate_mode="terse2",
        explanation_reviewer=reject,
    )
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert calls and result.verified and result.gate is not None and result.gate.passed
    assert result.outcome == "fallthrough" and result.reason == "explanation_rejected"
    assert result.explanation_approved is False and result.explanation_issue == "rejected:format"


@REAL
def test_an_unavailable_explanation_review_is_a_rejection(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast

    def broken(request: str, source: str, parts: dict, language: str):  # type: ignore[no-untyped-def,type-arg]
        raise RuntimeError("reviewer down")

    answer = fa.FastAnswer(
        resident,
        verifier,
        fake_model({"merged": GOOD_MERGED}),
        scratch,
        calls=2,
        gate_mode="terse2",
        explanation_reviewer=broken,
    )
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert result.outcome == "fallthrough" and result.reason == "explanation_rejected"
    assert result.explanation_issue == "review_unavailable"


@REAL
def test_every_wait_is_bounded_by_the_request_budget(fast) -> None:  # type: ignore[no-untyped-def]
    resident, verifier, scratch = fast
    base = fake_model({"merged": GOOD_MERGED})

    def slow_gate(prompt: str, schema: dict) -> dict:  # type: ignore[type-arg]
        if prompt.startswith("You review a formalisation"):
            time.sleep(6.0)  # the review never comes back within the budget
        return base(prompt, schema)

    answer = fa.FastAnswer(
        resident,
        verifier,
        slow_gate,
        scratch,
        calls=2,
        gate_mode="terse2",
        budget_s=2.0,
        explanation_reviewer=approve,
    )
    started = time.monotonic()
    result = answer.run("Show n + 0 = n for every natural n.", "en")
    assert result.outcome == "fallthrough" and result.reason == "budget_exhausted"
    assert time.monotonic() - started < 4.5  # not the 6 s of the slow call


@REAL
def test_a_cancelled_run_stops_and_publishes_nothing(fast) -> None:  # type: ignore[no-untyped-def]
    import threading

    resident, verifier, scratch = fast
    cancel = threading.Event()
    base = fake_model({"merged": GOOD_MERGED})

    def slow(prompt: str, schema: dict) -> dict:  # type: ignore[type-arg]
        time.sleep(3.0)
        return base(prompt, schema)

    answer = fa.FastAnswer(resident, verifier, slow, scratch, calls=2, explanation_reviewer=approve)
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    result = answer.run("q", "en", cancel=cancel)
    assert result.reason == "cancelled" and time.monotonic() - started < 2.0


# ------------------------------------------------------------------ fallback race (no Lean needed)
class _FakeFast:
    def __init__(self, outcome: str, seconds: float, usage: int = 1) -> None:
        self.outcome, self.seconds, self.usage = outcome, seconds, usage
        self.published = 0

    def run(self, request: str, language: str, cancel=None):  # type: ignore[no-untyped-def]
        from pals_agent.usage import forward_usage

        forward_usage([{"model": "fast", "input_tokens": 10, "output_tokens": 5}] * self.usage)
        end = time.monotonic() + self.seconds
        while time.monotonic() < end:
            if cancel is not None and cancel.is_set():
                return fa.FastAnswerResult("fallthrough", "cancelled")
            time.sleep(0.01)
        return fa.FastAnswerResult(self.outcome, None if self.outcome == "answered" else "x")


def _normal(duration: float, stops: list[bool], *, publish: list[str] | None = None):  # type: ignore[no-untyped-def]
    def run(cancel, deadline, claim):  # type: ignore[no-untyped-def]
        from pals_agent.usage import forward_usage

        forward_usage([{"model": "normal", "input_tokens": 100, "output_tokens": 50}])
        end = time.monotonic() + duration
        while time.monotonic() < min(end, deadline):
            if cancel.is_set():
                stops.append(True)
                return None
            time.sleep(0.01)
        if time.monotonic() >= deadline:
            return None  # out of time: no answer
        if publish is not None and claim.try_claim("fallback"):
            publish.append("fallback")  # it saves its own answer, only after winning the claim
        return "normal answer"

    return run


def test_a_verified_fast_answer_cancels_the_normal_path_and_both_spends_are_counted() -> None:
    stops: list[bool] = []
    outcome = fa.run_with_fallback(
        _FakeFast("answered", 0.1), "q", "en", _normal(5.0, stops), deadline_s=10.0
    )
    assert outcome.winner == "fast" and outcome.seconds["total"] < 2.0
    assert sorted(r["model"] for r in outcome.settle(5.0)) == ["fast", "normal"]
    assert stops == [True]


def test_a_fast_failure_costs_nothing_extra_because_the_normal_path_already_runs() -> None:
    outcome = fa.run_with_fallback(
        _FakeFast("fallthrough", 0.2), "q", "en", _normal(0.5, []), deadline_s=10.0
    )
    assert outcome.winner == "fallback" and outcome.fallback_result == "normal answer"
    assert outcome.seconds["total"] < 0.8  # the normal path alone, not 0.2 s + 0.5 s


def test_a_quick_normal_answer_is_not_held_up_by_a_slow_fast_path() -> None:
    fast = _FakeFast("answered", 5.0)
    outcome = fa.run_with_fallback(fast, "q", "en", _normal(0.2, []), deadline_s=10.0)
    assert outcome.winner == "fallback" and outcome.seconds["total"] < 1.5
    outcome.settle(5.0)  # the slow fast path was cancelled, not waited for


def test_the_shared_deadline_ends_both_paths() -> None:
    outcome = fa.run_with_fallback(
        _FakeFast("fallthrough", 0.1), "q", "en", _normal(30.0, []), deadline_s=0.5
    )
    assert outcome.winner == "none" and outcome.seconds["total"] < 2.0


def test_usage_that_arrives_after_the_race_returned_is_still_recorded() -> None:
    def stubborn(cancel, deadline, claim):  # type: ignore[no-untyped-def]
        from pals_agent.usage import forward_usage

        forward_usage([{"model": "normal", "input_tokens": 1, "output_tokens": 1}])
        time.sleep(0.6)  # ignores the cancel, and its provider call is billed all the same
        forward_usage([{"model": "late", "input_tokens": 1, "output_tokens": 1}])
        return None

    outcome = fa.run_with_fallback(_FakeFast("answered", 0.05), "q", "en", stubborn, deadline_s=5)
    assert outcome.winner == "fast"
    assert "late" not in [r["model"] for r in outcome.usage]  # not there yet
    assert "late" in [r["model"] for r in outcome.settle(5.0)]  # but never lost


def test_at_most_one_path_publishes_even_when_both_finish_together() -> None:
    for _ in range(20):
        published: list[str] = []
        fast = _FakeFast("answered", 0.05)
        outcome = fa.run_with_fallback(
            fast, "q", "en", _normal(0.05, [], publish=published), deadline_s=5
        )
        outcome.settle(5.0)
        fast_published = ["fast"] if outcome.winner == "fast" else []
        assert outcome.winner in {"fast", "fallback"}
        # exactly the winner publishes: the fallback only after winning the claim, the caller
        # publishes the fast answer only when the winner is "fast"
        assert published + fast_published == [outcome.winner]
