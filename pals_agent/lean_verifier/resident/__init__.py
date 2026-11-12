"""Resident Lean: a warm Mathlib process that serves compile and audit requests by forking.

See ``manager.ResidentLean``.  Default off; nothing here runs unless a verifier is given one.
"""

from pals_agent.lean_verifier.resident.adapter import ResidentWorker
from pals_agent.lean_verifier.resident.manager import (
    AuditOutcome,
    CompileOutcome,
    ResidentBusy,
    ResidentConfig,
    ResidentLean,
    ResidentUnavailable,
    confinement_available,
)

__all__ = [
    "confinement_available",
    "AuditOutcome",
    "CompileOutcome",
    "ResidentBusy",
    "ResidentConfig",
    "ResidentLean",
    "ResidentUnavailable",
    "ResidentWorker",
]
