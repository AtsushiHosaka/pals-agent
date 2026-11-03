"""Stage labels for the existing content-free provider metering callback."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_role: ContextVar[str] = ContextVar("proof_reuse_model_role", default="proof_reuse_judge")


def current_role() -> str:
    return _role.get()


def explicit_role() -> str | None:
    """The role set by an enclosing model_role, without the metering default."""
    return _role.get(None)  # type: ignore[arg-type]


@contextmanager
def model_role(role: str) -> Iterator[None]:
    token = _role.set(role)
    try:
        yield
    finally:
        _role.reset(token)
