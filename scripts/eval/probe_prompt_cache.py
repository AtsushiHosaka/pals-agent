"""Why does the prompt cache miss? Tiny calls with the real direct-prove prompt, varying the gap
between calls and whether ``prompt_cache_key`` is set. Each phase uses its own fresh prefix (a
random first line) so an earlier phase cannot warm a later one. Needs OPENAI_API_KEY; each call
asks for at most 200 output tokens, so a probe costs a few cents. Prints cached/input per call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_stages  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--spend-ledger", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from pals_agent import generator as g
    from pals_agent.artifacts import FileArtifactStore
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.pipeline import ProofPipeline
    from pals_agent.usage import usage_scope

    problems = run_stages.select(json.loads(run_stages.DEFAULT_MANIFEST.read_text()), None, 2)
    pipeline = ProofPipeline(
        generator=object(), verifier=None, verification_mode="api_reconcile",  # type: ignore[arg-type]
        artifact_store=FileArtifactStore(args.out / "art"),
    )
    prompts = [
        g._direct_prove_prompt_for(
            pipeline.prepare_statement(
                statement=p["statement"], formal_statement=p.get("fixed_lean_statement")
            ),
            None,
        )
        for p in problems
    ]

    def client(key: str | None) -> OpenAIResponsesClient:
        return OpenAIResponsesClient(
            api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=200,
            reasoning_effort="low", prompt_cache_key=key, timeout_seconds=120,
        )

    def call(c: OpenAIResponsesClient, salt: str, i: int) -> tuple[int, int]:
        got: list[dict] = []
        with usage_scope(got.append):
            try:
                c.generate(model="gpt-6.1-terra", prompt=f"[{salt}]\n" + prompts[i % 2])
            except Exception:  # noqa: BLE001 -- an incomplete 200-token answer still reports usage
                pass
        return (
            sum(u.get("cached_input_tokens", 0) for u in got),
            sum(u["input_tokens"] for u in got),
        )

    log: list[dict] = []

    def phase(name: str, key: str | None, salt: str, gaps: list[float]) -> None:
        c = client(key)
        for n, gap in enumerate(gaps):
            time.sleep(gap)
            cached, total = call(c, salt, n)
            row = {"phase": name, "call": n, "gap_s": gap, "cached": cached, "input": total}
            log.append(row)
            print(row, flush=True)

    s1, s2 = uuid.uuid4().hex[:8], uuid.uuid4().hex[:8]
    phase("no_key_fresh_3s", None, s1, [0] + [3] * 7)
    phase("key_fresh_3s", "pals-direct-prove", s2, [0] + [3] * 7)
    phase("no_key_again_after_60s", None, s1, [60, 60])
    phase("no_key_again_after_300s", None, s1, [300])
    (args.out / "probe.json").write_text(json.dumps(log))


if __name__ == "__main__":
    main()
