from __future__ import annotations

import json
import multiprocessing
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, cast

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.http_transport import (
    HardDeadlineHttpTransport,
    HttpResponseTooLarge,
)
from pals_agent.ollama import OllamaClient, OllamaError
from pals_agent.openai import OpenAIError, OpenAIResponsesClient


class _DaemonHttpServer(ThreadingHTTPServer):
    daemon_threads = True


class _SlowDripHandler(BaseHTTPRequestHandler):
    payloads: ClassVar[dict[str, bytes]] = {
        "/responses": json.dumps({"output_text": "generated" * 40}).encode(),
        "/api/generate": json.dumps({"response": "generated" * 40}).encode(),
        "/v1/internal/proof-jobs/proof-1/worker-input": json.dumps(
            {"state": "verified", "padding": "x" * 400}
        ).encode(),
    }

    def do_GET(self) -> None:  # noqa: N802
        self._send_slow_body()

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length:
            self.rfile.read(content_length)
        self._send_slow_body()

    def _send_slow_body(self) -> None:
        payload = self.payloads.get(self.path)
        if payload is None:
            payload = b"x" * (
                1_048_576 if self.path == "/exact-limit" else 1_048_577
            )
        self.send_response(400 if self.path == "/too-large-error" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        chunk_size = max(1, (len(payload) + 23) // 24)
        try:
            for offset in range(0, len(payload), chunk_size):
                self.wfile.write(payload[offset : offset + chunk_size])
                self.wfile.flush()
                time.sleep(0.025)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)


class _SlowHeaderHandler(_SlowDripHandler):
    def _send_slow_body(self) -> None:
        time.sleep(0.50)
        super()._send_slow_body()


class _RedirectHandler(BaseHTTPRequestHandler):
    follow_up_requests = 0

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/follow-up")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"redirect":true}')
            return
        type(self).follow_up_requests += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)


@contextmanager
def _slow_server(
    handler: type[BaseHTTPRequestHandler] = _SlowDripHandler,
) -> Iterator[str]:
    server = _DaemonHttpServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = cast(tuple[str, int], server.server_address)
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.mark.parametrize("client_kind", ["openai", "ollama", "pals-api"])
@pytest.mark.parametrize("response_phase", ["headers", "body"])
def test_pae_015_slow_drip_cannot_extend_total_http_wall_deadline(
    client_kind: str,
    response_phase: str,
) -> None:
    existing_children = {child.pid for child in multiprocessing.active_children()}
    handler = _SlowHeaderHandler if response_phase == "headers" else _SlowDripHandler
    with _slow_server(handler) as base_url:
        started = time.monotonic()
        if client_kind == "openai":
            openai_client = OpenAIResponsesClient(
                api_key="test",
                base_url=base_url,
                timeout_seconds=0.10,
            )
            with pytest.raises(OpenAIError):
                openai_client.generate(model="model", prompt="prompt")
        elif client_kind == "ollama":
            ollama_client = OllamaClient(host=base_url, timeout_seconds=0.10)
            with pytest.raises(OllamaError):
                ollama_client.generate(model="model", prompt="prompt")
        else:
            api_client = PalsApiClient(
                base_url=base_url,
                worker_secret="PRIVATE-SECRET",
                timeout_seconds=0.10,
            )
            with pytest.raises(PalsApiError):
                api_client.get_proof_job("proof-1")
        elapsed = time.monotonic() - started
        remaining_children = {child.pid for child in multiprocessing.active_children()}

    assert elapsed < 0.40
    assert remaining_children <= existing_children


def test_pae_015_http_body_limit_accepts_exact_bytes_and_rejects_one_more() -> None:
    with _slow_server() as base_url:
        transport = HardDeadlineHttpTransport()
        exact = transport.request(
            method="GET",
            url=base_url + "/exact-limit",
            headers={},
            body=None,
            timeout_seconds=2,
        )
        with pytest.raises(HttpResponseTooLarge):
            transport.request(
                method="GET",
                url=base_url + "/too-large",
                headers={},
                body=None,
                timeout_seconds=2,
            )
        with pytest.raises(HttpResponseTooLarge):
            transport.request(
                method="GET",
                url=base_url + "/too-large-error",
                headers={},
                body=None,
                timeout_seconds=2,
            )

    assert exact.status_code == 200
    assert len(exact.body) == 1_048_576


def test_private_candidate_transport_never_follows_redirects_and_keeps_headers() -> None:
    _RedirectHandler.follow_up_requests = 0
    with _slow_server(_RedirectHandler) as base_url:
        response = HardDeadlineHttpTransport().request(
            method="GET",
            url=base_url + "/redirect",
            headers={},
            body=None,
            timeout_seconds=2,
        )

    assert response.status_code == 302
    assert response.body == b'{"redirect":true}'
    assert ("Content-Type", "application/json") in response.headers
    assert _RedirectHandler.follow_up_requests == 0


def test_private_candidate_transport_ignores_environment_proxy_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    with _slow_server() as base_url:
        response = HardDeadlineHttpTransport().request(
            method="GET",
            url=base_url + "/responses",
            headers={},
            body=None,
            timeout_seconds=2,
        )

    assert response.status_code == 200
