from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


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
    PROOF_REUSE_JUDGE = "proof_reuse_judge"
    PROOF_REUSE_JUDGE_ESCALATION = "proof_reuse_judge_escalation"


@dataclass(frozen=True, slots=True)
class RoleModelDefault:
    role: ModelRole
    provider: Literal["openai"]
    model: str
    reasoning_effort: ReasoningEffort = "low"


RELEASE_ROLE_REGISTRY_REVISION: Final = "pals.release-role-registry.v3"
RELEASE_MODEL_PROVIDER: Final = "openai"
RELEASE_MODEL: Final = "gpt-6-luna"
LEAN_GENERATION_MODEL: Final = "gpt-6.1-terra"
ESCALATION_MODEL: Final = LEAN_GENERATION_MODEL

_LEAN_ROLES: Final = frozenset({
    ModelRole.DRAFT, ModelRole.SKETCH, ModelRole.PROVE, ModelRole.REPAIR,
})

# This ordered tuple is the source of truth for release model identity.  It deliberately
# has no environment-derived provider, fallback, or per-role override. The public
# aliases below are exact identities, with no automatic Astra fallback.
RELEASE_ROLE_REGISTRY: Final[tuple[RoleModelDefault, ...]] = tuple(
    RoleModelDefault(
        role=role,
        provider=RELEASE_MODEL_PROVIDER,
        model=LEAN_GENERATION_MODEL if role in _LEAN_ROLES else RELEASE_MODEL,
        reasoning_effort="medium" if role in _LEAN_ROLES else "low",
    )
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
        ModelRole.PROOF_REUSE_JUDGE,
    )
) + (
    RoleModelDefault(
        role=ModelRole.PROOF_REUSE_JUDGE_ESCALATION,
        provider=RELEASE_MODEL_PROVIDER,
        model=ESCALATION_MODEL,
        reasoning_effort="high",
    ),
)
_FIXED_ROLE_DEFAULTS: Final = {entry.role: entry for entry in RELEASE_ROLE_REGISTRY}


def fixed_model_default(role: ModelRole) -> RoleModelDefault:
    """Return the immutable release binding for one known generation role."""

    return _FIXED_ROLE_DEFAULTS[role]
