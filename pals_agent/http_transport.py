from __future__ import annotations

import math
import multiprocessing
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any, Protocol, cast
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_HTTP_RESPONSE_BYTES = 1_048_576


class HardDeadlineHttpError(RuntimeError):
    """Base class for closed hard-deadline transport failures."""


class HttpDeadlineExceeded(HardDeadlineHttpError):
    pass


class HttpResponseTooLarge(HardDeadlineHttpError):
    pass


class HttpTransportError(HardDeadlineHttpError):
    pass


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


class HttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse: ...


class _ProcessContext(Protocol):
    def Pipe(self, duplex: bool = True) -> tuple[Connection, Connection]: ...

    def Process(
        self,
        *,
        target: Callable[..., object],
        args: tuple[Any, ...],
        daemon: bool,
    ) -> multiprocessing.Process: ...


@dataclass(frozen=True, slots=True)
class HardDeadlineHttpTransport:
    max_response_bytes: int = MAX_HTTP_RESPONSE_BYTES
    process_start_method: str = "spawn"

    def __post_init__(self) -> None:
        if type(self.max_response_bytes) is not int or self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        if self.process_start_method not in {"spawn", "forkserver", "fork"}:
            raise ValueError("unsupported HTTP helper process start method")

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
        started_at = time.monotonic()
        deadline = started_at + timeout
        context = cast(
            _ProcessContext,
            multiprocessing.get_context(self.process_start_method),
        )
        parent_connection, child_connection = context.Pipe(duplex=True)
        process = context.Process(
            target=_http_helper,
            args=(child_connection, self.max_response_bytes),
            daemon=True,
        )
        try:
            process.start()
            child_connection.close()
            parent_connection.send(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "body": body,
                    "socket_timeout": timeout,
                }
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not parent_connection.poll(remaining):
                _terminate_and_reap(process)
                raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline")
            message = parent_connection.recv()
            remaining = deadline - time.monotonic()
            process.join(max(0.0, remaining))
            if process.is_alive() or time.monotonic() >= deadline:
                _terminate_and_reap(process)
                raise HttpDeadlineExceeded("HTTP request exceeded its hard deadline")
        except HardDeadlineHttpError:
            raise
        except (EOFError, OSError, TypeError, ValueError):
            _terminate_and_reap(process)
            raise HttpTransportError("HTTP helper failed") from None
        finally:
            parent_connection.close()
            child_connection.close()

        if not isinstance(message, tuple) or not message:
            raise HttpTransportError("HTTP helper returned an invalid result")
        outcome = message[0]
        if outcome == "response" and len(message) == 4:
            status_code, response_body, response_headers = message[1], message[2], message[3]
            if (
                type(status_code) is not int
                or not isinstance(response_body, bytes)
                or not isinstance(response_headers, tuple)
                or not all(
                    isinstance(name, str) and isinstance(value, str)
                    for name, value in response_headers
                )
            ):
                raise HttpTransportError("HTTP helper returned an invalid response")
            return HttpResponse(
                status_code=status_code,
                body=response_body,
                headers=cast(tuple[tuple[str, str], ...], response_headers),
            )
        if outcome == "too_large":
            raise HttpResponseTooLarge("HTTP response exceeded the byte limit")
        raise HttpTransportError("HTTP request failed")


def _http_helper(connection: Connection, max_response_bytes: int) -> None:
    try:
        message = connection.recv()
        if not isinstance(message, dict):
            connection.send(("transport_error",))
            return
        method = message.get("method")
        url = message.get("url")
        headers = message.get("headers")
        body = message.get("body")
        socket_timeout = message.get("socket_timeout")
        if (
            not isinstance(method, str)
            or not isinstance(url, str)
            or not isinstance(headers, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in headers.items()
            )
            or (body is not None and not isinstance(body, bytes))
            or not isinstance(socket_timeout, float)
        ):
            connection.send(("transport_error",))
            return
        request = Request(
            url,
            data=body,
            headers=cast(dict[str, str], headers),
            method=method,
        )
        opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
        try:
            with opener.open(request, timeout=socket_timeout) as response:
                status_code = response.status
                response_body = response.read(max_response_bytes + 1)
                response_headers = tuple(
                    (str(name), str(value)) for name, value in response.headers.items()
                )
        except HTTPError as exc:
            status_code = exc.code
            response_body = exc.read(max_response_bytes + 1)
            response_headers = tuple(
                (str(name), str(value)) for name, value in exc.headers.items()
            )
        if len(response_body) > max_response_bytes:
            connection.send(("too_large",))
            return
        connection.send(("response", status_code, response_body, response_headers))
    except BaseException:
        with suppress(BaseException):
            connection.send(("transport_error",))
    finally:
        connection.close()


def _terminate_and_reap(process: multiprocessing.Process) -> None:
    if process.pid is None:
        return
    if process.is_alive():
        process.terminate()
        process.join(0.05)
    if process.is_alive():
        process.kill()
    process.join()


class _NoRedirectHandler(HTTPRedirectHandler):
    """Treat every 3xx response as terminal instead of following another origin/path."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Request | None:
        del req, fp, code, msg, headers, newurl
        return None


def _positive_timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError("HTTP timeout must be a positive finite number")
    return float(value)
