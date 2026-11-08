"""Measure how long the worker takes to notice that a Lean verification finished.

Runs the worker's real candidate wait (`SqsProofWorker._wait_for_candidate_reconciliation`)
and its real fresh-process HTTP transport against a local stdlib HTTP server. The server
reports a `compiling` proof job until a random moment, then a settled one, and records that
moment. The lag is the time from that moment to the wait returning. There is no Lean, DB,
model or network involved, so the figures isolate the polling schedule and the per-call
process cost. TLS and API processing time of a real deployment are not included.

    python -m tools.latency.poll_lag --trials 20 --min-seconds 2 --max-seconds 6
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, cast

from pals_agent.api_client import PalsApiClient
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker

PROOF_JOB_ID = "poll-lag-job"


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.flip_at = float("inf")
        self.flipped_at: float | None = None
        self.requests = 0

    def arm(self, flip_at: float) -> None:
        with self.lock:
            self.flip_at = flip_at
            self.flipped_at = None
            self.requests = 0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            self.requests += 1
            if time.monotonic() >= self.flip_at:
                self.flipped_at = self.flipped_at or self.flip_at
                return {"state": "verified", "verification_candidate_state": "verified"}
            return {"state": "compiling", "verification_candidate_state": "compiling"}


def _handler(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 -- stdlib hook name.
            body = json.dumps(state.snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return Handler


def measure(trials: int, low: float, high: float) -> dict[str, Any]:
    state = _State()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = PalsApiClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}", worker_secret="x" * 32,
    )
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace()), api_client=cast(Any, client),
        pipeline=None, explainer=None,
    )
    rng = random.Random(20261108)
    lags: list[float] = []
    polls: list[int] = []
    try:
        for _ in range(trials):
            state.arm(time.monotonic() + rng.uniform(low, high))
            settled = worker._wait_for_candidate_reconciliation(
                proof_job_id=PROOF_JOB_ID, extend_visibility=lambda _seconds: None,
                refresh_visibility=False,
            )
            observed = time.monotonic()
            assert settled is not None and state.flipped_at is not None
            lags.append((observed - state.flipped_at) * 1000)
            polls.append(state.requests)
    finally:
        server.shutdown()
    ordered = sorted(lags)
    return {
        "trials": trials,
        "lag_ms_median": round(statistics.median(ordered), 1),
        "lag_ms_p95": round(ordered[max(0, int(0.95 * len(ordered) + 0.5) - 1)], 1),
        "lag_ms_max": round(ordered[-1], 1),
        "api_calls_per_wait_median": statistics.median(polls),
        "api_calls_per_second_median": round(statistics.median(polls) / ((low + high) / 2), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--min-seconds", type=float, default=2.0)
    parser.add_argument("--max-seconds", type=float, default=6.0)
    arguments = parser.parse_args()
    print(json.dumps(measure(arguments.trials, arguments.min_seconds, arguments.max_seconds)))


if __name__ == "__main__":
    main()
