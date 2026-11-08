"""p50/p95 per step, per-run totals and per-step shares from ``step_timing`` events.

    python -m pals_agent.step_timing_report steps.jsonl
    python -m pals_agent.step_timing_report steps.jsonl --hint-ab results/run.jsonl
    python -m pals_agent.step_timing_report - --json < steps.jsonl

Reads JSONL written with ``PALS_STEP_TIMING_JSONL`` (or CloudWatch log lines that carry the
same fields). Other lines are ignored. ``--hint-ab`` joins each ``hint_ab.py`` result record
to the run it produced and prints the differences, so the two measurements can be checked
against each other. Percentiles use the interpolation of ``latency_report``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pals_agent.latency_report import percentile
from pals_agent.step_timing import RUN_SCHEMA, SCHEMA

_TOKENS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")


@dataclass
class Samples:
    steps: dict[tuple[str, str, str], list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    runs: list[dict[str, Any]] = field(default_factory=list)


def collect(lines: Iterable[str]) -> Samples:
    samples = Samples()
    for line in lines:
        start = line.find("{")
        if start < 0 or '"schema"' not in line:
            continue
        try:
            event = json.loads(line[start:])
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "pipeline_step":
            duration = event.get("duration_ms")
            if (
                event.get("schema") == SCHEMA
                and isinstance(event.get("step"), str)
                and isinstance(event.get("outcome"), str)
                and isinstance(duration, int | float)
                and not isinstance(duration, bool)
            ):
                name = event["step"] + (" (container)" if event.get("container") else "")
                key = (name, str(event.get("model") or "-"), event["outcome"])
                samples.steps[key].append(float(duration))
        elif event.get("event") == "pipeline_run" and event.get("schema") == RUN_SCHEMA:
            run = _normalized_run(event)
            if run is not None:
                samples.runs.append(run)
    return samples


def _normalized_run(event: dict[str, Any]) -> dict[str, Any] | None:
    """A run record with numeric ``total_ms`` and a ``step_ms`` mapping, or None.

    CloudWatch EMF lines carry the mapping as the JSON text ``step_ms_json``.
    """
    total = event.get("total_ms")
    if isinstance(total, bool) or not isinstance(total, int | float) or total < 0:
        return None
    step_ms = event.get("step_ms")
    if not isinstance(step_ms, dict) and isinstance(event.get("step_ms_json"), str):
        try:
            step_ms = json.loads(event["step_ms_json"])
        except ValueError:
            step_ms = None
    clean = {
        str(k): float(v) for k, v in (step_ms.items() if isinstance(step_ms, dict) else ())
        if isinstance(v, int | float) and not isinstance(v, bool)
    }
    return {**event, "total_ms": float(total), "step_ms": clean}


def rows(samples: Samples) -> list[dict[str, Any]]:
    return [
        {
            "step": step, "model": model, "outcome": outcome, "n": len(values),
            "p50_ms": round(percentile(values, 0.5), 1),
            "p95_ms": round(percentile(values, 0.95), 1),
            "max_ms": round(max(values), 1), "sum_ms": round(sum(values), 1),
        }
        for (step, model, outcome), values in sorted(samples.steps.items())
    ]


def run_summary(samples: Samples) -> dict[str, Any]:
    """Per-run totals and each step's share of the summed run time."""
    runs = samples.runs
    if not runs:
        return {"runs": 0}
    totals = [float(r["total_ms"]) for r in runs if isinstance(r.get("total_ms"), int | float)]
    grand = sum(totals) or 1.0
    by_step: dict[str, float] = defaultdict(float)
    for run in runs:
        for step, ms in (run.get("step_ms") or {}).items():
            by_step[step] += float(ms or 0)
    shares = {step: round(ms / grand, 4) for step, ms in sorted(by_step.items())}
    # Steps can overlap, so the unattributed time is the runs' own recorded wall time with no
    # step running, not what is left after subtracting the summed step times.
    recorded = [
        r["unattributed_ms"] for r in runs if isinstance(r.get("unattributed_ms"), int | float)
    ]
    shares["unattributed"] = round(
        sum(recorded) / grand if len(recorded) == len(runs)
        else max(0.0, 1 - sum(by_step.values()) / grand),
        4,
    )
    truncated = sum(1 for r in runs if r.get("truncated"))
    return {
        "runs": len(runs),
        "step_shares_can_overlap": True,
        "truncated_runs": truncated,
        "total_ms_p50": round(percentile(totals, 0.5), 1),
        "total_ms_p95": round(percentile(totals, 0.95), 1),
        "model_calls_mean": round(sum(r.get("model_calls", 0) for r in runs) / len(runs), 2),
        "share_of_run_time": shares,
    }


def join_hint_ab(samples: Samples, records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each hint_ab record next to the pipeline_run it produced, with the differences."""
    by_run = {str(r.get("run")): r for r in samples.runs}
    joined = []
    for record in records:
        label = record.get("step_timing_run")
        run = by_run.get(str(label))
        if run is None:
            continue
        joined.append({
            "run": label,
            "model_calls": (record.get("model_calls"), run.get("model_calls")),
            "input_tokens": (record.get("input_tokens"), run.get("input_tokens")),
            "output_tokens": (record.get("output_tokens"), run.get("output_tokens")),
            "elapsed_s": (record.get("elapsed_seconds"), round((run["total_ms"] or 0) / 1000, 1)),
            "lean_s": (record.get("lean_seconds"), round((run["lean_ms"] or 0) / 1000, 1)),
        })
    return joined


def render(samples: Samples) -> str:
    out = [f"{'step':<24}{'model':<16}{'outcome':<16}{'n':>5}{'p50_ms':>11}{'p95_ms':>11}"
           f"{'max_ms':>11}{'share':>8}"]
    table = rows(samples)
    total = sum(r["sum_ms"] for r in table if "(container)" not in r["step"]) or 1.0
    for r in table:
        out.append(
            f"{r['step']:<24}{r['model']:<16}{r['outcome']:<16}{r['n']:>5}{r['p50_ms']:>11.1f}"
            f"{r['p95_ms']:>11.1f}{r['max_ms']:>11.1f}"
            + ("   (encloses other steps)" if "(container)" in r["step"]
               else f"{r['sum_ms'] / total:>8.1%}")
        )
    summary = run_summary(samples)
    out.append("")
    if not summary["runs"]:
        out.append("per run: no pipeline_run events")
        return "\n".join(out) + "\n"
    out.append(
        f"per run: n={summary['runs']} total p50={summary['total_ms_p50']}ms "
        f"p95={summary['total_ms_p95']}ms model_calls/run={summary['model_calls_mean']}"
    )
    for step, share in summary["share_of_run_time"].items():
        out.append(f"  {step:<24}{share:>8.1%} of run time")
    out.append("  (steps can overlap, so the shares may add up to more than 100%)")
    if summary["truncated_runs"]:
        out.append(f"  WARNING: {summary['truncated_runs']} run(s) truncated; totals are partial")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+", help="JSONL files, or - for standard input")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--hint-ab", help="hint_ab.py result JSONL to reconcile against")
    args = parser.parse_args(argv)
    samples = Samples()
    for name in args.logs:
        if name == "-":
            part = collect(sys.stdin)
        else:
            with open(name, encoding="utf-8", errors="replace") as stream:
                part = collect(stream)
        for key, values in part.steps.items():
            samples.steps[key].extend(values)
        samples.runs.extend(part.runs)
    joined: list[dict[str, Any]] = []
    if args.hint_ab:
        with open(args.hint_ab, encoding="utf-8") as stream:
            records = [json.loads(line) for line in stream if line.strip().startswith("{")]
        joined = join_hint_ab(samples, records)
    if args.json:
        json.dump({"steps": rows(samples), "runs": run_summary(samples), "hint_ab": joined},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    sys.stdout.write(render(samples))
    for item in joined:
        sys.stdout.write(
            "hint_ab " + str(item["run"]) + ": "
            + ", ".join(f"{k} {v[0]}|{v[1]}" for k, v in item.items() if k != "run") + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
