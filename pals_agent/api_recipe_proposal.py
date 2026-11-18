"""API-owned compile hints for general Recipes; no local Lean or answer authority."""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pals_agent.recipe_instantiation import elaborate

SCHEMA = "pals.recipe-instance-proposal.v1"
HEX = re.compile(r"[a-f0-9]{64}\Z")
REASONS = {
    "disabled",
    "unavailable",
    "claim_budget",
    "candidate_ineligible",
    "not_instance",
    "compile_failed",
}


def validate_response(value: Any, request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "schema_version",
        "decision",
        "reason",
        "request_id",
        "claim_id",
        "request_revision",
        "request_context_sha256",
        "recipe_id",
        "recipe_revision",
        "entry_sha256",
        "candidate",
    }
    if not isinstance(value, dict) or set(value) != keys or value["schema_version"] != SCHEMA:
        raise ValueError("invalid Recipe proposal envelope")
    expected = {
        "request_id": request_id,
        "request_revision": payload["expected_revision"],
        **{
            k: payload[k]
            for k in (
                "claim_id",
                "request_context_sha256",
                "recipe_id",
                "recipe_revision",
                "entry_sha256",
            )
        },
    }
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in expected.items()):
        raise ValueError("Recipe proposal binding mismatch")
    if value["decision"] == "fallback":
        if (
            not isinstance(value["reason"], str)
            or value["reason"] not in REASONS
            or value["candidate"] is not None
        ):
            raise ValueError("invalid Recipe fallback")
    elif value["decision"] == "candidate":
        candidate = value["candidate"]
        if (
            value["reason"] is not None
            or not isinstance(candidate, dict)
            or set(candidate)
            != {
                "instance_proposition",
                "instance_proposition_sha256",
                "instance_source_sha256",
                "bindings",
            }
        ):
            raise ValueError("invalid Recipe candidate")
        proposition = candidate["instance_proposition"]
        if (
            not isinstance(proposition, str)
            or not 1 <= len(proposition) <= 2000
            or candidate["bindings"] != payload["bindings"]
            or any(
                not isinstance(candidate[k], str) or not HEX.fullmatch(candidate[k])
                for k in ("instance_proposition_sha256", "instance_source_sha256")
            )
            or hashlib.sha256(proposition.encode()).hexdigest()
            != candidate["instance_proposition_sha256"]
        ):
            raise ValueError("invalid Recipe candidate hashes")
    else:
        raise ValueError("invalid Recipe proposal decision")
    return value


@dataclass(slots=True)
class ProposalResult:
    outcome: str
    chosen: dict[str, Any] | None = None
    code: str | None = None
    tried: list[dict[str, str]] = field(default_factory=list)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "phase": "api_recipe_instance_proposal",
            "decision": "candidate" if self.outcome == "candidate" else "fallback",
            "not_verified_answer": True,
            "model_calls": 0,
            "tried": self.tried,
        }


@dataclass(slots=True)
class RemoteGeneralRecipeStage:
    propose: Callable[..., dict[str, Any]]

    def run(
        self,
        proposition: str,
        recipes: list[dict[str, Any]],
        language: str,
        *,
        budget_s: float,
        bound: bool = False,
        proposal_context: dict[str, Any] | None = None,
    ) -> ProposalResult:
        from pals_agent.api_client import PalsApiError

        if bound or proposal_context is None or not math.isfinite(budget_s) or budget_s < 2:
            return ProposalResult("miss", code="proposal_budget_or_context")
        deadline = time.monotonic() + budget_s
        tried: list[dict[str, str]] = []
        for recipe in recipes[:4]:
            remaining = deadline - time.monotonic()
            if remaining < 3:
                break
            payload = {
                **proposal_context,
                **{k: recipe[k] for k in ("recipe_id", "recipe_revision", "entry_sha256")},
                "requested_proposition": proposition,
                "bindings": [],
            }
            request_id = payload.pop("request_id")
            try:
                response = self.propose(
                    request_id=request_id,
                    **payload,
                    timeout_seconds=min(90.0, remaining),
                    budget_ms=min(90_000, int((remaining - 1.0) * 1000)),
                )
                validate_response(response, request_id, payload)
                if response["decision"] == "fallback":
                    tried.append({"recipe_id": recipe["recipe_id"], "decision": response["reason"]})
                    if response["reason"] in {"disabled", "unavailable", "claim_budget"}:
                        break
                    continue
                expected = elaborate(recipe["lean_code"], proposition)
                actual = response["candidate"]
                if (
                    actual["instance_proposition"],
                    actual["instance_proposition_sha256"],
                    actual["instance_source_sha256"],
                ) != (expected.proposition, expected.proposition_sha256, expected.source_sha256):
                    raise ValueError("API proposal differs from sealed Recipe derivation")
                if time.monotonic() >= deadline:
                    break
                return ProposalResult("candidate", recipe, tried=tried)
            except (PalsApiError, ValueError, TypeError, KeyError, TimeoutError):
                return ProposalResult("miss", code="proposal_unavailable", tried=tried)
        return ProposalResult("miss", code="no_api_proposal", tried=tried)
