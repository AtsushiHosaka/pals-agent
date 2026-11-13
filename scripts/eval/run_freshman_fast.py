"""freshman-v1 `dev_unseen`: the fast path beside the normal path, on the confined resident Lean.

For each item the fast path (FastAnswer: merged calls, race, gate, explanation, and the EXISTING
explanation review) runs under ``run_with_fallback`` against a REPLAY of the normal path measured
earlier for the same item (``--normal-records``): the replay finishes after the normal path's
measured time and bills its measured spend.  Running the real normal pipeline a second time
would double the cost; the replay keeps the claim/cancel/deadline logic real and the normal
time and cost measured.  Reported per item: fast outcome and reason, seconds to verified and to
shown, the winner and the total, and the usd of both paths.

Safety: the input must be a manifest that contains ONLY dev_unseen or tuning items (never
held_out), built from docs/generation-eval-freshman-v1/manifest.json; any other split aborts
before any call.

    python scripts/eval/run_freshman_fast.py --manifest DEV.json --out DIR --normal-log LOG ...
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/eval"))

from run_fast_variants import Recorder, instrumented_model  # noqa: E402

from pals_agent import fast_answer as fa  # noqa: E402
from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean  # noqa: E402
from pals_agent.lean_verifier.resident.manager import default_read_roots  # noqa: E402


def normal_replay(log: Path, records: Path | None) -> dict[str, dict]:
    """Per item: the normal path's measured seconds to answer and its spend (from its run log)."""
    pattern = re.compile(
        r"^(\S+) base r\d+ ok=(\w+) first=(\w+) repairs=(\d+) wall=([\d.]+) "
        r"answer=([\w.]+) run_usd=([\d.]+)"
    )
    out: dict[str, dict] = {}
    previous = 0.0
    for line in log.read_text().splitlines():
        m = pattern.match(line)
        if not m:
            continue
        usd = float(m.group(7))
        answer = None if m.group(6) == "None" else float(m.group(6))
        out[m.group(1)] = {
            "ok": m.group(2) == "True",
            "repairs": int(m.group(4)),
            "wall_s": float(m.group(5)),
            "answer_s": answer if answer is not None else float(m.group(5)),
            "usd": round(usd - previous, 6),
        }
        previous = usd
    return out


def make_replay(n: dict, forward_usage):  # type: ignore[no-untyped-def]
    """The fallback callback that replays one recorded normal-path run.

    A recorded failure (``ok`` False) ends after its recorded time with NO answer, so it can
    neither win the race nor produce an answer time.
    """
    import time as _time  # noqa: PLC0415

    def replay(cancel, deadline, claim):  # type: ignore[no-untyped-def]
        forward_usage(
            [{"model": "normal-replay", "input_tokens": 0, "output_tokens": 0, "usd": n["usd"]}]
        )
        end = _time.monotonic() + n["answer_s"]
        while _time.monotonic() < min(end, deadline):
            if cancel.is_set():
                return None
            _time.sleep(0.02)
        if not n.get("ok", False) or _time.monotonic() >= deadline:
            return None
        return "normal answer (replayed)"

    return replay


def main() -> None:
    from formalise import load_key  # noqa: PLC0415

    from pals_agent.evals.runner import estimate_usd  # noqa: PLC0415
    from pals_agent.usage import forward_usage  # noqa: PLC0415

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--normal-log", type=Path, required=True)
    parser.add_argument("--calls", type=int, default=3)
    parser.add_argument("--max-usd", type=float, default=0.5)
    parser.add_argument("--deadline", type=float, default=600.0)
    parser.add_argument("--no-fallback", action="store_true")
    parser.add_argument("--explanation-retries", type=int, default=0)
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--request-root", type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    problems = json.loads(args.manifest.read_text())["problems"]
    if not problems or any(p.get("split") not in {"dev_unseen", "tuning"} for p in problems):
        raise SystemExit("refusing: the manifest must hold dev_unseen or tuning items only")
    if any(not p["id"].startswith("fy1-") for p in problems) or len(problems) > 20:
        raise SystemExit("refusing: not the dev_unseen set")
    normal = normal_replay(args.normal_log, None)
    lean, lake = f"{args.toolchain}/bin/lean", f"{args.toolchain}/bin/lake"
    lean_path = subprocess.run(
        [lake, "env", "printenv", "LEAN_PATH"],
        cwd=args.project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    resident = ResidentLean(
        ResidentConfig(
            lean_binary=lean,
            lean_path=lean_path,
            build_dir=args.out / "resident",
            project_dir=args.project,
            max_children=8,
            queue_timeout_s=30.0,
            warm_exact=True,
            confine=sys.platform.startswith("linux"),
            request_root=args.request_root,
            read_roots=default_read_roots(lean, lean_path),
            startup_timeout_s=240,
        )
    )
    print("resident startup s", round(resident.start(), 2), flush=True)
    verifier = LeanVerifier(
        lean_binary=lean,
        lake_binary=lake,
        project_dir=args.project,
        child_path=f"{args.toolchain}/bin:/usr/bin:/bin",
        elan_home=os.environ.get("ELAN_HOME", str(Path.home() / ".elan")),
        scratch_dir=args.request_root,
        timeout_seconds=120.0,
        resident=resident,
    )
    key = load_key(None)
    recorder = Recorder()
    model = instrumented_model(key, recorder, "gpt-6-luna:none", {})
    from pals_agent.model_roles import ModelRole, fixed_model_default  # noqa: PLC0415
    from pals_agent.openai import OpenAIResponsesClient  # noqa: PLC0415

    binding = fixed_model_default(ModelRole.EXPLAIN)
    review_client = dataclasses.replace(
        OpenAIResponsesClient(api_key=key, timeout_seconds=60.0, max_output_tokens=3000),
        reasoning_effort=binding.reasoning_effort,
    )
    fast = fa.FastAnswer(
        resident,
        verifier,
        model,
        args.request_root,
        calls=args.calls,
        gate_mode="terse2",
        explanation_reviewer=fa.existing_explanation_reviewer(review_client),
        explanation_retries=args.explanation_retries,
    )
    spent = [0.0]
    lock = threading.Lock()

    def add(row: dict) -> None:
        with lock:
            spent[0] += estimate_usd(row["model"], row["input_tokens"], row["output_tokens"]) or 0.0

    rows = []
    with (args.out / f"{args.name}.jsonl").open("a") as fh:
        for p in problems:
            if spent[0] >= args.max_usd:
                print("budget reached", round(spent[0], 4), flush=True)
                break
            if p["id"] not in normal:
                raise SystemExit(f"no normal-path record for {p['id']}: refusing to guess")
            n = normal[p["id"]]
            recorder.reset()

            replay = make_replay(n, forward_usage)

            start_spent = spent[0]
            from pals_agent.usage import usage_scope  # noqa: PLC0415

            with usage_scope(add):
                if args.no_fallback:
                    t0 = time.monotonic()
                    r = fast.run(p["statement"], p["language"])
                    race = None
                    ledger_rows = []
                    total = time.monotonic() - t0
                else:
                    race = fa.run_with_fallback(
                        fast, p["statement"], p["language"], replay, deadline_s=args.deadline
                    )
                    r = race.fast
                    total = race.seconds["total"]
                    ledger_rows = race.settle(60.0)
            time.sleep(0.5)
            if race is not None:
                fast_usd = sum(
                    estimate_usd(x["model"], x["input_tokens"], x["output_tokens"]) or 0.0
                    for x in ledger_rows
                    if x["model"] != "normal-replay"
                )
                with lock:
                    spent[0] += fast_usd
            else:
                fast_usd = spent[0] - start_spent
            row = {
                "id": p["id"],
                "field": p["field"],
                "tier": p["tier"],
                "language": p["language"],
                "trivial": p.get("trivial"),
                "request": p["statement"],
                "expected_conclusion": p.get("expected_conclusion"),
                "fast_outcome": r.outcome if r else None,
                "fast_reason": r.reason if r else None,
                "kind": r.kind if r else None,
                "answer": r.answer if r else None,
                "tactic": r.tactic if r else None,
                "formal": r.formal if r else None,
                "proved": r.proved if r else None,
                "explanation": r.explanation if r else None,
                "explanation_approved": r.explanation_approved if r else None,
                "explanation_issue": r.explanation_issue if r else None,
                "gate": None
                if not r or r.gate is None
                else {
                    "passed": r.gate.passed,
                    "reasons": r.gate.reasons,
                },
                "fast_seconds": r.seconds if r else None,
                "attempt_log": r.attempt_log if r else None,
                "statements": r.statements if r else None,
                "winner": race.winner if race else ("fast" if r.outcome == "answered" else "none"),
                "total_s": round(total, 3),
                "fast_usd": round(fast_usd, 6),
                "normal": n,
                "calls": list(recorder.events),
            }
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(
                p["id"][:40],
                row["fast_outcome"],
                row["fast_reason"],
                row["winner"],
                row["total_s"],
                flush=True,
            )
    print(f"spend_est_usd={spent[0]:.4f}", flush=True)
    resident.close()


if __name__ == "__main__":
    main()
