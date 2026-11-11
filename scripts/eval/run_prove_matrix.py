"""One direct proof per (problem, model/effort config), timed through the resident Lean verifier.

Measures what a first attempt costs in time and money for each configuration, with no Draft,
no repair and no answer stage, so the numbers are the model call plus one verification. A race of
two configurations is then *computed* from these independent single runs (analyze_prove_matrix.py):
each candidate finishes at model_s + verify_s and the first verified one wins. Needs
OPENAI_API_KEY in the environment (never read from or written to a file here); every run takes
--max-usd and stops before the next problem once recorded usage reaches it.

    run_prove_matrix.py --out DIR --n 14 --configs luna_low,terra_low,terra_med --max-usd 0.9 \
      --spend-ledger L.jsonl --lean .../lean --lake .../lake --project WS --elan-home ~/.elan
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_stages  # noqa: E402

SHORT = (
    "\nOutput format: reply with exactly one fenced ```lean block containing the complete proof "
    "and nothing else: no explanation, no preamble, no comments."
)
# name -> (model, reasoning effort or None for the model's own, short-output instruction)
CONFIGS: dict[str, tuple[str, str | None, bool]] = {
    "luna_low": ("gpt-6-luna", None, False),
    "terra_low": ("gpt-6.1-terra", "low", False),
    "terra_med": ("gpt-6.1-terra", "medium", False),
    "terra_med_short": ("gpt-6.1-terra", "medium", True),
    "terra_low_short": ("gpt-6.1-terra", "low", True),
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=14)
    ap.add_argument("--ids")
    ap.add_argument("--configs", required=True)
    ap.add_argument("--max-usd", type=float, required=True)
    ap.add_argument("--total-cap", type=float, default=3.0)
    ap.add_argument("--spend-ledger", type=Path, required=True)
    ap.add_argument("--model-timeout", type=float, default=240.0)
    ap.add_argument("--max-output-tokens", type=int, default=12000)
    ap.add_argument("--seed", type=int, default=20261112)
    for name in ("lean", "lake", "project", "elan-home"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--cold", action="store_true", help="skip the resident Lean (cold verify)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from pals_agent import generator as generator_module
    from pals_agent.evals.runner import estimate_usd, interleaved_schedule
    from pals_agent.generator import HybridLeanGenerator
    from pals_agent.lean import LeanVerifier
    from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean
    from pals_agent.lean_verifier.resident.manager import default_read_roots
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.pipeline import ProofPipeline, validate_generated_lean
    from pals_agent.usage import usage_scope

    names = args.configs.split(",")
    problems = run_stages.select(
        json.loads(run_stages.DEFAULT_MANIFEST.read_text()), args.ids, args.n
    )
    by_id = {p["id"]: p for p in problems}

    import subprocess

    lean_path = subprocess.run(
        [args.lake, "env", "printenv", "LEAN_PATH"],
        cwd=args.project, capture_output=True, text=True, check=True,
    ).stdout.strip()
    scratch = Path(mkdtemp(prefix="pals-matrix-"))  # no spaces: the resident worker requires it
    resident = None
    if not args.cold:
        resident = ResidentLean(
            ResidentConfig(
                project_dir=Path(args.project),
                confine=sys.platform.startswith("linux"),
                request_root=scratch,
                read_roots=default_read_roots(args.lean, lean_path),
                lean_binary=args.lean,
                lean_path=lean_path,
                build_dir=scratch / "resident",
                max_children=2,
                warm_exact=False,
                queue_timeout_s=30.0,
            )
        )
        startup = resident.start()
        print(f"resident startup {startup:.1f}s", flush=True)
    verifier = LeanVerifier(
        lean_binary=args.lean,
        lake_binary=args.lake,
        project_dir=Path(args.project),
        child_path=f"{Path(args.lean).parent}:/usr/bin:/bin",
        elan_home=args.elan_home,
        scratch_dir=scratch,
        timeout_seconds=300.0,
        resident=resident,
    )

    def make_generator(model: str, effort: str | None) -> HybridLeanGenerator:
        client = OpenAIResponsesClient(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("PALS_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout_seconds=args.model_timeout,
            max_output_tokens=args.max_output_tokens,
            reasoning_effort=effort,
        )
        return HybridLeanGenerator(
            model=model, provider="openai", client=client, use_release_role_bindings=True
        )

    generators = {n: make_generator(CONFIGS[n][0], CONFIGS[n][1]) for n in names}
    pipeline = ProofPipeline(
        generator=generators[names[0]], verifier=verifier,
        artifact_store=__import__("pals_agent.artifacts", fromlist=["x"]).FileArtifactStore(
            args.out / "art"
        ),
    )
    original_prompt = generator_module._direct_prove_prompt_for
    meter = run_stages.Meter(args.spend_ledger, args.out.name, args.max_usd, args.total_cap)
    prompts: dict[str, str] = {}

    for pid, name, _rep in interleaved_schedule(list(by_id), names, 1, args.seed):
        if meter.exhausted():
            print("budget reached; stopping", flush=True)
            break
        model, effort, short = CONFIGS[name]
        meter.arm = name
        problem = by_id[pid]
        request = pipeline.prepare_statement(
            statement=problem["statement"], formal_statement=problem.get("fixed_lean_statement")
        )
        if short:
            generator_module._direct_prove_prompt_for = (  # type: ignore[assignment]
                lambda req, draft: original_prompt(req, draft) + SHORT
            )
        usage: list[dict[str, Any]] = []
        started = time.monotonic()
        try:
            with usage_scope(lambda row: (usage.append(row), meter.add(row))):
                generated = generators[name].generate_direct_proof(request, None)
        finally:
            generator_module._direct_prove_prompt_for = original_prompt  # type: ignore[assignment]
        model_s = time.monotonic() - started
        code = generated.lean_code
        preflight = (
            validate_generated_lean(request, code, require_single_target=False)
            if code.strip() else []
        )
        verify_s = 0.0
        success = False
        errors = len([d for d in preflight if d.severity == "error"])
        if code.strip() and not errors:
            started = time.monotonic()
            result = verifier.verify(code)
            verify_s = time.monotonic() - started
            success = bool(result.success)
        prompt = generated.prompt or ""
        prompts.setdefault(pid + "|" + name, prompt)
        row = {
            "problem_id": pid,
            "config": name,
            "model": model,
            "effort": effort,
            "model_s": round(model_s, 3),
            "verify_s": round(verify_s, 3),
            "preflight_errors": errors,
            "verified": success,
            "empty": not code.strip(),
            "input_tokens": sum(u["input_tokens"] for u in usage),
            "cached_input_tokens": sum(u.get("cached_input_tokens", 0) for u in usage),
            "output_tokens": sum(u["output_tokens"] for u in usage),
            "reasoning_output_tokens": sum(u.get("reasoning_output_tokens", 0) for u in usage),
            "usd": round(sum(
                estimate_usd(u["model"], u["input_tokens"], u["output_tokens"]) or 0.0
                for u in usage
            ), 5),
            "prompt_chars": len(prompt),
            "code_chars": len(code),
            "resident": resident is not None,
            "load_1m": round(os.getloadavg()[0], 2),
        }
        with (args.out / "matrix.jsonl").open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(
            f"{pid} {name} ok={success} model={row['model_s']}s verify={row['verify_s']}s "
            f"in={row['input_tokens']} cached={row['cached_input_tokens']} "
            f"out={row['output_tokens']} reas={row['reasoning_output_tokens']} "
            f"run_usd={meter.run_usd:.4f}",
            flush=True,
        )
    # Longest common prefix of the prompts of one config across problems (cache friendliness).
    by_config: dict[str, list[str]] = {}
    for key, prompt in prompts.items():
        by_config.setdefault(key.split("|")[1], []).append(prompt)
    prefix_rows = []
    for name, items in by_config.items():
        if len(items) >= 2:
            common = os.path.commonprefix(items)
            prefix_rows.append(
                {"config": name, "prompts": len(items), "common_prefix_chars": len(common),
                 "min_prompt_chars": min(len(i) for i in items)}
            )
    (args.out / "prefix.json").write_text(json.dumps(prefix_rows))
    if resident is not None:
        resident.close()
    print(f"DONE run_usd={meter.run_usd:.4f} session_total={meter.total():.4f}", flush=True)


if __name__ == "__main__":
    main()
