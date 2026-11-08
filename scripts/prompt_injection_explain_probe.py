"""Check that enabling prompt isolation does not reject ordinary explanations.

Manual and paid (a few Terra-class calls). Uses fixed, verified Lean proofs of ordinary
inequalities, so the explanation prose naturally contains `<` in mathematics. Records only counts
and codes: whether an explanation was produced and, if not, the failure class. Raw outputs go to
--raw-dir (outside the repository).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pals_agent import prompt_safety as ps  # noqa: E402
from pals_agent.explanations import ExplanationGenerationError, LeanProofExplainer  # noqa: E402
from pals_agent.model_roles import ModelRole, fixed_model_default  # noqa: E402
from pals_agent.openai import OpenAIResponsesClient  # noqa: E402

CASES = {
    "lt-abs": (
        "実数 x, a について |x| < a ならば -a < x < a を示してください。",
        "import Mathlib\n\ntheorem lt_abs_bound (x a : ℝ) (h : |x| < a) : -a < x ∧ x < a := by\n"
        "  exact abs_lt.mp h\n",
    ),
    "unit-interval": (
        "0 < a < 1 を満たす実数 a について a^2 < a を示してください。",
        "import Mathlib\n\ntheorem sq_lt_self_of_unit (a : ℝ) (h0 : 0 < a) (h1 : a < 1) :"
        " a ^ 2 < a := by\n  nlinarith\n",
    ),
    "eps-delta-lt": (
        "x < a を満たす実数 x, a について、a - x > 0 かつ (a - x) / 2 < a - x を示してください。",
        "import Mathlib\n\ntheorem half_gap (x a : ℝ) (h : x < a) :"
        " 0 < a - x ∧ (a - x) / 2 < a - x := by\n  constructor <;> linarith\n",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isolation", choices=("true", "false"), required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    args = parser.parse_args()
    os.environ[ps.PROMPT_ISOLATION_ENV] = args.isolation
    binding = fixed_model_default(ModelRole.EXPLAIN)
    client = OpenAIResponsesClient(
        api_key=os.environ["OPENAI_API_KEY"], timeout_seconds=240, reasoning_effort="low"
    )
    explainer = LeanProofExplainer(
        client=client, model=binding.model, provider=binding.provider, max_attempts=3
    )
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    for case_id, (statement, lean_code) in CASES.items():
        record: dict[str, object] = {"case": case_id, "isolation": args.isolation}
        try:
            result = explainer.explain(
                theorem_statement=statement, lean_code=lean_code, verified=True, language="ja"
            )
            prose = [result.overview, result.conclusion, *(s.summary for s in result.sections)]
            record["explained"] = True
            record["learner_text_violation"] = [ps.learner_text_violation(text) for text in prose]
            record["contains_less_than"] = any("<" in text for text in prose)
            (args.raw_dir / f"explain-{args.isolation}-{case_id}.json").write_text(
                json.dumps(prose, ensure_ascii=False, indent=1)
            )
        except ExplanationGenerationError as exc:
            record["explained"] = False
            record["error_class"] = type(exc).__name__
            record["rejected_by_prompt_safety"] = "prompt safety" in str(exc)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
