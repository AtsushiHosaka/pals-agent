"""The A/B harness for PALS_SPECULATIVE_EXPLANATION_ENABLED measures the real worker path.

It runs ``SqsProofWorker.process_proof_job`` in virtual time, so every case below takes
milliseconds and the expected totals are exact, not statistical.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pals_agent import latency_report, runtime_latency

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "speculative_ab.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("speculative_ab", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ab = _load()


def _scenario(
    review: float, explain: float, explain_review: float, api: float = 0.0, **extra: Any,
) -> Any:
    return ab.Scenario(
        review=f"const:{review}", explain=f"const:{explain}",
        explain_review=f"const:{explain_review}", api=f"const:{api}", **extra,
    )


def _run(scenario: Any, pairs: int = 3, seed: int = 1, order: str = "abab") -> list[Any]:
    results: list[Any] = ab.run_experiment(
        pairs=pairs, seed=seed, scenario=scenario, order=order,
    )
    return results


def _arm(results: list[Any], arm: str) -> list[Any]:
    return [r for r in results if r.arm == arm]


@pytest.mark.parametrize(
    ("review", "explain"),
    [(3.0, 5.0), (6.0, 4.0), (4.0, 4.0)],
    ids=["explanation_longer", "review_longer", "equal"],
)
def test_the_on_arm_costs_the_longer_call_the_off_arm_costs_both(
    review: float, explain: float,
) -> None:
    results = _run(_scenario(review, explain, 2.0))

    for r in _arm(results, "off"):
        assert r.outcome == "completed"
        assert r.total_ms == pytest.approx((review + explain + 2.0) * 1000)
    for r in _arm(results, "on"):
        assert r.outcome == "completed"
        assert r.total_ms == pytest.approx((max(review, explain) + 2.0) * 1000)
    # The stages themselves are the same in both arms: the switch moves them, not shortens them.
    for r in results:
        assert r.semantic_review_ms == pytest.approx(review * 1000)
        assert r.explanation_ms == pytest.approx(explain * 1000)
        assert r.explanation_review_ms == pytest.approx(2.0 * 1000)


def test_api_latency_adds_to_the_serial_path_but_not_to_the_overlapped_one() -> None:
    review, explain, review_of_explanation, api = 5.0, 9.0, 2.0, 0.5
    results = _run(_scenario(review, explain, review_of_explanation, api))

    # After the review starts: settle, claim (both before the explanation can be adopted), write.
    for r in _arm(results, "off"):
        assert r.total_ms == pytest.approx(
            (review + explain + review_of_explanation + 3 * api) * 1000
        )
    for r in _arm(results, "on"):
        assert r.total_ms == pytest.approx(
            (max(review + 2 * api, explain) + review_of_explanation + api) * 1000
        )


def test_the_switch_only_changes_who_calls_the_explainer() -> None:
    results = _run(_scenario(3.0, 5.0, 2.0))

    assert all(not r.speculative_started and r.explain_calls == 1 for r in _arm(results, "off"))
    assert all(r.speculative_started and r.explain_calls == 1 for r in _arm(results, "on"))
    assert all(not r.speculative_discarded for r in results)
    # Each explanation is claimed, reviewed once, written once and billed once.
    assert all(r.explanation_upserts == 2 and r.explain_usage_forwarded == 1 for r in results)


def test_a_rejected_review_discards_the_early_call_without_writing_or_billing() -> None:
    results = _run(_scenario(3.0, 5.0, 2.0, reject_rate=1.0))

    on = _arm(results, "on")
    assert [r.outcome for r in on] == ["rejected"] * 3
    assert all(r.speculative_started and r.speculative_discarded for r in on)
    assert all(r.explain_calls == 1 for r in on)  # the speculative call did run ...
    assert all(r.explanation_upserts == 0 for r in on)  # ... but no claim, no write
    assert all(r.explain_usage_forwarded == 0 for r in on)  # ... and nothing billed
    assert all(r.total_ms is None and r.explanation_review_ms is None for r in on)
    # The off arm never starts one.
    off = _arm(results, "off")
    assert all(r.outcome == "rejected" and r.explain_calls == 0 for r in off)
    assert all(r.explanation_upserts == 0 and r.explain_usage_forwarded == 0 for r in off)
    # The review took the same time either way, and the table says so.
    assert [r.semantic_review_ms for r in on] == [r.semantic_review_ms for r in off]


def test_a_failed_early_call_ends_like_a_direct_failure_and_is_still_billed() -> None:
    results = _run(_scenario(3.0, 5.0, 2.0, explain_fail_rate=1.0))

    for r in results:
        assert r.outcome == "explanation_failed"
        assert r.explain_calls == 1
        assert r.explanation_upserts == 2  # generating, then failed
        assert r.explain_usage_forwarded == 1
    assert not any(r.speculative_discarded for r in results)


def test_arms_alternate_abab_and_abba_flips_every_second_pair() -> None:
    assert [arm for _, arm in ab.arm_sequence(3, "abab")] == ["off", "on"] * 3
    assert [arm for _, arm in ab.arm_sequence(4, "abba")] == [
        "off", "on", "on", "off", "off", "on", "on", "off",
    ]
    results = _run(_scenario(1.0, 1.0, 1.0), pairs=4)
    assert [r.arm for r in results] == ["off", "on"] * 4
    assert [r.pair for r in results] == [0, 0, 1, 1, 2, 2, 3, 3]


def test_both_arms_of_a_pair_share_their_random_draws() -> None:
    scenario = ab.Scenario()  # the default lognormal distributions
    results = ab.run_experiment(pairs=6, seed=3, scenario=scenario)

    by_pair: dict[int, dict[str, Any]] = {}
    for r in results:
        by_pair.setdefault(r.pair, {})[r.arm] = r
    for arms in by_pair.values():
        assert arms["off"].semantic_review_ms == pytest.approx(arms["on"].semantic_review_ms)
        assert arms["off"].explanation_ms == pytest.approx(arms["on"].explanation_ms)
        assert arms["on"].total_ms < arms["off"].total_ms
    assert len({round(arms["off"].total_ms) for arms in by_pair.values()}) > 1  # draws vary


def test_a_seed_fixes_the_outcome_and_another_seed_changes_it() -> None:
    def totals(seed: int) -> list[float | None]:
        return [r.total_ms for r in ab.run_experiment(pairs=5, seed=seed, scenario=ab.Scenario())]

    assert totals(11) == totals(11)
    assert totals(11) != totals(12)


def test_events_are_the_repos_latency_events_and_latency_report_reads_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = _run(_scenario(3.0, 5.0, 2.0), pairs=2)
    assert all(r.event is not None for r in results)

    # Byte for byte what the worker's own emitter writes.
    runtime_latency.report_latency(results[0].event)
    assert capsys.readouterr().err.strip() == ab._event_line(results[0].event)

    lines = [ab._event_line(r.event) for r in results]
    event = json.loads(lines[0])
    assert event["event"] == "proof_request_latency"
    assert event["metrics"]["schema_version"] == "pals.runtime-latency-aggregates.v2"
    assert event["metrics"]["trace_kind"] == "proof_job"

    samples = latency_report.collect(lines)
    path = "fresh_proof_job"
    assert samples[path, "local/semantic_review"] == pytest.approx([3000.0] * 4)
    assert samples[path, "provider/generation[explain]"] == pytest.approx([5000.0] * 4)
    assert samples[path, "provider/generation[explanation_review]"] == pytest.approx([2000.0] * 4)
    assert samples[path, "provider/generation[semantic_review]"] == pytest.approx([3000.0] * 4)
    assert len(samples[path, "trace/processor_elapsed_ms"]) == 4
    # Off: 3 + 5 + 2 s of model time end to end; on: the explanation call is hidden in the review.
    elapsed = samples[path, "trace/processor_elapsed_ms"]
    assert elapsed[0] > elapsed[1]


def test_a_rejected_delivery_still_emits_its_event_with_the_call_left_in_flight() -> None:
    # The early call outlives the delivery (5 s against a 3 s review): its span is unfinished.
    results = _run(_scenario(3.0, 5.0, 2.0, reject_rate=1.0), pairs=1)

    on = _arm(results, "on")[0]
    assert on.event is not None
    assert on.event["all_recorded_spans_finished"] is False
    assert on.event["complete_timing_capture"] is False
    roles = {row["role"] for row in on.event["phases"] if row["service"] == "provider"}
    assert roles == {"semantic_review"}  # the unfinished explain span is not counted
    off = _arm(results, "off")[0]
    assert off.event is not None and off.event["all_recorded_spans_finished"] is True


def test_the_summary_reports_p50_p95_mean_counts_and_a_paired_interval() -> None:
    results = ab.run_experiment(pairs=8, seed=2, scenario=ab.Scenario(reject_rate=0.25))
    summary = ab.summarize(results, resamples=500, seed=2)

    off, on = summary["arms"]["off"], summary["arms"]["on"]
    assert off["iterations"] == on["iterations"] == 8
    assert on["speculative_started"] == 8 and off["speculative_started"] == 0
    assert on["speculative_discarded"] == on["outcomes"].get("rejected", 0) > 0
    assert off["completed"] + off["failed"] == 8
    total = on["metrics"]["total"]
    assert total["p50_ms"] <= total["p95_ms"] and total["n"] == on["completed"]
    paired = summary["paired_off_minus_on"]["total"]
    low, high = paired["ci95_ms"]
    assert low <= paired["mean_diff_ms"] <= high and low > 0  # the switch saves time here
    assert summary["paired_off_minus_on"]["semantic_review"]["mean_diff_ms"] == 0.0

    table = ab.render_table(summary, "header")
    for text in ("p50_ms", "p95_ms", "mean_ms", "spec_discarded", "total", "[", "95% bootstrap CI"):
        assert text in table


def test_bootstrap_interval_is_deterministic_and_degenerates_for_constant_data() -> None:
    assert ab.bootstrap_mean_ci([4.0] * 5, resamples=200, seed=1) == (4.0, 4.0, 4.0)
    first = ab.bootstrap_mean_ci([1.0, 2.0, 3.0, 10.0], resamples=300, seed=5)
    assert first == ab.bootstrap_mean_ci([1.0, 2.0, 3.0, 10.0], resamples=300, seed=5)
    mean, low, high = first
    assert low <= mean <= high and low >= 1.0 and high <= 10.0


@pytest.mark.parametrize("spec", ["", "const", "const:-1", "uniform:3,1", "lognormal:0,1", "x:1"])
def test_bad_distributions_are_rejected(spec: str) -> None:
    with pytest.raises(ValueError):
        ab.parse_distribution(spec)


def test_main_prints_the_table_and_writes_events_per_arm(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    prefix = tmp_path / "events"
    code = ab.main(["-n", "3", "--seed", "4", "--events", str(prefix)])

    out = capsys.readouterr()
    assert code == 0
    assert "p50_ms" in out.out and "paired difference" in out.out
    for arm in ("off", "on"):
        lines = (tmp_path / f"events.{arm}.jsonl").read_text().splitlines()
        assert len(lines) == 3
        assert latency_report.collect(lines)["fresh_proof_job", "local/semantic_review"]

    code = ab.main(["-n", "2", "--json", "--events", "none"])
    assert code == 0
    assert set(json.loads(capsys.readouterr().out)) == {"arms", "paired_off_minus_on"}


def test_main_sends_events_to_stderr_by_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert ab.main(["-n", "1"]) == 0
    err = capsys.readouterr().err
    events = [json.loads(line) for line in err.splitlines() if line.startswith("{")]
    assert [e["event"] for e in events] == ["proof_request_latency"] * 2


def test_real_mode_needs_the_spend_flag_and_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("PALS_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    assert ab.main(["--real"]) == 2
    assert "--confirm-spend" in capsys.readouterr().err

    assert ab.main(["--real", "--confirm-spend", "-n", "1"]) == 2
    err = capsys.readouterr().err
    assert "real mode not run" in err and "credentials" in err.lower()


def test_invalid_arguments_exit_with_a_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert ab.main(["-n", "0"]) == 2
    assert ab.main(["-n", "1", "--review", "nonsense"]) == 2
    assert "error:" in capsys.readouterr().err


def test_virtual_time_does_not_leak_into_the_tracing_module() -> None:
    import time

    _run(_scenario(1.0, 1.0, 1.0), pairs=1)
    assert vars(runtime_latency)["time"] is time
