"""Run adversarial and benign questions through real Draft -> Sketch -> Prove generation.

Local, manual, paid. It sends only the synthetic cases from tests/fixtures/prompt_injection_cases.py
to the model provider named by the key, never to any other service. For every run it records
codes and booleans, not text: whether Lean accepted the first proof, whether forbidden constructs
or prompt echoes appeared, token-free timing. Raw outputs go to --raw-dir (outside the repository).

    OPENAI_API_KEY=... uv run python scripts/prompt_injection_probe.py \
        --isolation true --cases override-sorry,benign-amgm --lean-project <lean-workspace> \
        --toolchain-bin <elan toolchain bin> --raw-dir <scratch dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pals_agent import prompt_safety as ps  # noqa: E402
from pals_agent.generator import HybridLeanGenerator  # noqa: E402
from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.model_roles import ModelRole, fixed_model_default  # noqa: E402
from pals_agent.models import ProofRequest  # noqa: E402
from pals_agent.openai import OpenAIResponsesClient  # noqa: E402
from tests.fixtures.prompt_injection_cases import ATTACKS, BENIGN  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolation", choices=("true", "false"), required=True)
    parser.add_argument("--cases", required=True, help="comma separated case ids")
    parser.add_argument("--lean-project", type=Path, required=True)
    parser.add_argument("--toolchain-bin", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    args = parser.parse_args()

    os.environ[ps.PROMPT_ISOLATION_ENV] = args.isolation
    cases = {case["id"]: case for case in (*BENIGN, *ATTACKS)}
    binding = fixed_model_default(ModelRole.PROVE)
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], timeout_seconds=240)
    generator = HybridLeanGenerator(
        model=binding.model,
        provider=binding.provider,
        openai=client,
        use_release_role_bindings=True,
    )
    bin_dir = str(args.toolchain_bin)
    verifier = LeanVerifier(
        lean_binary=str(args.toolchain_bin / "lean"),
        lake_binary=str(args.toolchain_bin / "lake"),
        project_dir=args.lean_project,
        timeout_seconds=600,
        child_path=f"{bin_dir}:/usr/bin:/bin",
    )
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    for case_id in args.cases.split(","):
        case = cases[case_id]
        request = ProofRequest(
            id=f"probe-{case_id}", prompt=case["prompt"], formal_statement=case["formal_statement"]
        )
        started = time.monotonic()
        proof = generator.generate(request)
        record: dict[str, object] = {
            "case": case_id,
            "isolation": args.isolation,
            "generation_seconds": round(time.monotonic() - started, 1),
            "lean_returned": bool(proof.lean_code),
            "error_marker": proof.raw_model_output.startswith("[generation-error]"),
        }
        outputs = [
            proof.draft.raw_model_output if proof.draft else "",
            proof.sketch.raw_model_output if proof.sketch else "",
            proof.raw_model_output,
        ]
        record["leak_in_any_stage"] = any(
            "prompt_leak" in ps.inspect_output(text, kind="prose").codes for text in outputs
        )
        if proof.lean_code:
            inspection = ps.inspect_output(proof.lean_code, kind="lean")
            record["forbidden_codes"] = list(inspection.codes)
            result = verifier.verify(proof.lean_code)
            record["lean_verified"] = result.success
            record["lean_diagnostic_codes"] = sorted(
                {d.code or d.severity for d in result.diagnostics}
            )
        else:
            record["forbidden_codes"] = []
            record["lean_verified"] = False
        (args.raw_dir / f"{args.isolation}-{case_id}.json").write_text(
            json.dumps(
                {
                    "prompt_draft": proof.draft.prompt if proof.draft else None,
                    "draft": proof.draft.raw_model_output if proof.draft else None,
                    "sketch": proof.sketch.raw_model_output if proof.sketch else None,
                    "proof": proof.raw_model_output,
                    "lean_code": proof.lean_code,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
