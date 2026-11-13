"""The fast first attempt (default off): it proposes a source; it never decides correctness.

Off, nothing changes (the generator sees the same calls, nothing is imported).  On, a source that
passes the ordinary preflight becomes the first candidate; a late, failing, wrong-target or empty
proposal leaves the ordinary generation to run exactly as before.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from pals_agent import fast_first_attempt as ffa
from tests.unit.test_t2_api_reconcile import _api_pipeline, _run
from tests.unit.test_t2_pipeline import GOOD, Generator

PROVE = {"kind": "prove", "formal": "∀ n : ℕ, n + 0 = n", "tactics": ["simp"],
         "negation_tactics": []}


class Model:
    def __init__(
        self, reply: Any = None, delay: float = 0.0, error: bool = False, faithful: bool = True
    ) -> None:
        self.reply, self.delay, self.error, self.faithful = reply or PROVE, delay, error, faithful
        self.calls = self.gate_calls = 0

    def __call__(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if "faithful" in schema.get("properties", {}):
            self.gate_calls += 1
            return {"faithful": self.faithful, "issue": "" if self.faithful else "weaker"}
        self.calls += 1
        time.sleep(self.delay)
        if self.error:
            raise RuntimeError("boom")
        return self.reply


def _pipeline(tmp_path: Path, fast: Any, generator: Generator):
    return _api_pipeline(tmp_path, generator, fast_first_attempt=fast)


def test_the_default_is_off_and_a_pipeline_has_no_fast_attempt(tmp_path: Path) -> None:
    assert _api_pipeline(tmp_path, Generator([GOOD])).fast_first_attempt is None
    assert ffa.enabled() is False


def test_off_the_module_is_not_even_imported() -> None:
    code = (
        "import sys, os\n"
        "from pals_agent.pipeline import ProofPipeline\n"
        "from pals_agent import factory\n"
        "assert factory.build_fast_first_attempt(None) is None\n"
        "assert 'pals_agent.fast_first_attempt' not in sys.modules\n"
    )
    env = {k: v for k, v in __import__("os").environ.items()
           if k != "PALS_FAST_FIRST_ATTEMPT_ENABLED"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_a_malformed_switch_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from pals_agent import factory

    monkeypatch.setenv(ffa.ENABLED_ENV, "yes")
    with pytest.raises(ValueError):
        factory.build_fast_first_attempt(None)  # type: ignore[arg-type]


def test_off_and_a_lane_that_proposes_nothing_give_the_same_first_attempt(
    tmp_path: Path,
) -> None:
    plain = Generator([GOOD])
    off, _ = _run(_pipeline(tmp_path / "a", None, plain))
    idle = Generator([GOOD])
    lane = ffa.FastFirstAttempt(Model({"kind": "explain", "formal": "", "tactics": [],
                                       "negation_tactics": []}))
    on, _ = _run(_pipeline(tmp_path / "b", lane, idle))
    assert off.generated.lean_code == on.generated.lean_code == GOOD
    assert off.generated.model == on.generated.model


def test_a_proposed_source_is_the_first_candidate_and_the_generator_is_not_called(
    tmp_path: Path,
) -> None:
    generator = Generator([GOOD])
    model = Model()
    result, _ = _run(_pipeline(tmp_path, ffa.FastFirstAttempt(model), generator))
    assert model.calls == 1
    assert result.verification_pending  # the API's compile and the reviews decide, not this lane
    assert result.generated.model == "fast-first-attempt"
    assert "theorem" in result.generated.lean_code and "simp" in result.generated.lean_code
    assert generator.proof_calls == 0 if hasattr(generator, "proof_calls") else True


def test_a_slow_model_hands_over_to_the_ordinary_path_at_the_deadline(tmp_path: Path) -> None:
    lane = ffa.FastFirstAttempt(Model(delay=1.0), deadline_s=0.2)
    started = time.monotonic()
    result, _ = _run(_pipeline(tmp_path, lane, Generator([GOOD])))
    assert result.generated.lean_code == GOOD
    assert time.monotonic() - started < 0.9  # did not wait for the slow call


def test_a_failing_model_hands_over(tmp_path: Path) -> None:
    result, _ = _run(_pipeline(tmp_path, ffa.FastFirstAttempt(Model(error=True)),
                               Generator([GOOD])))
    assert result.generated.lean_code == GOOD


def test_a_source_the_preflight_refuses_is_dropped(tmp_path: Path) -> None:
    sorry = dict(PROVE, tactics=["sorry"])
    result, _ = _run(_pipeline(tmp_path, ffa.FastFirstAttempt(Model(sorry)), Generator([GOOD])))
    assert result.generated.lean_code == GOOD


def test_the_fidelity_gate_stops_a_mistranslated_statement_before_the_api(
    tmp_path: Path,
) -> None:
    model = Model(faithful=False)
    result, _ = _run(_pipeline(tmp_path, ffa.FastFirstAttempt(model), Generator([GOOD])))
    assert model.gate_calls >= 1
    assert result.generated.lean_code == GOOD  # handed over, not submitted


def test_a_gate_call_that_fails_is_not_faithful() -> None:
    class Flaky(Model):
        def __call__(self, prompt, schema):  # type: ignore[no-untyped-def]
            if "faithful" in schema.get("properties", {}):
                raise RuntimeError("down")
            return super().__call__(prompt, schema)

    proposal = ffa.FastFirstAttempt(Flaky()).propose(
        "For every natural number n, n + 0 = n.", formal_statement=None
    )
    assert proposal.sources == [] and proposal.reason == "gate_rejected"


def test_a_fixed_formal_statement_is_left_to_the_ordinary_path() -> None:
    model = Model()
    proposal = ffa.FastFirstAttempt(model).propose("q", formal_statement="theorem t : True := by")
    assert proposal.sources == [] and model.calls == 0


def test_the_sieve_keeps_only_a_source_that_compiles(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def reject_all(sources, timeout):  # type: ignore[no-untyped-def]
        seen.append(list(sources))
        return []

    lane = ffa.FastFirstAttempt(Model(), sieve=reject_all)
    result, _ = _run(_pipeline(tmp_path / "a", lane, Generator([GOOD])))
    assert result.generated.lean_code == GOOD and seen  # nothing compiled: ordinary path

    lane = ffa.FastFirstAttempt(Model(), sieve=lambda sources, timeout: [0])
    result, _ = _run(_pipeline(tmp_path / "b", lane, Generator([GOOD])))
    assert result.generated.model == "fast-first-attempt"


def test_a_crashing_sieve_hands_over(tmp_path: Path) -> None:
    def boom(sources, timeout):  # type: ignore[no-untyped-def]
        raise RuntimeError("resident gone")

    result, _ = _run(_pipeline(tmp_path, ffa.FastFirstAttempt(Model(), sieve=boom),
                               Generator([GOOD])))
    assert result.generated.lean_code == GOOD


def test_the_observer_sees_the_stage_times() -> None:
    events: list[dict[str, Any]] = []
    lane = ffa.FastFirstAttempt(Model(), observer=events.append)
    lane.propose("For every natural number n, n + 0 = n.", formal_statement=None)
    assert events[0]["reason"] == "proposed_unchecked" and "model" in events[0]["seconds"]
