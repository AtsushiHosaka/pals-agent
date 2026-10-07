"""Stage labels for the existing content-free provider metering callback."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

P = ParamSpec("P")
R = TypeVar("R")

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


def with_model_role(role: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Label every retry in a stage without mutating a shared provider client."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def run(*args: P.args, **kwargs: P.kwargs) -> R:
            with model_role(role):
                return function(*args, **kwargs)

        return run

    return decorate


@dataclass(frozen=True, slots=True)
class RoleBoundClient:
    """Bind an immutable client at composition without changing pinned source."""

    client: Any
    role: str

    def generate(self, *, model: str, prompt: str, **kwargs: Any) -> str:
        with model_role(self.role):
            return cast(str, self.client.generate(model=model, prompt=prompt, **kwargs))
