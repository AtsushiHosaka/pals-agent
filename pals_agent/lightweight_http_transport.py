"""Optional fresh-process HTTP transport; no CLI reconstruction or process pool.

The unchanged owning HTTP helper retains TLS verification, proxy/redirect
policy, and the caller's response cap (including the 56 MB attachment client).
JSON IPC has explicit protocol budgets: 128 MiB raw request body, 64 MiB raw
response, and 256 KiB of UTF-8 headers per direction. These exceed current
20 MB image/65,536-byte OCR inputs and the 56 MB attachment response. They are
transport limits, not permission to exceed any owning application limit.

This module is not enabled by importing it. The optional factory defaults to
the existing spawn transport and never retries a failed lightweight request.
"""

from __future__ import annotations

import base64
import json
import math
import os
import selectors
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, BinaryIO, cast

from pals_agent.http_transport import (
    MAX_HTTP_RESPONSE_BYTES,
    HardDeadlineHttpTransport,
    HttpDeadlineExceeded,
    HttpResponse,
    HttpResponseTooLarge,
    HttpTransport,
    HttpTransportError,
    _http_helper,
    _positive_timeout,
)

MAX_REQUEST_BODY_BYTES = 128 * 1024 * 1024
MAX_RESPONSE_BODY_BYTES = 64 * 1024 * 1024
MAX_HEADER_BYTES = 256 * 1024
MAX_URL_BYTES = 65_536
MAX_STDERR_BYTES = 8_192
_REQUEST_BYTES = 4 * ((MAX_REQUEST_BODY_BYTES + 2) // 3) + 6 * MAX_HEADER_BYTES + 524_288
_BOOTSTRAP = "from pals_agent.lightweight_http_transport import _child_main; _child_main()"


def _need(value: bool) -> None:
    if not value:
        raise ValueError("invalid HTTP IPC object")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _need(key not in result)
        result[key] = value
    return result


def _invalid_constant(_value: str) -> Any:
    raise ValueError("invalid HTTP IPC number")


def _decode(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    _need(type(value) is dict)
    return cast(dict[str, Any], value)


def _encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()


def _unbase64(value: Any, maximum: int) -> bytes:
    _need(type(value) is str and len(value) <= 4 * ((maximum + 2) // 3))
    decoded = base64.b64decode(value, validate=True)
    _need(len(decoded) <= maximum and base64.b64encode(decoded).decode("ascii") == value)
    return decoded


def _headers(value: Any) -> tuple[tuple[str, str], ...]:
    _need(type(value) is list)
    total = 0
    rows: list[tuple[str, str]] = []
    for row in value:
        _need(type(row) is list and len(row) == 2 and all(type(v) is str for v in row))
        key, item = row
        total += len(key.encode("utf-8")) + len(item.encode("utf-8"))
        _need(total <= MAX_HEADER_BYTES)
        rows.append((key, item))
    return tuple(rows)


def _response_limit(maximum: int) -> int:
    return 4 * ((maximum + 2) // 3) + 6 * MAX_HEADER_BYTES + 8_192


def _packet(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
    maximum: int,
) -> bytes:
    _need(
        type(method) is str
        and 0 < len(method) <= 128
        and type(url) is str
        and 0 < len(url.encode("utf-8")) <= MAX_URL_BYTES
    )
    _need(
        type(headers) is dict and all(type(k) is str and type(v) is str for k, v in headers.items())
    )
    _headers([[k, v] for k, v in headers.items()])
    _need(body is None or (type(body) is bytes and len(body) <= MAX_REQUEST_BODY_BYTES))
    ca = os.environ.get("SSL_CERT_FILE") or None
    _need(ca is None or len(ca.encode("utf-8")) <= MAX_URL_BYTES)
    raw = _encode(
        {
            "version": 1,
            "max_response_bytes": maximum,
            "request": {
                "method": method,
                "url": url,
                "headers": headers,
                "body": base64.b64encode(body).decode("ascii") if body is not None else None,
                "socket_timeout": timeout,
                "ssl_cert_file": ca,
            },
        }
    )
    _need(len(raw) <= _REQUEST_BYTES)
    return raw


def _read_request(raw: bytes) -> tuple[dict[str, Any], int]:
    _need(0 < len(raw) <= _REQUEST_BYTES)
    packet = _decode(raw)
    _need(
        set(packet) == {"version", "max_response_bytes", "request"}
        and type(packet["version"]) is int
        and packet["version"] == 1
    )
    maximum = packet["max_response_bytes"]
    _need(type(maximum) is int and 0 < maximum <= MAX_RESPONSE_BODY_BYTES)
    request = packet["request"]
    _need(
        type(request) is dict
        and set(request)
        == {
            "method",
            "url",
            "headers",
            "body",
            "socket_timeout",
            "ssl_cert_file",
        }
    )
    _need(
        type(request["method"]) is str
        and 0 < len(request["method"]) <= 128
        and type(request["url"]) is str
        and 0 < len(request["url"].encode("utf-8")) <= MAX_URL_BYTES
    )
    headers = request["headers"]
    _need(
        type(headers) is dict and all(type(k) is str and type(v) is str for k, v in headers.items())
    )
    _headers([[k, v] for k, v in headers.items()])
    timeout = request["socket_timeout"]
    _need(type(timeout) is float and math.isfinite(timeout) and timeout > 0)
    ca = request["ssl_cert_file"]
    _need(ca is None or (type(ca) is str and len(ca.encode("utf-8")) <= MAX_URL_BYTES))
    if request["body"] is not None:
        request["body"] = _unbase64(request["body"], MAX_REQUEST_BODY_BYTES)
    return cast(dict[str, Any], request), maximum


class _JsonConnection:
    """Only the recv/send/close methods used by the existing owning helper."""

    def __init__(self, request: dict[str, Any], maximum: int) -> None:
        self.request = request
        self.maximum = maximum
        self.sent = False

    def recv(self) -> dict[str, Any]:
        return self.request

    def send(self, value: tuple[Any, ...]) -> None:
        _need(not self.sent and type(value) is tuple and len(value) > 0)
        self.sent = True
        if value[0] == "response":
            _need(
                len(value) == 4
                and type(value[1]) is int
                and 100 <= value[1] <= 599
                and type(value[2]) is bytes
                and len(value[2]) <= self.maximum
                and type(value[3]) is tuple
            )
            headers = _headers([list(row) for row in value[3]])
            result = {
                "outcome": "response",
                "status": value[1],
                "body": base64.b64encode(value[2]).decode("ascii"),
                "headers": headers,
            }
        else:
            _need(value in {("too_large",), ("transport_error",)})
            result = {"outcome": value[0]}
        raw = _encode(result)
        _need(len(raw) <= _response_limit(self.maximum))
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()

    def close(self) -> None:
        pass


def _child_main() -> None:
    # The parent supplies a minimal environment before interpreter startup.
    # SSL_CERT_FILE is forwarded per request, not inherited from a forkserver.
    try:
        _need("pals_agent.cli" not in sys.modules)
        request, maximum = _read_request(sys.stdin.buffer.read(_REQUEST_BYTES + 1))
        _http_helper(cast(Connection, _JsonConnection(request, maximum)), maximum)
    except BaseException:
        # Never serialize a URL/body/header or raw exception into either pipe.
        raise SystemExit(2) from None


def _exchange(
    child: subprocess.Popen[bytes],
    payload: bytes,
    deadline: float,
    stdout_limit: int,
) -> bytes:
    streams = cast(tuple[BinaryIO, BinaryIO, BinaryIO], (child.stdin, child.stdout, child.stderr))
    output = bytearray()
    stderr_bytes = 0
    offset = 0
    with selectors.DefaultSelector() as selector:
        for name, stream, event in zip(
            ("stdin", "stdout", "stderr"),
            streams,
            (selectors.EVENT_WRITE, selectors.EVENT_READ, selectors.EVENT_READ),
            strict=True,
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, event, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline")
            for key, _ in selector.select(remaining):
                stream = cast(BinaryIO, key.fileobj)
                name = key.data
                try:
                    if name == "stdin":
                        offset += os.write(
                            stream.fileno(), memoryview(payload)[offset : offset + 65_536]
                        )
                        if offset == len(payload):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        chunk = os.read(stream.fileno(), 65_536)
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                        elif name == "stdout":
                            output.extend(chunk)
                            if len(output) > stdout_limit:
                                raise HttpTransportError(
                                    "HTTP helper output exceeded its byte limit"
                                )
                        else:
                            stderr_bytes += len(chunk)
                            if stderr_bytes > MAX_STDERR_BYTES:
                                raise HttpTransportError(
                                    "HTTP helper output exceeded its byte limit"
                                )
                except BlockingIOError:
                    continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline")
        try:
            child.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline") from None
    if child.returncode != 0:
        raise HttpTransportError("HTTP helper failed")
    return bytes(output)


def _reap(child: subprocess.Popen[bytes]) -> None:
    try:
        if child.poll() is None:
            with suppress(ProcessLookupError):
                child.terminate()
            try:
                child.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    child.kill()
        child.wait()
    finally:
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()


def _response(raw: bytes, maximum: int) -> HttpResponse:
    result = _decode(raw)
    if result == {"outcome": "too_large"}:
        raise HttpResponseTooLarge("HTTP response exceeded the byte limit")
    if set(result) != {"outcome", "status", "body", "headers"} or result["outcome"] != "response":
        raise HttpTransportError("HTTP request failed")
    _need(type(result["status"]) is int and 100 <= result["status"] <= 599)
    return HttpResponse(
        result["status"], _unbase64(result["body"], maximum), _headers(result["headers"])
    )


@dataclass(frozen=True, slots=True)
class LightweightHttpTransport:
    max_response_bytes: int = MAX_HTTP_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if (
            type(self.max_response_bytes) is not int
            or not 0 < self.max_response_bytes <= MAX_RESPONSE_BODY_BYTES
        ):
            raise ValueError("max_response_bytes must fit the HTTP protocol budget")
        if os.name != "posix":
            raise ValueError("lightweight HTTP pipes require POSIX")

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse:
        timeout = _positive_timeout(timeout_seconds)
        deadline = time.monotonic() + timeout
        child: subprocess.Popen[bytes] | None = None
        try:
            payload = _packet(method, url, headers, body, timeout, self.max_response_bytes)
            if time.monotonic() >= deadline:
                raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline")
            # Static module entry in the same immutable installed image. Request
            # values and CA path travel only via stdin; PYTHONPATH, credentials,
            # proxies, user site and cwd never select the child implementation.
            child = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", _BOOTSTRAP],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "LC_ALL": "C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            raw = _exchange(child, payload, deadline, _response_limit(self.max_response_bytes))
            response = _response(raw, self.max_response_bytes)
            if time.monotonic() >= deadline:
                raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline")
            return response
        except (OSError, ValueError, TypeError, RecursionError):
            raise HttpTransportError("HTTP helper failed") from None
        finally:
            if child is not None:
                _reap(child)


def fresh_process_http_transport(
    *,
    max_response_bytes: int = MAX_HTTP_RESPONSE_BYTES,
    use_lightweight: bool = False,
) -> HttpTransport:
    """Explicit opt-in only; unsupported platforms use spawn before any request."""
    if use_lightweight and sys.platform.startswith("linux"):
        return LightweightHttpTransport(max_response_bytes=max_response_bytes)
    return HardDeadlineHttpTransport(max_response_bytes=max_response_bytes)
