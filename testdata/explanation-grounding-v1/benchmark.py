"""Bounded, preregistered local explanation comparison; never uses a worker queue.

Run prepare first, inspect its JSON, then run with its exact SHA256. Raw responses
and credentials stay outside Git. Re-running an output directory is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
REPOSITORY = CORPUS_DIR.parents[1]
BASELINE = "7f17c526aec5d4d341fbbb7cc034ac33ec28f000"
MODEL = "gpt-6-luna"
MAX_CALLS, MAX_BYTES, MAX_OUTPUT = 24, 80000, 6000


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, value: object) -> None:
    with open(path, "x", encoding="utf-8", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def source_snapshot() -> dict[str, str]:
    return {
        "candidate": digest((REPOSITORY / "pals_agent/explanations.py").read_bytes()),
        "harness": digest(Path(__file__).read_bytes()),
        "corpus": digest((CORPUS_DIR / "corpus.json").read_bytes()),
        **{p.name: digest(p.read_bytes()) for p in CORPUS_DIR.glob("*.lean")},
    }


def prepare(args: argparse.Namespace) -> None:
    args.output.mkdir(mode=0o700, exist_ok=False)
    corpus = json.loads((CORPUS_DIR / "corpus.json").read_bytes())
    manifest = json.loads((args.lean_project / "lake-manifest.json").read_bytes())
    packages = args.lean_project / manifest.get("packagesDir", ".lake/packages")
    libs = [packages / x["name"] / ".lake/build/lib/lean" for x in manifest["packages"]]
    env = {**os.environ, "LEAN_PATH": ":".join(str(x) for x in libs if x.is_dir())}
    version = subprocess.check_output([str(args.lean), "--version"], timeout=10).decode()
    if "version 4.32.0-rc1" not in version:
        raise ValueError("wrong Lean version")
    revision = subprocess.check_output(
        ["git", "-C", str(packages / "mathlib"), "rev-parse", "HEAD"], timeout=10
    ).decode().strip()
    if revision != corpus["mathlib_revision"]:
        raise ValueError("wrong mathlib revision")
    audit = "import Mathlib\n"
    cases = []
    for case in corpus["cases"]:
        raw = (CORPUS_DIR / case["source"]).read_bytes()
        if re.search(rb"\b(?:sorry|admit|axiom|unsafe)\b", raw):
            raise ValueError("untrusted proof source")
        started = time.monotonic()
        run = subprocess.run(
            [str(args.lean), str(CORPUS_DIR / case["source"])],
            env=env, capture_output=True, timeout=90, check=False,
        )
        save(args.output / (case["id"] + ".compile.json"), {
            "exit_code": run.returncode, "seconds": time.monotonic() - started,
            "stdout": run.stdout.decode(), "stderr": run.stderr.decode(),
        })
        if run.returncode:
            raise ValueError("Lean compile failed; inspect private diagnostic")
        audit += re.sub(r"^import [^\n]+\n", "", raw.decode(), flags=re.M) + "\n"
        cases.append({"id": case["id"], "lean_sha256": digest(raw),
                      "question_sha256": digest(case["question"].encode()),
                      "expected": case["expected"]})
    audit += "\n".join("#print axioms " + c["target"] for c in corpus["cases"]) + "\n"
    audit_path = args.output / "Axioms.lean"
    audit_path.write_text(audit)
    audit_path.chmod(0o600)
    run = subprocess.run([str(args.lean), str(audit_path)], env=env,
                         capture_output=True, timeout=90, check=False)
    diagnostic = (run.stdout + run.stderr).decode()
    if run.returncode:
        raise ValueError("axiom audit compile failed")
    for case in corpus["cases"]:
        match = re.search(re.escape("'" + case["target"] + "' depends on axioms: [")
                          + r"([^]]*)\]", diagnostic)
        if not match or not set(x.strip() for x in match[1].split(",")) <= {
            "propext", "Classical.choice", "Quot.sound",
        }:
            raise ValueError("unexpected axioms")
    save(args.output / "axiom-audit.json", {"output": diagnostic, "exit_code": 0,
         "source_sha256": digest(audit.encode()), "lean_version": version.strip(),
         "mathlib_revision": revision})
    baseline = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "show", BASELINE + ":pals_agent/explanations.py"],
        timeout=10,
    )
    for arm, raw in {"baseline": baseline, "candidate": (
        REPOSITORY / "pals_agent/explanations.py").read_bytes()}.items():
        path = args.output / (arm + ".py")
        path.write_bytes(raw)
        path.chmod(0o600)
    declaration = {
        "schema_version": "pals.explanation-grounding-comparison.v1",
        "created_at_utc": datetime.now(UTC).isoformat(), "baseline_commit": BASELINE,
        "source_sha256": {**source_snapshot(), "baseline": digest(baseline)},
        "cases": cases, "provider": "openai", "model": MODEL,
        "reasoning_effort": "low", "max_output_tokens": MAX_OUTPUT,
        "max_input_bytes": MAX_BYTES, "timeout_seconds": 55, "max_attempts": 1,
        "planned_calls": 4 if args.repair_followup else 6 if args.controls_only else 14,
        "prior_task_calls": args.prior_calls, "hard_task_call_cap": MAX_CALLS,
        "hard_remaining_call_cap": MAX_CALLS - args.prior_calls, "cost_cap_usd": 1,
        "upper_bound_usd": MAX_CALLS * (MAX_BYTES * .25 + MAX_OUTPUT * .50) / 1e6,
        "price_source": "https://developers.openai.com/api/docs/pricing",
        "price_checked_at_utc": "2026-11-04T15:56Z",
        "conservative_usd_per_million": {"all_input": .25, "output": .50},
        "order": [[1, "candidate"]] if args.repair_followup else (
            [] if args.controls_only else [[0, "baseline"], [0, "candidate"],
                                          [1, "candidate"], [1, "baseline"]]),
        "repair_followup": args.repair_followup,
        "rubric": {
            "pipeline": "one generation + matching-arm QA if valid; no retry or fallback",
            "references": "exact original excerpts; fixed corpus header ranges in one section",
            "conclusion": "manual fixed expected full formula/characterization; no mere proved",
            "soundness": "manual fixed derivation/hypotheses; no unsupported object bridge",
            "ending": "no complete final answer repeated in last section and conclusion",
            "controls": {
                "unsupported-bridge": "reject invented Gaussian/exponential identification",
                "missing-result": "reject generic conclusion omitting product characterization",
                "missing-header": "reject otherwise sound source with multiline headers omitted",
            },
        },
        "limits": "n=2 one draw/arm; QA is same model, not independent correctness proof; "
                  "controls are fixed authored negative inputs, not generated successes; "
                  "dual-number exponential identification itself is not formalized here",
    }
    if args.repair_followup:
        saved = args.previous_output / "outcome-1-explanation.json"
        declaration["saved_positive_input"] = {"path": str(saved),
                                                "sha256": digest(saved.read_bytes())}
    save(args.output / "predeclaration.json", declaration)
    print(json.dumps({"prepared": True, "predeclaration_sha256": digest(
        (args.output / "predeclaration.json").read_bytes()), "upper_bound_usd":
        declaration["upper_bound_usd"], "cases": cases}), flush=True)


def load_module(arm: str, directory: Path):
    name = "pals_agent.grounding_benchmark_" + arm
    spec = importlib.util.spec_from_file_location(name, directory / (arm + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def control(module, case: dict, name: str):
    """Explicit authored QA negatives; never represented as actual generated output."""
    source = (CORPUS_DIR / case["source"]).read_text()
    lines = source.splitlines()
    if name == "missing-result":
        paragraphs = [("Factor the common multiple", "Suppose $a\\mid n$ and $b\\mid n$. "
                       "Write $n=ak$ for a natural number $k$. Since $a$ and $b$ are coprime, "
                       "Euclid's lemma gives $b\\mid k$ from $b\\mid ak$. Thus $k=bq$ for "
                       "a natural number $q$, and $n=(ab)q$.", 8, 15),
                      ("Reverse implication", "Conversely, if $ab\\mid n$, each factor "
                       "divides $ab$, so transitivity gives $a\\mid n$ and $b\\mid n$. "
                       "Both arguments use natural-number quotients and include zero cases "
                       "without adding positivity assumptions.", 16, 19)]
        overview, conclusion = (
            "Fix coprime natural numbers $a,b$ and a natural number $n$, including zero.",
            "This completes both directions of the required proof.")
    else:
        first_start = 21 if name == "missing-header" else 18
        second_start = 32 if name == "missing-header" else 30
        paragraphs = [("平方を完成する", "$q=(a+b+c)/3$、"
                       "$m=((a-b)^2+(b-c)^2+(c-a)^2)/3$とおく。"
                       "定義した和を分配法則で展開して整理すると、$E(t)=3(t-q)^2+m$となる。"
                       "平方の非負性から、任意の実数$t$で$E(t)\\ge m$である。", first_start, 26),
                      ("等号を調べる", "$E(t)=m$ならば$3(t-q)^2=0$となる。"
                       "$3>0$なので$(t-q)^2=0$、したがって$t=q$である。"
                       "逆に$t=q$を代入すると平方項がゼロになり、下界に一致する。",
                       second_start, 36)]
        overview = "実数$a,b,c$を任意に固定し、実数$t$について"
        overview += "$E(t)=(t-a)^2+(t-b)^2+(t-c)^2$とする。"
        if name == "unsupported-bridge":
            title, summary, _, end = paragraphs[0]
            paragraphs[0] = (title, "定義式だけから、$E$はガウス確率密度の負の対数と同一であり、"
                             "$\\exp(-E(t))$が正規化された確率密度だと証明される。" + summary,
                             6, end)
        conclusion = "最小値は$((a-b)^2+(b-c)^2+(c-a)^2)/3$であり、"
        conclusion += "これを達成する実数は$t=(a+b+c)/3$だけである。"
    sections = tuple(module.ExplanationSection(
        id="step-" + str(i), title=title, summary=summary,
        references=(module.LeanLineReference(start, end, "\n".join(lines[start-1:end])),),
    ) for i, (title, summary, start, end) in enumerate(paragraphs, 1))
    return module.ProofExplanation(overview=overview, sections=sections, conclusion=conclusion,
        model="authored-negative-control", provider="synthetic", prompt="", raw_model_output="",
        elapsed_ms=0)


def run(args: argparse.Namespace) -> None:
    raw = (args.output / "predeclaration.json").read_bytes()
    if digest(raw) != args.predeclaration_sha256:
        raise ValueError("predeclaration pin mismatch")
    declaration = json.loads(raw)
    if any(declaration["source_sha256"][k] != v for k, v in source_snapshot().items()):
        raise ValueError("source changed since preregistration")
    save(args.output / "run-started.json", {"utc": datetime.now(UTC).isoformat()})
    sys.path.insert(0, str(REPOSITORY))
    from pals_agent.http_transport import HardDeadlineHttpTransport
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.usage import capture_usage

    config = {}
    for line in args.credential_file.read_text().splitlines():
        match = re.match(r"(?:export\s+)?(OPENAI_API_KEY|PALS_OPENAI_BASE_URL)\s*=\s*(.*)", line)
        if match:
            config[match[1]] = match[2].strip().strip('"').strip("'")
    if not config.get("OPENAI_API_KEY") or config.get(
        "PALS_OPENAI_BASE_URL") != "https://api.openai.com/v1":
        raise ValueError("explicit existing local credentials/official endpoint required")

    class Transport:
        calls = 0

        def request(self, **kwargs):
            payload = json.loads(kwargs["body"])
            if (self.calls >= declaration["hard_remaining_call_cap"]
                    or len(payload["input"].encode()) > MAX_BYTES):
                raise ValueError("predeclared call/input budget exhausted")
            if (payload["model"] != MODEL or payload["max_output_tokens"] != MAX_OUTPUT
                    or payload.get("reasoning") != {"effort": "low"}
                    or payload.get("service_tier") != "default" or payload.get("store") is not False
                    or kwargs["url"] != "https://api.openai.com/v1/responses"):
                raise ValueError("model/settings/endpoint mismatch")
            self.calls += 1
            save(args.output / f"call-{self.calls}-reserved.json", {
                "utc": datetime.now(UTC).isoformat(), "payload_sha256": digest(kwargs["body"]),
            })
            started = time.monotonic()
            response = HardDeadlineHttpTransport().request(**kwargs)
            save(args.output / f"provider-{self.calls}.json", {
                "http_status": response.status_code, "elapsed_seconds": time.monotonic() - started,
                "response": json.loads(response.body),
            })
            return response

    transport = Transport()

    class Client:
        def generate(self, **kwargs):
            return OpenAIResponsesClient(api_key=config["OPENAI_API_KEY"],
                base_url=config["PALS_OPENAI_BASE_URL"], timeout_seconds=55,
                max_output_tokens=MAX_OUTPUT, reasoning_effort="low", transport=transport,
            ).generate(**kwargs, store=False)

    modules = {arm: load_module(arm, args.output) for arm in ("baseline", "candidate")}
    cases = json.loads((CORPUS_DIR / "corpus.json").read_bytes())["cases"]
    tasks = [(index, arm, "pipeline") for index, arm in declaration["order"]]
    if declaration["repair_followup"]:
        tasks += [(0, "candidate", "saved-positive"), (1, "candidate", "missing-result"),
                  (0, "candidate", "missing-header")]
    else:
        tasks += [(index, arm, kind) for kind, index in [
            ("unsupported-bridge", 0), ("missing-result", 1), ("missing-header", 0),
        ] for arm in ("baseline", "candidate")]
    outcomes = []
    for index, arm, kind in tasks:
        module, case = modules[arm], cases[index]
        row = {"case_id": case["id"], "arm": arm, "kind": kind,
               "started_at_utc": datetime.now(UTC).isoformat(), "review": "not_run"}
        started = time.monotonic()
        calls_before = transport.calls
        with capture_usage() as usage:
            try:
                source = (CORPUS_DIR / case["source"]).read_text()
                if kind == "pipeline":
                    explanation = module.LeanProofExplainer(client=Client(), model=MODEL,
                        provider="openai", max_attempts=1).explain(
                        theorem_statement=case["question"], lean_code=source, verified=True,
                        language=case["language"], deadline=time.monotonic()+55, timeout_seconds=55)
                    row["validated_generation"] = True
                elif kind == "saved-positive":
                    saved = declaration["saved_positive_input"]
                    raw = Path(saved["path"]).read_bytes()
                    if digest(raw) != saved["sha256"]:
                        raise ValueError("saved positive input pin mismatch")
                    explanation = module.proof_explanation_from_api(
                        json.loads(raw), lean_code=source)
                else:
                    explanation = control(module, case, kind)
                save(args.output / f"outcome-{len(outcomes)}-explanation.json", asdict(explanation))
                review = module.LeanGroundedOutputReviewer(client=Client(), model=MODEL,
                    provider="openai", max_attempts=1).review_explanation(
                    theorem_statement=case["question"], lean_code=source, explanation=explanation,
                    language=case["language"], deadline=time.monotonic()+55, timeout_seconds=55)
                row["review"] = "approved"
                save(args.output / f"outcome-{len(outcomes)}-review.json", asdict(review))
            except Exception as error:
                row["exception"] = type(error).__name__
                row["validation_failures"] = getattr(error, "attempt_failures", None)
                row["review"] = getattr(error, "category", "not_run")
                save(args.output / f"outcome-{len(outcomes)}-failure.json", {
                    "rationale": getattr(error, "rationale", ""),
                    "attempt_outputs": getattr(error, "attempt_outputs", ()),
                })
            row["usage"] = usage
        row["elapsed_seconds"] = time.monotonic() - started
        row["finished_at_utc"] = datetime.now(UTC).isoformat()
        row["provider_calls"] = transport.calls - calls_before
        row["usage_missing"] = row["provider_calls"] != len(usage)
        row["conservative_cost_usd"] = sum(
            (x["input_tokens"]*.25 + x["output_tokens"]*.50)/1e6 for x in usage
        ) if not row["usage_missing"] else None
        outcomes.append(row)
        save(args.output / f"outcome-{len(outcomes)-1}.json", row)
        print(json.dumps({k: v for k, v in row.items() if k != "usage"}), flush=True)
    save(args.output / "outcomes.json", outcomes)
    print(json.dumps({"finished": True, "provider_calls": transport.calls,
        "conservative_known_cost_usd": sum(x["conservative_cost_usd"] or 0 for x in outcomes),
        "unknown_usage_rows": sum(x["usage_missing"] for x in outcomes)}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lean-project", type=Path)
    parser.add_argument("--lean", type=Path)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--predeclaration-sha256")
    parser.add_argument("--controls-only", action="store_true")
    parser.add_argument("--repair-followup", action="store_true")
    parser.add_argument("--previous-output", type=Path)
    parser.add_argument("--prior-calls", type=int, default=0)
    args = parser.parse_args()
    if args.controls_only and args.repair_followup:
        parser.error("controls-only and repair-followup are exclusive")
    if args.repair_followup and args.previous_output is None:
        parser.error("repair followup requires the preserved previous output")
    planned = 4 if args.repair_followup else 6 if args.controls_only else 14
    if not 0 <= args.prior_calls <= MAX_CALLS - planned:
        parser.error("declared prior task calls leave insufficient call budget")
    if args.action == "prepare":
        if args.lean_project is None or args.lean is None:
            parser.error("prepare requires --lean-project and --lean")
        prepare(args)
    else:
        if args.credential_file is None or args.predeclaration_sha256 is None:
            parser.error("run requires --credential-file and --predeclaration-sha256")
        run(args)


if __name__ == "__main__":
    main()
