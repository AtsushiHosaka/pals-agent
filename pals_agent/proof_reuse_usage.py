"""Stage labels for the existing content-free provider metering callback."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_role: ContextVar[str] = ContextVar("proof_reuse_model_role", default="proof_reuse_judge")


def current_role() -> str:
    return _role.get()


@contextmanager
def model_role(role: str) -> Iterator[None]:
    token = _role.set(role)
    try:
        yield
    finally:
        _role.reset(token)
