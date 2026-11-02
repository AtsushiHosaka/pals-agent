"""p50/p95 per answer-path stage from the content-free timing events in the logs.

    python -m pals_agent.latency_report worker.log api.log verifier.log
    docker compose logs --no-log-prefix worker api | python -m pals_agent.latency_report -

Reads only JSON timing events and ``lean_stage`` lines, each of which may follow a log
prefix. Every other line is ignored. p95 is the linear interpolation at rank
(n-1)*0.95; a few samples describe that run and guarantee nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, TextIO

_LEAN_STAGE = re.compile(r"lean_stage stage=([a-z_]+) elapsed_ms=([0-9.]+)")
_DERIVED = (
    "processor_elapsed_ms", "model_generation_union_ms", "non_model_ms", "provider_union_ms",
    "api_union_ms", "local_stage_union_ms", "unattributed_ms",
)
_SERVICE_TOTALS = {"api": "api_server_total", "provider": "provider_server_total"}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _path(metrics: dict[str, Any]) -> str:
    """Name the answer path from its calls: no generation at all is exact-match reuse."""
    if metrics.get("trace_kind", "proof_request") != "proof_request":
        return "fresh_" + str(metrics["trace_kind"])
    generations = [
        row for row in metrics.get("phases", ())
        if row.get("service") == "provider" and row.get("phase") == "generation"
    ]
    if not generations:
        return "assessment_no_model"
    roles = {row.get("role") for row in generations}
    if "recipe_semantic_assessment" not in roles:
        return "assessment"
    # Only the two independent semantic calls ran, so the catalog decided this request.
    if roles <= {"recipe_semantic_assessment", "token_answer_qa"} and sum(
        row.get("calls", 1) for row in generations
    ) == 2:
        return "recipe_semantic"
    return "recipe_semantic_then_assessment"


def _stage(row: dict[str, Any]) -> str:
    # API-side billing calls run inside a model role; the role says nothing about their cost.
    if row["service"] == "provider":
        return f"provider/{row['phase']}[{row['role']}]"
    return f"{row['service']}/{row['phase']}"


def _record_trace(samples: dict[tuple[str, str], list[float]], metrics: dict[str, Any]) -> None:
    path = _path(metrics)
    for key in _DERIVED:
        if isinstance(metrics.get(key), int | float):
            samples[path, "trace/" + key].append(float(metrics[key]))
    queue = metrics.get("queue")
    if isinstance(queue, dict) and isinstance(queue.get("queue_wait_ms"), int):
        samples[path, "queue/sqs_wait"].append(float(queue["queue_wait_ms"]))
    notes = metrics.get("notes")
    if isinstance(notes, dict):
        for name, value in notes.items():
            samples[path, "note/" + str(name)].append(float(value))
    per_delivery: dict[str, float] = defaultdict(float)
    server_totals: dict[str, float] = defaultdict(float)
    overhead_total = 0.0
    for row in metrics.get("phases", ()):
        per_delivery[_stage(row)] += row["elapsed_total_ms"]
        if row.get("server_timed_calls"):
            server_totals[_SERVICE_TOTALS[row["service"]]] += row["server_elapsed_total_ms"]
            overhead_total += row["transport_overhead_total_ms"]
    for stage, value in per_delivery.items():
        samples[path, stage].append(value)
    for stage, value in server_totals.items():
        samples[path, "trace/" + stage].append(value)
    if server_totals:
        samples[path, "trace/transport_overhead_total"].append(overhead_total)


def _record_api(samples: dict[tuple[str, str], list[float]], event: dict[str, Any]) -> None:
    name = event["event"]
    if name == "api_route_timing" and isinstance(event.get("duration_ms"), int | float):
        samples["api", "route/" + str(event.get("route"))].append(float(event["duration_ms"]))
        return
    if name == "client_answer_timing":
        for field in ("post_ms", "total_ms"):
            if isinstance(event.get(field), int | float):
                samples["client", "client/" + field].append(float(event[field]))
        return
    fields = {
        "proof_request_dispatch": ("queued_age_ms", "send_ms", "finish_ms"),
        "linked_lean_apply": ("formal_dispatch_ms", "apply_ms"),
        "proof_request_terminal_read": ("terminal_age_ms",),
        "candidate_verification": ("candidate_wait_ms", "verify_ms", "total_ms"),
    }.get(name, ())
    for field in fields:
        if isinstance(event.get(field), int | float):
            samples["api", f"{name}/{field}"].append(float(event[field]))


def _record_handoffs(
    samples: dict[tuple[str, str], list[float]], traces: list[dict[str, Any]],
) -> None:
    """Wall-clock gap from a settled assessment to the linked proof job's first delivery."""
    finished = {
        trace["request_correlation_sha256"]:
            trace["started_unix_ms"] + trace["processor_elapsed_ms"]
        for trace in traces
        if trace.get("trace_kind") == "proof_request"
        and isinstance(trace.get("started_unix_ms"), int)
    }
    linked: dict[str, float] = {}
    for trace in traces:
        request = trace.get("linked_request_correlation_sha256")
        if (
            isinstance(request, str)
            and request in finished
            and isinstance(trace.get("started_unix_ms"), int)
        ):
            linked[request] = min(linked.get(request, math.inf), trace["started_unix_ms"])
    for request, started in linked.items():
        samples["fresh_proof_job", "handoff/assessment_to_job"].append(
            max(0.0, started - finished[request])
        )


def collect(lines: Iterable[str]) -> dict[tuple[str, str], list[float]]:
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    traces: list[dict[str, Any]] = []
    for line in lines:
        lean = _LEAN_STAGE.search(line)
        if lean is not None:
            samples["verifier", "lean/" + lean.group(1)].append(float(lean.group(2)))
            continue
        start = line.find("{")
        if start < 0 or '"event"' not in line:
            continue
        try:
            event = json.loads(line[start:])
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "proof_request_latency" and isinstance(event.get("metrics"), dict):
            _record_trace(samples, event["metrics"])
            traces.append(event["metrics"])
        elif isinstance(event.get("event"), str):
            _record_api(samples, event)
    _record_handoffs(samples, traces)
    return samples


def rows(samples: dict[tuple[str, str], list[float]]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "stage": stage,
            "n": len(values),
            "p50_ms": round(percentile(values, 0.5), 1),
            "p95_ms": round(percentile(values, 0.95), 1),
            "max_ms": round(max(values), 1),
        }
        for (path, stage), values in sorted(samples.items())
    ]


def _print_table(report: list[dict[str, Any]], stream: TextIO) -> None:
    current = None
    for row in report:
        if row["path"] != current:
            current = row["path"]
            stream.write(
                f"\n{current}\n{'stage':<52}{'n':>5}{'p50_ms':>11}{'p95_ms':>11}{'max_ms':>11}\n"
            )
        stream.write(
            f"{row['stage']:<52}{row['n']:>5}{row['p50_ms']:>11.1f}"
            f"{row['p95_ms']:>11.1f}{row['max_ms']:>11.1f}\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+", help="log files, or - for standard input")
    parser.add_argument("--json", action="store_true", help="print rows as JSON")
    args = parser.parse_args(argv)
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    for name in args.logs:
        if name == "-":
            collected = collect(sys.stdin)
        else:
            with open(name, encoding="utf-8", errors="replace") as stream:
                collected = collect(stream)
        for key, values in collected.items():
            samples[key].extend(values)
    report = rows(samples)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_table(report, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
