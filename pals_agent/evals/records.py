"""Append-only JSONL records for generation evals (no problem text, no secrets, no user content).

Two row kinds share one file per run:
  attempt  one stage execution (draft, sketch, sketch_check, prove, lean_check, repair,
           replay_check)
  run      one (problem, arm, repeat) outcome, written last

Lean source of failed attempts is NOT inlined: it goes to
``<artifacts>/<run_id>/<problem>/<n>.lean``
and the row carries its sha256 and relative path.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ATTEMPT_SCHEMA = "pals.generation-eval.attempt.v1"
RUN_SCHEMA = "pals.generation-eval.run.v1"
STAGES = (
    "draft",
    "sketch",
    "sketch_check",
    "prove",
    "prove_direct",  # T2 no-Sketch full proof
    "patch",  # T2 patch repair
    "lean_check",
    "repair",
    "replay_check",
)
TIERS = (0, 1, 2, 3)

ATTEMPT_FIELDS = {
    "schema",
    "run_id",
    "problem_id",
    "arm",
    "repeat",
    "ordinal",
    "stage",
    "started_at",
    "ended_at",
    "elapsed_ms",
    "success",
    "error_codes",
    "model",
    "effort",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "diagnostic_count",
    "diagnostics",
    "lean_sha256",
    "lean_path",
}
RUN_FIELDS = {
    "schema",
    "run_id",
    "tier",
    "problem_id",
    "arm",
    "repeat",
    "split",
    "success",
    "first_attempt_ok",
    "repairs_used",
    "wall_s",
    "cost_usd",
    "model_calls",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "termination_reason",
    "config",
    "started_at",
    "ended_at",
    "error",
    # Tier 2 additions: stage breakdown and the answer stage (review + explanation).
    "stage_ms",
    "answer_s",
    "answer_ok",
    "answer_note",
    "review_s",
    "review_approved",
    "review_error",
    "explain_wait_s",
    "explain_ok",
    "explain_error",
    "explained_in_parallel",
    "undrained_background_calls",
    "load_1m_start",
    "load_1m_end",
    "load_guard_timeout",
}


class RecordError(ValueError):
    pass


def validate_row(row: dict[str, Any]) -> None:
    kind = row.get("schema")
    allowed = {ATTEMPT_SCHEMA: ATTEMPT_FIELDS, RUN_SCHEMA: RUN_FIELDS}.get(str(kind))
    if allowed is None:
        raise RecordError(f"unknown schema {kind!r}")
    extra = set(row) - allowed
    if extra:
        raise RecordError(f"unexpected fields {sorted(extra)} (closed schema)")
    for key in ("run_id", "problem_id", "arm"):
        if not isinstance(row.get(key), str) or not row[key]:
            raise RecordError(f"{key} is required")
    if kind == ATTEMPT_SCHEMA and row.get("stage") not in STAGES:
        raise RecordError(f"bad stage {row.get('stage')!r}")
    if kind == RUN_SCHEMA and row.get("tier") not in TIERS:
        raise RecordError(f"bad tier {row.get('tier')!r}")


class JsonlSink:
    """Append-only writer: one fsync'd line per row, refuses unknown fields."""

    def __init__(self, path: Path, artifacts_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.artifacts_dir = artifacts_dir
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, row: dict[str, Any]) -> None:
        validate_row(row)
        line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    def save_lean(
        self, run_id: str, problem_id: str, ordinal: int, code: str
    ) -> tuple[str, str | None]:
        digest = hashlib.sha256(code.encode()).hexdigest()
        if self.artifacts_dir is None:
            return digest, None
        rel = f"{run_id}/{problem_id}/{ordinal}.lean"
        target = self.artifacts_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")
        return digest, rel


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            validate_row(row)
            rows.append(row)
    return rows
