"""One small-model formalisation call per NL-only item: only the Lean statement, no proof.

Model/effort = the pipeline's assessment binding (proof_reuse_judge: Luna, low).  The key is read
from OPENAI_API_KEY in the environment or from the single variable of an env file (never echoed).
Spend is estimated from recorded usage and the run stops at --max-usd.

    uv run python scripts/eval/formalise.py --out FILE.jsonl --env-file ENVFILE --max-usd 0.3
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PROMPT = (
    "Translate the mathematical statement below into ONE Lean 4 (Mathlib) proposition.\n"
    "Rules: output only the proposition, a single line, no proof, no `theorem`/`example` keyword, "
    "no tactic, no comment. Quantify every variable explicitly with ∀ and keep every hypothesis "
    "of the statement as an implication or a binder (do not drop, weaken or strengthen anything; "
    "do not choose a special case). Use Mathlib names (Real, ℝ, ℕ, Continuous, HasDerivAt, "
    "Filter.Tendsto, ...). If the statement asks for a computation or a yes/no decision, state the "
    "claim that holds (the true value or the true answer) as a proposition. If it cannot be "
    "stated as a single Lean proposition, return an empty string.\n\nSTATEMENT:\n"
)
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["formal"],
    "properties": {"formal": {"type": "string"}},
}


def load_key(env_file: Path | None) -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    if env_file:
        for line in env_file.read_text().splitlines():
            match = re.match(r"\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*)$", line)
            if match:
                return match.group(1).strip().strip("'\"")
    raise SystemExit("OPENAI_API_KEY not available")


def main() -> None:
    from pals_agent.evals.runner import estimate_usd
    from pals_agent.model_roles import ModelRole, fixed_model_default
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.usage import usage_scope

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--max-usd", type=float, default=0.3)
    args = ap.parse_args()
    binding = fixed_model_default(ModelRole.PROOF_REUSE_JUDGE)
    client = dataclasses.replace(
        OpenAIResponsesClient(
            api_key=load_key(args.env_file), timeout_seconds=60.0, max_output_tokens=800
        ),
        reasoning_effort=binding.reasoning_effort,
    )
    problems = [
        p
        for p in json.loads((ROOT / "testdata/generation-eval-v1/manifest.json").read_text())[
            "problems"
        ]
        if not p.get("fixed_lean_statement")
    ]
    spend = 0.0
    rows: list[dict] = []

    def add(row: dict) -> None:
        nonlocal spend
        spend += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

    with args.out.open("a") as fh:
        for p in problems:
            if spend >= args.max_usd:
                print("budget reached", flush=True)
                break
            t0 = time.monotonic()
            error = None
            formal = ""
            try:
                with usage_scope(add):
                    raw = client.generate(
                        model=binding.model,
                        prompt=PROMPT + p["statement"],
                        response_schema=SCHEMA,
                        timeout_seconds=60.0,
                    )
                formal = " ".join(str(json.loads(raw).get("formal", "")).split())
            except Exception as exc:  # noqa: BLE001 - recorded, never raised
                error = type(exc).__name__
            row = {
                "id": p["id"],
                "formal": formal,
                "seconds": round(time.monotonic() - t0, 2),
                "error": error,
                "model": binding.model,
                "effort": binding.reasoning_effort,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            rows.append(row)
            print(p["id"], bool(formal), row["seconds"], f"spend~{spend:.4f}", flush=True)
    print(f"DONE n={len(rows)} spend_est_usd={spend:.4f}")


if __name__ == "__main__":
    main()
