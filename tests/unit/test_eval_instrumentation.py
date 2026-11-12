"""The measurement harness: usage reaches the budget, and a late call stays out of the next item."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/eval"))

from run_fast_variants import Recorder, instrumented_model  # noqa: E402

from pals_agent.openai import OpenAIResponsesClient  # noqa: E402
from pals_agent.usage import forward_usage, usage_scope  # noqa: E402

ROW = {"model": "gpt-6-luna", "input_tokens": 100, "output_tokens": 10}


@pytest.fixture
def fake_generate(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    state = {"delay": 0.0}

    def generate(self, **kwargs):  # type: ignore[no-untyped-def]
        time.sleep(state["delay"])
        forward_usage([dict(ROW)])  # what the real client reports for the call
        return '{"formal": "x"}'

    monkeypatch.setattr(OpenAIResponsesClient, "generate", generate)
    return state


def test_usage_of_an_instrumented_call_reaches_the_outer_budget(fake_generate) -> None:  # type: ignore[no-untyped-def]
    recorder = Recorder()
    model = instrumented_model("key", recorder, "", {})
    budget: list[dict] = []  # type: ignore[type-arg]
    with usage_scope(budget.append):
        model("Classify the request, translate it into Lean 4 (Mathlib) and give", {})
    assert budget == [ROW]  # the nested scope no longer hides it from the budget
    assert len(recorder.events) == 1 and recorder.events[0]["input_tokens"] == 100


def test_a_call_that_ends_after_the_next_item_started_is_not_recorded_in_it(fake_generate) -> None:  # type: ignore[no-untyped-def]
    recorder = Recorder()
    model = instrumented_model("key", recorder, "", {})
    fake_generate["delay"] = 0.5
    budget: list[dict] = []  # type: ignore[type-arg]
    done = threading.Event()

    def late() -> None:
        with usage_scope(budget.append):
            model("Classify the request, translate it into Lean 4 (Mathlib) and give", {})
        done.set()

    thread = threading.Thread(target=late)
    thread.start()
    time.sleep(0.1)
    recorder.reset()  # the next item starts while the call is in flight
    assert done.wait(5.0)
    assert recorder.events == []  # its record is not mixed into the next item
    assert budget == [ROW]  # but its spend still counts
