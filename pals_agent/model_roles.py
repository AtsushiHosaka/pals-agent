from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal


class ModelRole(StrEnum):
    """The complete, externally recorded generation-role vocabulary."""

    OPENMATH = "openmath"
    DRAFT = "draft"
    SKETCH = "sketch"
    PROVE = "prove"
    ROUTE = "route"
    REPAIR = "repair"
    EXPLAIN = "explain"
    CLARIFY = "clarify"
    PROOF_REVIEW = "proof_review"


@dataclass(frozen=True, slots=True)
class RoleModelDefault:
    role: ModelRole
    provider: Literal["openai"]
    model: str


RELEASE_ROLE_REGISTRY_REVISION: Final = "pals.release-role-registry.v1"
RELEASE_MODEL_PROVIDER: Final = "openai"
RELEASE_MODEL: Final = "gpt-5.4-mini-2026-03-17"

# This ordered tuple is the source of truth for release model identity.  It deliberately
# has no environment-derived provider, alias, fallback, or per-role override.
RELEASE_ROLE_REGISTRY: Final[tuple[RoleModelDefault, ...]] = tuple(
    RoleModelDefault(role=role, provider=RELEASE_MODEL_PROVIDER, model=RELEASE_MODEL)
    for role in (
        ModelRole.OPENMATH,
        ModelRole.DRAFT,
        ModelRole.SKETCH,
        ModelRole.PROVE,
        ModelRole.ROUTE,
        ModelRole.REPAIR,
        ModelRole.EXPLAIN,
        ModelRole.CLARIFY,
        ModelRole.PROOF_REVIEW,
    )
)
_FIXED_ROLE_DEFAULTS: Final = {entry.role: entry for entry in RELEASE_ROLE_REGISTRY}


def fixed_model_default(role: ModelRole) -> RoleModelDefault:
    """Return the immutable release binding for one known generation role."""

    return _FIXED_ROLE_DEFAULTS[role]
