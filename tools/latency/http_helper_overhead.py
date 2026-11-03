"""Split the per-call cost of the worker's fresh-process HTTP helper.

Run inside a worker container, so it uses the image's interpreter and network:

    docker exec -i <worker> python - --api http://api:8000/healthz < http_helper_overhead.py

Compares an empty child interpreter, the helper's real transport, a fresh in-process
connection and one reused connection against the same URL. Sends one GET per sample,
no prompt, and uses no model tokens. Prints medians only.
"""

from __future__ import annotations

import argparse
import http.client
import json
import ssl
import statistics
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import urlopen

from pals_agent.lightweight_http_transport import _BOOTSTRAP, LightweightHttpTransport


def _median_ms(work, samples: int) -> float:
    values = []
    for _ in range(samples):
        started = time.monotonic()
        work()
        values.append((time.monotonic() - started) * 1000)
    return round(statistics.median(values), 1)


def _interpreter_start() -> None:
    # Only the child's import of the helper; stdin is empty, so it exits with its own error.
    subprocess.run(
        [sys.executable, "-I", "-B", "-c", _BOOTSTRAP],
        stdin=subprocess.DEVNULL, capture_output=True, check=False,
    )


def _measure(url: str, samples: int) -> dict[str, float]:
    transport = LightweightHttpTransport()

    def helper() -> None:
        transport.request(
            method="GET", url=url, headers={}, body=None, timeout_seconds=30.0,
        )

    def fresh() -> None:
        try:
            with urlopen(url, timeout=30) as response:  # noqa: S310 -- operator-supplied URL.
                response.read()
        except HTTPError as error:
            error.read()

    parts = urlsplit(url)
    if parts.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            parts.hostname, parts.port, context=ssl.create_default_context(), timeout=30,
        )
    else:
        connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=30)

    def reused() -> None:
        connection.request("GET", parts.path or "/")
        connection.getresponse().read()

    result = {
        "helper_ms": _median_ms(helper, samples),
        "fresh_connection_ms": _median_ms(fresh, samples),
    }
    # Warm up only now: a server may close a connection left idle by the samples above.
    reused()
    result["reused_connection_ms"] = _median_ms(reused, samples)
    connection.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--api", required=True, help="URL on the PALS API, e.g. /healthz")
    parser.add_argument("--provider", help="URL on the model provider; an error status is fine")
    args = parser.parse_args()
    report: dict[str, object] = {
        "samples": args.samples,
        "interpreter_start_ms": _median_ms(_interpreter_start, args.samples),
        "api": _measure(args.api, args.samples),
    }
    if args.provider:
        try:
            report["provider"] = _measure(args.provider, args.samples)
        except OSError as error:
            report["provider_error"] = type(error).__name__
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
