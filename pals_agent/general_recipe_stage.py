"""Request-path stage for the general-Recipe lane (default OFF, zero model calls).

``general_recipe_lane`` decides, with the real Lean and a fixed back-check, whether a formal
proposition is a specialisation of a stored general Recipe.  This module is the thin, fail-closed
adapter between that lane and the request path (``ProofReuseRuntime.general_recipe_input``):

* it is inert unless ``PALS_GENERAL_RECIPE_LANE`` is on *and* a Lean runner was configured;
* every miss, error, timeout or rejected back-check returns ``outcome="miss"`` -- the caller then
  continues with the established route; this stage never fails a request and never answers
  without Lean's acceptance;
* the evidence it returns carries what a downstream settlement needs to re-derive the claim: the
  Recipe binding (id, revision, entry/lean/answer digests), the exact proposition, the digest of
  the compiled instance source, the back-check results (declared statement identical to the
  request's, standard axioms only, the general theorem actually used) and ``model_calls == 0``.

The API does not accept this evidence kind yet (``lean_general_recipe`` is outside its closed
set); until it does, the flag must stay off in production.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pals_agent import general_recipe_lane as lane

SCHEMA_VERSION: Final = "pals.general-recipe-stage.v1"
EVIDENCE_KIND: Final = "lean_general_recipe"
WORKSPACE_ENV: Final = "PALS_GENERAL_RECIPE_LANE_WORKSPACE"
MAX_LEAN_SECONDS: Final = 60.0
MIN_LEAN_SECONDS: Final = 5.0


def stage_enabled(environ: dict[str, str] | None = None) -> bool:
    """Default OFF (same switch as the lane)."""
    return lane.lane_enabled(environ)


@dataclass(slots=True)
class StageResult:
    outcome: str  # "answered" | "miss"
    code: str | None = None
    answer_text: str | None = None
    recipe: dict[str, Any] | None = None
    proposition: str | None = None
    instance_source_sha256: str | None = None
    seconds: dict[str, float] = field(default_factory=dict)
    tried: list[dict[str, Any]] = field(default_factory=list)

    def evidence(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "phase": "general_recipe_instance",
            "lean_route": "general_recipe_lane",
            "outcome": self.outcome,
            "code": self.code,
            "model_calls": 0,
            "seconds": self.seconds,
            "tried": self.tried,
        }
        if self.outcome == "answered":
            out.update(
                {
                    "recipe": self.recipe,
                    "formal_source": "request_grammar",
                    "formal_statement": self.proposition,
                    "formal_statement_sha256": hashlib.sha256(
                        (self.proposition or "").encode()
                    ).hexdigest(),
                    "instance_source_sha256": self.instance_source_sha256,
                    "back_checks": {
                        "declared_statement_equals_request": True,
                        "standard_axioms_only": True,
                        "general_theorem_used": True,
                    },
                }
            )
        return out


@dataclass(frozen=True, slots=True)
class GeneralRecipeStage:
    runner: lane.LeanRunner
    candidates: int = lane.DEFAULT_CANDIDATES

    def run(
        self, proposition: str, recipes: list[dict[str, Any]], language: str, *, budget_s: float
    ) -> StageResult:
        """Try ``proposition`` against the searched Recipes; any problem is a miss."""
        if budget_s < MIN_LEAN_SECONDS:
            return StageResult("miss", "budget_too_small")
        started = time.monotonic()
        pool: list[lane.PoolRecipe] = []
        by_id: dict[str, dict[str, Any]] = {}
        for candidate in recipes:
            try:
                pool.append(
                    lane.PoolRecipe(
                        candidate["recipe_id"],
                        candidate["lean_code"],
                        candidate["target_source"],
                        candidate["answer"],
                        candidate["output_language"],
                        "catalog",
                    )
                )
            except (KeyError, TypeError):
                continue
            by_id[candidate["recipe_id"]] = candidate
        if not pool:
            return StageResult("miss", "no_recipe")
        runner = dataclasses.replace(
            self.runner, timeout_seconds=min(MAX_LEAN_SECONDS, budget_s)
        )
        try:
            result = lane.answer(
                proposition, pool, runner, language=language, candidates=self.candidates
            )
        except Exception as error:  # a stage must never fail the request
            return StageResult("miss", f"lane_error:{type(error).__name__}")
        seconds = dict(result.timings_ms)
        seconds["wall"] = round((time.monotonic() - started) * 1000, 1)
        if result.outcome != "answered" or not result.answer_text or result.recipe_id not in by_id:
            code = result.code or ("no_stored_answer" if result.outcome == "answered" else "miss")
            return StageResult("miss", code, seconds=seconds, tried=result.tried)
        chosen = by_id[result.recipe_id]
        digests = {
            key: chosen.get(key)
            for key in ("recipe_id", "recipe_revision", "entry_sha256", "lean_sha256",
                        "answer_sha256")
        }
        return StageResult(
            "answered",
            None,
            result.answer_text,
            digests,
            result.proposition,
            result.instance_source_sha256,
            seconds,
            result.tried,
        )


def from_environment(environ: dict[str, str] | None = None) -> GeneralRecipeStage | None:
    """The configured stage, or ``None`` (flag off, no Lean workspace, toolchain unresolved)."""
    env = environ if environ is not None else os.environ
    if not stage_enabled(env):
        return None
    workspace = env.get(WORKSPACE_ENV, "").strip()
    if not workspace:
        return None
    try:
        return GeneralRecipeStage(lane.LeanRunner.from_workspace(Path(workspace)))
    except Exception:
        return None
