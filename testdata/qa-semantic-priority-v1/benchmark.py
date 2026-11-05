"""Preregistered fixed-output QA repetitions, not generation or production E2E.

Private source artifacts and credentials are explicit inputs. Prepare performs
format/source checks without a provider. Run refuses reuse, drift, retries,
fallbacks, and more than 24 calls; it preserves every response outside Git.
"""

from __future__ import annotations

import argparse
import base64
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

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "testdata/explanation-grounding-v1"
BASELINE = "23e903f682a5cfbd3cc21fd88b50ce6ffba0eccf"
CANDIDATE = "fc7e58b5857921d5fbe3124fec04a547600024c9"
MODEL, CALL_CAP, MAX_BYTES, MAX_OUTPUT = "gpt-6-luna", 24, 80000, 6000
SOURCE_PINS = {
    "baseline": "796d216eb5288e870bebf3b9520a8fccafdb45bf48d9fc67c790a7bbb7abe41b",
    "candidate": "82310b14357c55524edf70ec09cc68b0531dfb834f2f3308e9e83e12f244b8b6",
}
INPUTS = [
    (
        "coprime-positive",
        1,
        "repair",
        "outcome-0-explanation.json",
        "661f26d0d5d588260fe7f14ab6c54bc04788ea04c2e0032373b6bd74b6ddb873",
        "approve: natural-number Euclid proof including zero, with explicit characterization",
    ),
    (
        "energy-positive",
        0,
        "energy",
        "energy-positive.json",
        "4c0821d6383d7a19be0936404d15991d680d4bf193e953e20e569e3436829dd5",
        (
            "approve: decomposition gives a global bound, then "
            "equality/attainment/uniqueness; using the bound is legitimate dependency, "
            "not repeated derivation"
        ),
    ),
    (
        "coprime-missing-result",
        1,
        "controls",
        "outcome-2-explanation.json",
        "b0cf1d96c559864e3cc2efadd2a1bb640fe0f237a5940e7ed7728aa8db91199d",
        (
            "reject specifically the actual generic proof-complete conclusion omitting "
            "the product-divisibility characterization"
        ),
    ),
    (
        "energy-unsupported-bridge",
        0,
        "controls",
        "outcome-0-explanation.json",
        "d69bb57cb2c7cb27bf293995bf33913d8a5dcdee47a3742d1714114496c613bd",
        (
            "reject specifically the unproved normalized Gaussian/negative-log "
            "identification; no invented duplication accusation against the valid "
            "bound/equality steps"
        ),
    ),
]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, value: object) -> None:
    with open(path, "x", encoding="utf-8", opener=lambda p, f: os.open(p, f, 0o600)) as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def response_record(status: int, body: bytes, elapsed: float) -> dict:
    try:
        parsed = json.loads(body)
        parse_status = "json"
    except (ValueError, UnicodeDecodeError, RecursionError):
        parsed, parse_status = None, "invalid_json_or_utf8"
    return {
        "http_status": status,
        "elapsed_seconds": elapsed,
        "body_base64": base64.b64encode(body).decode("ascii"),
        "parse_status": parse_status,
        "response": parsed,
    }


def record_received_response(
    directory: Path, call: int, status: int, body: bytes, elapsed: float
) -> None:
    # Commit a flat, parse-independent envelope first. Any later decoder,
    # serializer or parsed-artifact write failure leaves these original bytes.
    raw_path = directory / f"provider-{call}-raw.json"
    save(
        raw_path,
        {
            "http_status": status,
            "elapsed_seconds": elapsed,
            "body_base64": base64.b64encode(body).decode("ascii"),
        },
    )
    parsed = response_record(status, body, elapsed)
    parsed["raw_envelope_sha256"] = digest(raw_path.read_bytes())
    save(directory / f"provider-{call}.json", parsed)


def module(arm: str, directory: Path):
    name = "pals_agent.qa_repeat_" + arm
    spec = importlib.util.spec_from_file_location(name, directory / (arm + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def prepare(args: argparse.Namespace) -> None:
    args.output.mkdir(mode=0o700, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    corpus_raw = (CORPUS / "corpus.json").read_bytes()
    cases = json.loads(corpus_raw)["cases"]
    for arm, commit in (("baseline", BASELINE), ("candidate", CANDIDATE)):
        raw = subprocess.check_output(
            ["git", "-C", str(ROOT), "show", commit + ":pals_agent/explanations.py"], timeout=10
        )
        if digest(raw) != SOURCE_PINS[arm]:
            raise ValueError("source pin mismatch")
        path = args.output / (arm + ".py")
        path.write_bytes(raw)
        path.chmod(0o600)
    modules = {a: module(a, args.output) for a in SOURCE_PINS}
    inputs = []
    for name, index, origin, filename, expected_hash, rubric in INPUTS:
        raw = (getattr(args, origin) / filename).read_bytes()
        if digest(raw) != expected_hash:
            raise ValueError("saved input pin mismatch")
        payload = json.loads(raw)
        case = cases[index]
        source = (CORPUS / case["source"]).read_bytes()
        prompt_pins = {}
        for arm, mod in modules.items():
            explanation = mod.proof_explanation_from_api(payload, lean_code=source.decode())
            # Private, deterministic new guard is deliberately checked on BOTH inputs;
            # it must not short-circuit any paid QA repetition in this cohort.
            modules["candidate"]._require_local_claim_headers(
                list(explanation.sections), source.decode()
            )
            prompt = mod._output_review_prompt(
                theorem_statement=case["question"],
                lean_code=source.decode(),
                explanation=explanation,
                language=case["language"],
            )
            if len(prompt.encode()) > MAX_BYTES:
                raise ValueError("input exceeds predeclared bound")
            prompt_pins[arm] = digest(prompt.encode())
        save(args.output / (name + ".json"), payload)
        inputs.append(
            {
                "id": name,
                "corpus_case_id": case["id"],
                "case_index": index,
                "saved_sha256": expected_hash,
                "lean_sha256": digest(source),
                "question_sha256": digest(case["question"].encode()),
                "prompt_sha256": prompt_pins,
                "expected": rubric,
                "origin": origin + "/" + filename,
            }
        )
    # Preserve the prior compile/axiom receipts without representing them as new runs.
    evidence = {}
    for name in ("axiom-audit.json", *(c["id"] + ".compile.json" for c in cases)):
        raw = (args.repair / name).read_bytes()
        if json.loads(raw).get("exit_code") != 0:
            raise ValueError("prior Lean evidence did not pass")
        evidence[name] = digest(raw)
        save(args.output / name, json.loads(raw))
    schedule = []
    for repeat in range(1, 4):
        # Four cases rotate; each round has two starts per arm. With three
        # repetitions, each case necessarily has a 2:1/1:2 first-arm split.
        for offset in range(4):
            index = (repeat - 1 + offset) % 4
            arms = ("baseline", "candidate") if (repeat + index) % 2 else ("candidate", "baseline")
            for arm in arms:
                schedule.append({"input_id": inputs[index]["id"], "arm": arm, "repeat": repeat})
    save(
        args.output / "predeclaration.json",
        {
            "schema_version": "pals.semantic-priority-qa-repeat.v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "baseline_commit": BASELINE,
            "candidate_commit": CANDIDATE,
            "source_sha256": SOURCE_PINS,
            "harness_sha256": digest(Path(__file__).read_bytes()),
            "corpus_sha256": digest(corpus_raw),
            "inputs": inputs,
            "prior_lean_evidence_sha256": evidence,
            "order": schedule,
            "provider": "openai",
            "model": MODEL,
            "reasoning_effort": "low",
            "max_output_tokens": MAX_OUTPUT,
            "max_input_bytes": MAX_BYTES,
            "timeout_seconds": 55,
            "max_attempts": 1,
            "planned_calls": CALL_CAP,
            "hard_call_cap": CALL_CAP,
            "cost_cap_usd": 0.97446050,
            "prior_cohort_reserve_usd": 0.02553950,
            "turn_combined_cap_usd": 1,
            "conservative_preflight_bound_usd": CALL_CAP
            * (MAX_BYTES * 0.25 + MAX_OUTPUT * 0.5)
            / 1e6,
            "price_source": "https://developers.openai.com/api/docs/pricing",
            "price_checked_at_utc": "2026-11-05T02:51Z",
            "price_usd_per_million": {"all_input": 0.25, "output": 0.5},
            "unit": (
                "one QA request on an identical fixed explanation; three repetitions per input/arm"
            ),
            "scoring": (
                "Manual rationale adjudication against fixed rubric. Approval is success "
                "only for positive. Rejection is success for negatives only when it "
                "identifies the intended defect without fabricated language, quote, format "
                "or mathematical accusations. Malformed/transport/usage missing are "
                "separate; never impute missing as zero. Record all outcomes including false "
                "approval and over-rejection."
            ),
            "evidence_scoring": (
                "Separately assess each criticism for an actual candidate field path, a "
                "short exact quotation from that field, and an explicit relevant "
                "mathematical or requirement reason. An omission quotes existing conclusion "
                "text, never invented missing words. Duplication needs two actual passages "
                "and the same substantive derivation repeated, not reuse for a new "
                "obligation. Positive approvals have no criticism evidence denominator. "
                "Semantic strict success is scored separately so extra formatting is not "
                "mistaken for improved mathematics."
            ),
            "all_verdict_semantic_evidence": (
                "Separate from semantic verdict correctness and criticism evidence: for "
                "each approval or rejection, check whether rationale gives the actual "
                "explanation.conclusion field path, a short exact quotation of its "
                "existing text, and a relevant explanation of whether it supplies the "
                "requested mathematical result. A missing result must name the absent "
                "requirement without inventing a quotation. This is reporting completeness, "
                "not a substitute for a correct verdict and not a chain-of-thought request."
            ),
            "prior_cohort_comparison": (
                "This is the single additional targeted correction after the fixed prior "
                "24-call grounded-rationale cohort. Prior candidate had 3/3 false approvals "
                "on the missing-result input; all prior raw/results/scoring remain unchanged. "
                "Compare per fixed input with repetitions; neither controls nor repeated "
                "calls become new independent mathematical problems. No further corrective "
                "model trial is authorized if this candidate fails acceptance."
            ),
            "energy_positive_derivation": (
                "From the pinned energy-unsupported-bridge input, remove only its first "
                "unsupported identification sentence; all other fields and exact references "
                "are unchanged. No new model generation."
            ),
            "prior_cache_observation": (
                "Prior cohort responses reported prompt_cache_retention=24h/default tier; "
                "price correspondence to 12h/30m write columns and actual invoice remains "
                "unverified. All-input .25/output .50 is a fixed budget reserve, not an "
                "invoice."
            ),
            "limits": (
                "Fixed outputs, four controls, one model/settings; repeats measure QA "
                "stability only, not independent problems, generation accuracy, broad math "
                "accuracy or production E2E. No source changes/retries/repair/fallback."
            ),
        },
    )
    print(
        json.dumps(
            {
                "prepared": True,
                "prereg_sha256": digest((args.output / "predeclaration.json").read_bytes()),
                "planned_calls": 24,
                "upper_bound_usd": 0.552,
            }
        ),
        flush=True,
    )


def run(args: argparse.Namespace) -> None:
    raw = (args.output / "predeclaration.json").read_bytes()
    if digest(raw) != args.prereg_sha256:
        raise ValueError("preregistration mismatch")
    declaration = json.loads(raw)
    if (
        digest(Path(__file__).read_bytes()) != declaration["harness_sha256"]
        or digest((CORPUS / "corpus.json").read_bytes()) != declaration["corpus_sha256"]
    ):
        raise ValueError("harness/corpus drift")
    for arm, expected in SOURCE_PINS.items():
        if digest((args.output / (arm + ".py")).read_bytes()) != expected:
            raise ValueError("source drift")
    for case in declaration["inputs"]:
        if digest((args.output / (case["id"] + ".json")).read_bytes()) != case["saved_sha256"]:
            raise ValueError("input drift")
    save(args.output / "run-started.json", {"utc": datetime.now(UTC).isoformat()})
    sys.path.insert(0, str(ROOT))
    from pals_agent.http_transport import HardDeadlineHttpTransport
    from pals_agent.openai import OpenAIResponsesClient
    from pals_agent.usage import capture_usage

    config = {}
    for line in args.credential_file.read_text().splitlines():
        match = re.match(r"(?:export\s+)?(OPENAI_API_KEY)\s*=\s*(.*)", line)
        if match:
            config[match[1]] = match[2].strip().strip('"').strip("'")
    if not config.get("OPENAI_API_KEY"):
        raise ValueError("existing local official-endpoint credentials required")

    class Transport:
        calls = 0

        def request(self, **kwargs):
            payload = json.loads(kwargs["body"])
            if self.calls >= CALL_CAP or len(payload["input"].encode()) > MAX_BYTES:
                raise ValueError("hard QA call/input cap")
            if (
                payload["model"] != MODEL
                or payload["max_output_tokens"] != MAX_OUTPUT
                or payload.get("reasoning") != {"effort": "low"}
                or payload.get("service_tier") != "default"
                or payload.get("store") is not False
                or kwargs["url"] != "https://api.openai.com/v1/responses"
            ):
                raise ValueError("settings mismatch")
            self.calls += 1
            save(
                args.output / f"call-{self.calls}-reserved.json",
                {"utc": datetime.now(UTC).isoformat(), "payload_sha256": digest(kwargs["body"])},
            )
            start = time.monotonic()
            response = HardDeadlineHttpTransport().request(**kwargs)
            record_received_response(
                args.output,
                self.calls,
                response.status_code,
                response.body,
                time.monotonic() - start,
            )
            return response

    transport = Transport()

    class Client:
        def generate(self, **kwargs):
            return OpenAIResponsesClient(
                api_key=config["OPENAI_API_KEY"],
                base_url="https://api.openai.com/v1",
                timeout_seconds=55,
                max_output_tokens=MAX_OUTPUT,
                reasoning_effort="low",
                transport=transport,
            ).generate(**kwargs, store=False)

    modules = {a: module(a, args.output) for a in SOURCE_PINS}
    cases = json.loads((CORPUS / "corpus.json").read_bytes())["cases"]
    inputs = {x["id"]: x for x in declaration["inputs"]}
    outcomes = []
    for task in declaration["order"]:
        item = inputs[task["input_id"]]
        case, mod = cases[item["case_index"]], modules[task["arm"]]
        source = (CORPUS / case["source"]).read_text()
        if digest(source.encode()) != item["lean_sha256"]:
            raise ValueError("Lean source drift")
        explanation = mod.proof_explanation_from_api(
            json.loads((args.output / (item["id"] + ".json")).read_bytes()), lean_code=source
        )
        prompt = mod._output_review_prompt(
            theorem_statement=case["question"],
            lean_code=source,
            explanation=explanation,
            language=case["language"],
        )
        if digest(prompt.encode()) != item["prompt_sha256"][task["arm"]]:
            raise ValueError("QA prompt drift")
        row = {**task, "started_at_utc": datetime.now(UTC).isoformat(), "decision": "not_run"}
        start, before = time.monotonic(), transport.calls
        with capture_usage() as usage:
            try:
                review = mod.LeanGroundedOutputReviewer(
                    client=Client(), model=MODEL, provider="openai", max_attempts=1
                ).review_explanation(
                    theorem_statement=case["question"],
                    lean_code=source,
                    explanation=explanation,
                    language=case["language"],
                    deadline=time.monotonic() + 55,
                    timeout_seconds=55,
                )
                row["decision"] = "approved"
                save(args.output / f"review-{len(outcomes)}.json", asdict(review))
            except Exception as error:
                row["exception"] = type(error).__name__
                row["decision"] = getattr(error, "category", "not_run")
                row["validation_failures"] = getattr(error, "attempt_failures", None)
                save(
                    args.output / f"review-{len(outcomes)}.json",
                    {
                        "rationale": getattr(error, "rationale", ""),
                        "attempt_outputs": getattr(error, "attempt_outputs", ()),
                    },
                )
            row["usage"] = usage
        row.update(
            elapsed_seconds=time.monotonic() - start,
            finished_at_utc=datetime.now(UTC).isoformat(),
            provider_calls=transport.calls - before,
        )
        row["usage_missing"] = row["provider_calls"] != len(usage) or row["provider_calls"] != 1
        row["conservative_cost_usd"] = (
            None
            if row["usage_missing"]
            else sum((u["input_tokens"] * 0.25 + u["output_tokens"] * 0.5) / 1e6 for u in usage)
        )
        outcomes.append(row)
        save(args.output / f"outcome-{len(outcomes) - 1}.json", row)
        print(json.dumps({k: v for k, v in row.items() if k != "usage"}), flush=True)
    save(args.output / "outcomes.json", outcomes)
    print(
        json.dumps(
            {
                "finished": True,
                "calls": transport.calls,
                "usage_missing_rows": sum(r["usage_missing"] for r in outcomes),
            }
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--repair", type=Path)
    parser.add_argument("--energy", type=Path)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--prereg-sha256")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.controls is None or args.repair is None or args.energy is None:
            parser.error(
                "prepare requires prior controls/repair and pinned energy-positive directories"
            )
        prepare(args)
    else:
        if args.credential_file is None or args.prereg_sha256 is None:
            parser.error("run requires credentials and exact preregistration SHA")
        run(args)


if __name__ == "__main__":
    main()
