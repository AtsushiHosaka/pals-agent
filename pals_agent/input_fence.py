"""Snapshot checks at controllable call boundaries (not provider cancellation)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class InputSnapshotObsolete(RuntimeError):
    pass


_check: ContextVar[Callable[[], bool] | None] = ContextVar("proof_input_fence", default=None)


def check_input_snapshot() -> None:
    check = _check.get()
    if check is not None and not check():
        raise InputSnapshotObsolete("proof_input_snapshot_obsolete")


@contextmanager
def input_fence_scope(check: Callable[[], bool] | None) -> Iterator[None]:
    token = _check.set(check)
    try:
        check_input_snapshot()
        yield
    finally:
        _check.reset(token)
