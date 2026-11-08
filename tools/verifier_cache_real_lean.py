# ruff: noqa: E501
"""Drive the isolated verifier HTTP server and its result cache with the REAL pinned Lean.

Run from the repository root (about 10-15 minutes, one Lean process at a time):

    uv run --extra dev python tools/verifier_cache_real_lean.py --out tools/verifier_cache_real_lean_results.json

What runs for real: the HTTP server (TLS 1.3 mTLS, in process), the result cache, and the
production ``LeanVerifier`` (source policy, comment/string stripping, the compile with
``--threads=1``, the compiled-module axiom audit, the diagnostics parser, the supervisor and
the timeout).  What is different from production: ``lake`` is never run.  The verifier is built
without a project directory, so it execs the pinned ``lean`` binary directly, and this tool
adds ``LEAN_PATH`` (the built Mathlib packages, read only) to the child environment by wrapping
``pals_agent.lean._run_limited_process``.  This file is the only place that does that.

Safety: this never runs ``lake``, never points a ``.lake/packages`` anywhere, and never writes
under the Mathlib directory (Lean writes only inside a scratch directory it owns).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import http.client
import json
import logging
import platform
import socket
import ssl
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import pals_agent.lean as lean_module  # noqa: E402
from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.lean_templates import (  # noqa: E402
    render_x_squared_epsilon_delta,
    x_squared_worker_bindings,
)
from pals_agent.lean_verifier import result_cache as result_cache_module  # noqa: E402
from pals_agent.lean_verifier.http_server import (  # noqa: E402
    IsolatedVerifierHttpSettings,
    VerifierDeploymentBinding,
    _fresh_outcome,
    create_server,
)
from pals_agent.lean_verifier.result_cache import (  # noqa: E402
    SOURCE_HEADER,
    ResultCacheMode,
    VerifierResultCache,
    build_result_cache,
    result_cache_mode,
)
from pals_agent.models import VerificationResult  # noqa: E402
from tests.unit.test_isolated_verifier_http_server import (  # noqa: E402
    _DEPLOYMENT_SHA,
    _RELEASE_ID,
    _admission_context,
    _create_certificates,
    _headers,
    _spki_sha256,
)
from tests.unit.test_recipe_elaboration_lean import (  # noqa: E402
    LAKE_PACKAGES,
    PINNED,
    mathlib_environment,
)

CACHE_LOGGER_NAME = result_cache_module._LOGGER.name  # noqa: SLF001
PORT = 18_117
LEAN_VERSION = "leanprover/lean4:v4.32.0-rc1"
NORMAL_TIMEOUT_SECONDS = 300.0
TINY_TIMEOUT_SECONDS = 0.01
SOURCE_VARIABLES = ("x", "t", "y", "s")
FIRST_COMPILE_REPEATS = 3  # repeat compiles per source in scenario A (after the first)
HITS_PER_SOURCE = 8  # scenario B: 4 x 8 = 32 cache hits


def available() -> bool:
    return PINNED.exists() and mathlib_environment() is not None


# --- the real-Lean verifier ---------------------------------------------------------------------


class RealLeanAdapter:
    """The server's verifier port: the production ``LeanVerifier`` on the pinned Lean, no lake.

    ``mode`` selects, per call, ``normal``, ``tiny_timeout`` (a 10 ms deadline, so Lean is
    interrupted) or ``broken_mathlib`` (Mathlib is left off ``LEAN_PATH``, so Lean really rejects
    ``import Mathlib``).  Every call is counted and timed.
    """

    def __init__(self, scratch_dir: Path) -> None:
        environment = mathlib_environment()
        assert environment is not None
        self._lean_path = environment["LEAN_PATH"]
        toolchain = str(PINNED.parent.parent / "lib/lean")
        self._core_only_path = toolchain
        self.normal = LeanVerifier(
            lean_binary=str(PINNED),
            timeout_seconds=NORMAL_TIMEOUT_SECONDS,
            scratch_dir=scratch_dir,
        )
        self.tiny = dataclasses.replace(self.normal, timeout_seconds=TINY_TIMEOUT_SECONDS)
        self.mode = "normal"
        self.calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._original = lean_module._run_limited_process  # noqa: SLF001
        lean_module._run_limited_process = self._run_with_lean_path  # noqa: SLF001

    def close(self) -> None:
        lean_module._run_limited_process = self._original  # noqa: SLF001

    def _run_with_lean_path(self, command: list[str], **kwargs: Any) -> Any:
        path = self._core_only_path if self.mode == "broken_mathlib" else self._lean_path
        environment = {**kwargs.pop("environment"), "LEAN_PATH": path}
        return self._original(command, environment=environment, **kwargs)

    def verify(self, lean_code: str) -> VerificationResult:
        verifier = self.tiny if self.mode == "tiny_timeout" else self.normal
        started = time.monotonic()
        result = verifier.verify(lean_code)
        elapsed = time.monotonic() - started
        with self._lock:
            self.calls.append(
                {
                    "source_sha256": hashlib.sha256(lean_code.encode("utf-8")).hexdigest()[:12],
                    "mode": self.mode,
                    "seconds": round(elapsed, 3),
                    "success": result.success,
                    "codes": [d.code for d in result.diagnostics],
                }
            )
        return result


# --- server, client, log capture ----------------------------------------------------------------


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def tls_material() -> Iterator[tuple[ssl.SSLContext, ssl.SSLContext, str]]:
    with tempfile.TemporaryDirectory(prefix="pals-mtls-", dir="/private/tmp") as directory:
        root = Path(directory)
        _create_certificates(root)
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.minimum_version = ssl.TLSVersion.TLSv1_3
        server.verify_mode = ssl.CERT_REQUIRED
        server.load_verify_locations(cafile=root / "ca.pem")
        server.load_cert_chain(root / "server.pem", root / "server.key")
        client = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=root / "ca.pem")
        client.minimum_version = ssl.TLSVersion.TLSv1_3
        client.load_cert_chain(root / "client.pem", root / "client.key")
        yield server, client, _spki_sha256((root / "client.der").read_bytes())


@contextmanager
def serving(
    tls: tuple[ssl.SSLContext, ssl.SSLContext, str],
    verifier: Any,
    cache: VerifierResultCache | None,
) -> Iterator[Any]:
    server_context, _, client_spki = tls
    settings = IsolatedVerifierHttpSettings(
        bind_host="127.0.0.1",
        binding=VerifierDeploymentBinding(
            release_id=_RELEASE_ID,
            deployment_binding_sha256=_DEPLOYMENT_SHA,
            verifier_image_digest="sha256:" + "b" * 64,
            verifier_toolchain_sha256="c" * 64,
        ),
        ssl_context=server_context,
        reconciler_client_spki_sha256=client_spki,
        reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
        recipe_admission_context=_admission_context(),
        max_concurrent_compiles=1,
    )
    server = create_server(settings, verifier=verifier, result_cache=cache)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _exchange(client: ssl.SSLContext, raw_request: bytes) -> tuple[int, bytes, http.client.HTTPResponse]:
    # A compile takes tens of seconds, so unlike the unit-test helper the socket timeout is long.
    with (
        socket.create_connection(("127.0.0.1", PORT), timeout=900) as raw,
        client.wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(raw_request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        content = response.read()
    return response.status, content, response


def build_cache(
    mode: ResultCacheMode, verifier: LeanVerifier, allow_list: tuple[str, ...] | None = None
) -> VerifierResultCache:
    cache = build_result_cache(
        mode=mode,
        verifier=verifier,
        lean_version=LEAN_VERSION,
        lean_toolchain_file_sha256=hashlib.sha256(
            (REPOSITORY_ROOT / "lean-workspace/lean-toolchain").read_bytes()
        ).hexdigest(),
        lake_manifest_sha256=hashlib.sha256(
            (REPOSITORY_ROOT / "lean-workspace/lake-manifest.json").read_bytes()
        ).hexdigest(),
        verifier_toolchain_sha256="c" * 64,
        verifier_image_digest="sha256:" + "b" * 64,
        allow_list=allow_list,
    )
    assert cache is not None
    return cache


class Session:
    """One request log: wall time, status, source header, new cache counters and log lines."""

    def __init__(
        self,
        client: ssl.SSLContext,
        adapter: RealLeanAdapter,
        cache: VerifierResultCache | None,
        records: _Records,
    ) -> None:
        self.client = client
        self.adapter = adapter
        self.cache = cache
        self.records = records
        self.rows: list[dict[str, Any]] = []

    def post(self, label: str, source: str, *, job: str | None = None) -> dict[str, Any]:
        job_id = job or f"real-lean-{len(self.rows)}"
        body = json.dumps(
            {
                "lean_code": source,
                "proof_job_id": job_id,
                "result_artifact_uri": f"s3://bucket/proof-jobs/{job_id}/result.lean",
                "schema_version": "pals.isolated-verifier-request.v1",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        raw_request = (
            b"POST /v1/verify HTTP/1.1\r\n"
            + _headers()
            + b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        before = self.cache.snapshot() if self.cache is not None else {}
        log_start = len(self.records.records)
        lean_calls_before = len(self.adapter.calls)
        started = time.monotonic()
        status, content, response = _exchange(self.client, raw_request)
        elapsed = time.monotonic() - started
        payload = json.loads(content)
        after = self.cache.snapshot() if self.cache is not None else {}
        delta = {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}
        new_records = self.records.records[log_start:]
        results = [
            (r.levelname, r.getMessage().split("result=")[1].split()[0])
            for r in new_records
            if "result=" in r.getMessage()
        ]
        row: dict[str, Any] = {
            "label": label,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()[:12],
            "seconds": round(elapsed, 4),
            "status": status,
            "source_header": response.getheader(SOURCE_HEADER),
            "success": status == 200 and payload.get("verification_succeeded") is True,
            "lean_calls": len(self.adapter.calls) - lean_calls_before,
            "counter_delta": delta,
            "log_results": [f"{level}:{name}" for level, name in results],
            "serving_blocked": self.cache.serving_blocked if self.cache is not None else None,
            "error_code": payload.get("error_code"),
            "echoed_job": payload.get("proof_job_id") == job_id,
        }
        self.rows.append(row)
        print(
            f"  {label:<34} {elapsed:8.3f}s  {status}  header={row['source_header']}  "
            f"lean_calls={row['lean_calls']}  {row['log_results']}  {delta}",
            flush=True,
        )
        return row

    def ready_baseline(self, samples: int = 20) -> list[float]:
        times = []
        for _ in range(samples):
            started = time.monotonic()
            status, _, _ = _exchange(self.client, b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")
            assert status == 200
            times.append(time.monotonic() - started)
        return times


# --- sources ------------------------------------------------------------------------------------


def allow_listed_sources() -> dict[str, str]:
    by_letter = {b.variable: render_x_squared_epsilon_delta(b) for b in x_squared_worker_bindings()}
    return {letter: by_letter[letter] for letter in SOURCE_VARIABLES}


def not_allow_listed(source: str) -> str:
    return source + "\n-- one extra comment: this byte string is not in the allow-list\n"


def wrong_lemma(source: str) -> str:
    wrong = source.replace(
        "exact lt_min (by positivity) (div_pos hε hden)", "exact lt_min (by positivity) hε"
    )
    assert wrong != source
    return wrong


def sorry_proof(source: str) -> str:
    head = source.split(":= by\n")[0]
    return head + ":= by\n  sorry\n"


# --- scenarios ----------------------------------------------------------------------------------


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def __call__(self, name: str, ok: bool, detail: object = "") -> None:
        self.items.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)


def stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "p50": statistics.median(values),
        "p95": p95,
        "max": max(values),
    }


def run_all(scratch: Path) -> dict[str, Any]:
    sources = allow_listed_sources()
    checks = Checks()
    out: dict[str, Any] = {"scenarios": {}}
    handler = _Records()
    logger = logging.getLogger(CACHE_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    adapter = RealLeanAdapter(scratch)
    try:
        with tls_material() as tls:
            out["scenarios"]["A"] = scenario_a(tls, adapter, handler, sources, checks)
            out["scenarios"]["B"] = scenario_b(tls, adapter, handler, sources, checks)
            out["scenarios"]["C"] = scenario_c(tls, adapter, handler, sources, checks)
            out["scenarios"]["D"] = scenario_d(tls, adapter, handler, sources, checks)
    finally:
        adapter.close()
        logger.removeHandler(handler)
    out["checks"] = checks.items
    return out


def scenario_a(
    tls: Any, adapter: RealLeanAdapter, handler: _Records, sources: dict[str, str], checks: Checks
) -> dict[str, Any]:
    print("A. SHADOW=true ENABLED=false: compile each allow-list source 1+3 times", flush=True)
    cache = build_cache(result_cache_mode(shadow=True, enabled=False), adapter.normal)
    with serving(tls, adapter, cache):
        session = Session(tls[1], adapter, cache, handler)
        for letter, source in sources.items():
            for attempt in range(1 + FIRST_COMPILE_REPEATS):
                session.post(f"A {letter} #{attempt + 1}", source)
        snapshot = cache.snapshot()
    rows = session.rows
    checks("A: every response is 200 with header compile",
           all(r["status"] == 200 and r["source_header"] == "compile" for r in rows))
    checks("A: every request invoked Lean exactly once", all(r["lean_calls"] == 1 for r in rows))
    firsts = [r for r in rows if r["label"].endswith("#1")]
    repeats = [r for r in rows if not r["label"].endswith("#1")]
    checks("A: first request per source stores (no shadow_match yet)",
           all("INFO:stored" in r["log_results"] and "INFO:shadow_match" not in r["log_results"]
               for r in firsts))
    checks("A: every repeat reports shadow_match",
           all("INFO:shadow_match" in r["log_results"] for r in repeats), len(repeats))
    checks("A: counters stored=4 shadow_match=12 mismatch=0 inconclusive=0",
           snapshot.get("stored") == 4 and snapshot.get("shadow_match") == 4 * FIRST_COMPILE_REPEATS
           and snapshot.get("shadow_mismatch", 0) == 0
           and snapshot.get("shadow_inconclusive", 0) == 0, snapshot)
    return {"rows": rows, "snapshot": snapshot}


def scenario_b(
    tls: Any, adapter: RealLeanAdapter, handler: _Records, sources: dict[str, str], checks: Checks
) -> dict[str, Any]:
    print("B. SHADOW=true ENABLED=true: compile once, then serve from the cache", flush=True)
    cache = build_cache(result_cache_mode(shadow=True, enabled=True), adapter.normal)
    with serving(tls, adapter, cache):
        session = Session(tls[1], adapter, cache, handler)
        compile_seconds: dict[str, float] = {}
        for letter, source in sources.items():
            row = session.post(f"B {letter} first", source)
            compile_seconds[letter] = float(row["seconds"])
            checks(f"B: {letter} first request compiled", row["source_header"] == "compile"
                   and row["lean_calls"] == 1 and row["success"])
        hit_rows = []
        calls_before_hits = len(adapter.calls)
        for round_index in range(HITS_PER_SOURCE):
            for letter, source in sources.items():
                hit_rows.append(
                    session.post(f"B {letter} hit {round_index + 1}", source,
                                 job=f"hit-{letter}-{round_index}")
                )
        hits = [float(r["seconds"]) for r in hit_rows]
        checks("B: all hits answered 200 with header cache", all(
            r["status"] == 200 and r["source_header"] == "cache" and r["success"] for r in hit_rows),
            len(hit_rows))
        checks("B: Lean was NOT invoked during the hits (adapter counter)",
               len(adapter.calls) == calls_before_hits, len(adapter.calls) - calls_before_hits)
        slowest_hit = max(hits)
        fastest_compile = min(compile_seconds.values())
        checks("B: slowest hit is far faster than the fastest compile (timing)",
               slowest_hit < fastest_compile / 20, f"{slowest_hit:.3f}s vs {fastest_compile:.3f}s")
        checks("B: hit responses echo the request's own job id", all(r["echoed_job"] for r in hit_rows))
        ready = session.ready_baseline()
        # Not in the allow-list: compiled every time, never from the cache.
        outside = not_allow_listed(sources["x"])
        out_rows = [session.post(f"B x+comment #{i + 1}", outside) for i in range(2)]
        checks("B: a non-allow-list source compiles every time and never returns cache",
               all(r["source_header"] == "compile" and r["lean_calls"] == 1 and r["success"]
                   and r["counter_delta"].get("ineligible") == 1 for r in out_rows))
        # Failing sources: not stored, the normal 422 each time.
        bad = wrong_lemma(sources["x"])
        bad_rows = [session.post(f"B x wrong-lemma #{i + 1}", bad) for i in range(2)]
        sorry_rows = [session.post(f"B x sorry #{i + 1}", sorry_proof(sources["x"])) for i in range(2)]
        checks("B: a failing source returns the normal 422 with header compile every time",
               all(r["status"] == 422 and r["source_header"] == "compile" and not r["success"]
                   for r in bad_rows + sorry_rows))
        checks("B: every failing request went through the verifier (sorry is refused by its source "
               "policy before any Lean process, the wrong lemma is refused by Lean)",
               all(r["lean_calls"] == 1 for r in bad_rows + sorry_rows)
               and all("lean.disallowed_placeholder" in c["codes"]
                       for c in adapter.calls[-2:])
               and all("lean.disallowed_placeholder" not in c["codes"]
                       for c in adapter.calls[-4:-2]))
        snapshot = cache.snapshot()
        checks("B: the cache holds exactly the 4 allow-list successes", snapshot["entries"] == 4, snapshot)
    # A failing source that IS allow-listed: the failure is never stored.
    print("B2. an allow-listed source that Lean rejects", flush=True)
    failing_cache = build_cache(
        result_cache_mode(shadow=True, enabled=True), adapter.normal, allow_list=(bad,)
    )
    with serving(tls, adapter, failing_cache):
        session2 = Session(tls[1], adapter, failing_cache, handler)
        failing_rows = [session2.post(f"B2 allow-listed failing #{i + 1}", bad) for i in range(2)]
        failing_snapshot = failing_cache.snapshot()
    checks("B2: an allow-listed failing source is never stored and never served",
           all(r["status"] == 422 and r["source_header"] == "compile" and r["lean_calls"] == 1
               for r in failing_rows)
           and failing_snapshot.get("failure_not_stored") == 2 and failing_snapshot["entries"] == 0,
           failing_snapshot)
    return {
        "rows": session.rows + session2.rows,
        "snapshot": snapshot,
        "failing_allow_listed_snapshot": failing_snapshot,
        "hit_seconds": hits,
        "hit_stats": stats(hits),
        "ready_baseline_seconds": ready,
        "ready_baseline_stats": stats(ready),
        "first_compile_seconds": compile_seconds,
    }


def scenario_c(
    tls: Any, adapter: RealLeanAdapter, handler: _Records, sources: dict[str, str], checks: Checks
) -> dict[str, Any]:
    print("C. a timeout is inconclusive, not a mismatch", flush=True)
    x, t = sources["x"], sources["t"]
    cache = build_cache(result_cache_mode(shadow=True, enabled=False), adapter.normal)
    with serving(tls, adapter, cache):
        session = Session(tls[1], adapter, cache, handler)
        session.post("C x normal (stores)", x)
        adapter.mode = "tiny_timeout"
        stored_timeout = session.post("C x 10ms timeout (stored)", x)
        fresh_timeout = session.post("C t 10ms timeout (not stored)", t)
        adapter.mode = "normal"
        after_x = session.post("C x normal again", x)
        after_t = session.post("C t normal (stores)", t)
        snapshot = cache.snapshot()
    checks("C: timeout on a stored source -> 504, header compile, shadow_inconclusive at WARNING",
           stored_timeout["status"] == 504 and stored_timeout["source_header"] == "compile"
           and stored_timeout["log_results"] == ["INFO:eligible_compile", "WARNING:shadow_inconclusive"],
           stored_timeout["log_results"])
    checks("C: the timeout is not counted as shadow_mismatch and does not block",
           snapshot.get("shadow_mismatch", 0) == 0 and not cache.serving_blocked
           and snapshot.get("shadow_inconclusive") == 1, snapshot)
    checks("C: timeout on a source with no stored verdict -> inconclusive_not_stored",
           fresh_timeout["status"] == 504 and snapshot.get("inconclusive_not_stored") == 1)
    checks("C: later normal requests succeed (shadow_match, then stored)",
           after_x["status"] == 200 and "INFO:shadow_match" in after_x["log_results"]
           and after_t["status"] == 200 and "INFO:stored" in after_t["log_results"])
    print("C2. same, then SERVE mode serves after a timeout", flush=True)
    serve_cache = build_cache(result_cache_mode(shadow=True, enabled=True), adapter.normal)
    with serving(tls, adapter, serve_cache):
        session2 = Session(tls[1], adapter, serve_cache, handler)
        adapter.mode = "tiny_timeout"
        first = session2.post("C2 t 10ms timeout", t)
        adapter.mode = "normal"
        second = session2.post("C2 t normal (stores)", t)
        third = session2.post("C2 t (served)", t)
    checks("C2: after a timeout, serving is not blocked: compile stores, next is a cache hit",
           first["status"] == 504 and second["source_header"] == "compile"
           and third["source_header"] == "cache" and third["lean_calls"] == 0
           and not serve_cache.serving_blocked)
    return {"rows": session.rows + session2.rows, "snapshot": snapshot,
            "serve_snapshot": serve_cache.snapshot()}


def scenario_d(
    tls: Any, adapter: RealLeanAdapter, handler: _Records, sources: dict[str, str], checks: Checks
) -> dict[str, Any]:
    print("D. a mismatch blocks serving", flush=True)
    x, t = sources["x"], sources["t"]
    # D1: a real rejection by Lean of a stored allow-list source.  Leaving Mathlib off LEAN_PATH
    # makes the real compiler reject ``import Mathlib`` (a fault injection, not a tampered verdict).
    cache = build_cache(result_cache_mode(shadow=True, enabled=False), adapter.normal)
    with serving(tls, adapter, cache):
        session = Session(tls[1], adapter, cache, handler)
        session.post("D1 x normal (stores)", x)
        adapter.mode = "broken_mathlib"
        mismatch = session.post("D1 x Lean rejects (mismatch)", x)
        adapter.mode = "normal"
        after = session.post("D1 x normal after mismatch", x)
        snapshot = cache.snapshot()
    error_records = [r for r in handler.records if r.levelno == logging.ERROR]
    checks("D1: Lean's rejection of a stored source -> 422 compile, shadow_mismatch logged at ERROR",
           mismatch["status"] == 422 and mismatch["source_header"] == "compile"
           and "ERROR:shadow_mismatch" in mismatch["log_results"], mismatch["log_results"])
    checks("D1: counter shadow_mismatch=1 and serving is blocked for the rest of the process",
           snapshot.get("shadow_mismatch") == 1 and cache.serving_blocked
           and after["serving_blocked"] is True, snapshot)
    # D2: the same state in a SERVE cache.  Two requests overlap, the first stores a real
    # success, the second carries a real rejection (the in-process tampering the unit tests use).
    ok_result = adapter.verify(x)
    adapter.mode = "broken_mathlib"
    bad_result = adapter.verify(x)
    adapter.mode = "normal"
    serve_cache = build_cache(result_cache_mode(shadow=True, enabled=True), adapter.normal)
    decision_a, decision_b = serve_cache.begin(x), serve_cache.begin(x)
    serve_cache.finish_compiled(decision_a, _fresh_outcome(ok_result))
    serve_cache.finish_compiled(decision_b, _fresh_outcome(bad_result))
    checks("D2: tampered state: stored success + later real rejection => blocked",
           serve_cache.serving_blocked and serve_cache.snapshot().get("shadow_mismatch") == 1,
           serve_cache.snapshot())
    with serving(tls, adapter, serve_cache):
        session2 = Session(tls[1], adapter, serve_cache, handler)
        blocked_rows = [session2.post(f"D2 x with ENABLED, blocked #{i + 1}", x) for i in range(2)]
        other = session2.post("D2 t with ENABLED, blocked", t)
        other_again = session2.post("D2 t with ENABLED, blocked again", t)
        serve_snapshot = serve_cache.snapshot()
    checks("D2: with ENABLED and a mismatch seen, no request is served from the cache",
           all(r["source_header"] == "compile" and r["lean_calls"] == 1 and r["success"]
               for r in blocked_rows + [other, other_again]), serve_snapshot)
    checks("D2: blocked_by_mismatch counted", serve_snapshot.get("blocked_by_mismatch", 0) >= 2,
           serve_snapshot)
    return {"rows": session.rows + session2.rows, "snapshot": snapshot,
            "serve_snapshot": serve_snapshot, "error_log_lines": len(error_records)}


# --- summary ------------------------------------------------------------------------------------


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    a_rows = result["scenarios"]["A"]["rows"]
    b = result["scenarios"]["B"]
    table = []
    for index, letter in enumerate(SOURCE_VARIABLES):
        mine = [r for r in a_rows if r["label"].startswith(f"A {letter} ")]
        repeats = [float(r["seconds"]) for r in mine[1:]]
        table.append({
            "variable": letter,
            "process_order": index + 1,
            "first_compile_s": float(mine[0]["seconds"]),
            "repeat_compile_s": {
                "n": len(repeats), "min": min(repeats),
                "median": statistics.median(repeats), "max": max(repeats),
            },
        })
    hit = b["hit_stats"]
    result["table"] = table
    result["cache_hit_ms"] = {k: round(v * 1000, 2) if k != "n" else v for k, v in hit.items()}
    result["ready_baseline_ms"] = {
        k: round(v * 1000, 2) if k != "n" else v for k, v in b["ready_baseline_stats"].items()
    }
    return result


def environment_report() -> dict[str, object]:
    version = subprocess.run(
        [str(PINNED), "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "date": time.strftime("%Y-%m-%d"),
        "lean": version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "mathlib_packages_dir": str(LAKE_PACKAGES),
        "lean_binary": str(PINNED),
        "normal_timeout_seconds": NORMAL_TIMEOUT_SECONDS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not available():
        print("pinned Lean v4.32.0-rc1 or its built Mathlib is missing", file=sys.stderr)
        return 2
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pals-real-lean-scratch-", dir="/private/tmp") as scratch:
        result = run_all(Path(scratch))
    result["environment"] = environment_report()
    result["total_seconds"] = round(time.monotonic() - started, 1)
    summarize(result)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    failed = [c for c in result["checks"] if not c["ok"]]
    print(f"\n{len(result['checks']) - len(failed)}/{len(result['checks'])} checks passed;"
          f" total {result['total_seconds']}s; wrote {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    with contextlib.suppress(BrokenPipeError):
        sys.exit(main())
