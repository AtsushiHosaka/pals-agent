"""Resident Lean vs today's cold verification: latency and verdict equality, no model calls.

Every candidate goes through ``LeanVerifier.verify`` (policy, compile, trusted audit) twice: once
cold (a new ``lake env lean`` for the compile and another for the audit) and once with a resident
worker.  Reported: p50/p90/max seconds for a single caller and for N concurrent callers, the
machine load, and whether every verdict (success flag and diagnostic codes) is identical.

    uv run python scripts/eval/bench_resident.py --out DIR [--concurrency 10] [--repeats 2]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pals_agent.lean import LeanVerifier  # noqa: E402
from pals_agent.lean_verifier.resident import ResidentConfig, ResidentLean  # noqa: E402

HEADER = "import Mathlib\n"
CASES: list[tuple[str, str]] = [
    ("positivity", "theorem c1 (a b : ℝ) : 0 ≤ a ^ 2 + b ^ 2 := by positivity"),
    ("norm_num", "theorem c2 : (17 : ℕ) * 23 = 391 := by norm_num"),
    ("omega", "theorem c3 (n : ℕ) (h : n % 4 = 3) : n % 2 = 1 := by omega"),
    ("linarith", "theorem c4 (a b : ℝ) (h1 : a < b) (h2 : 0 < a) : a / 2 < b := by linarith"),
    (
        "nlinarith",
        "theorem c5 (a b : ℝ) : 2 * a * b ≤ a ^ 2 + b ^ 2 := by nlinarith [sq_nonneg (a - b)]",
    ),
    ("simp", "theorem c6 (s : Finset ℕ) : s ⊆ s := by simp"),
    ("decide", "theorem c7 : Nat.gcd 12 18 = 6 := by decide"),
    ("field_simp", "theorem c8 (x : ℝ) (hx : x ≠ 0) : x / x = 1 := by field_simp"),
    ("deriv", "theorem c9 (c : ℝ) : deriv (fun x : ℝ => 3 * x + c) 0 = 3 := by simp"),
    ("lemma", "theorem c10 (n : ℕ) : Even (n * (n + 1)) := Nat.even_mul_succ_self n"),
    ("gcongr", "theorem c11 (a b c : ℝ) (h : a ≤ b) : a + c ≤ b + c := by gcongr"),
    ("classical", "theorem c12 (p : Prop) : p ∨ ¬p := Classical.em p"),
    # must be rejected, and by the same diagnostics in both modes
    ("wrong", "theorem w1 : (2 : ℕ) + 2 = 5 := by norm_num"),
    ("unsolved", "theorem w2 (a b : ℝ) : a + b = b + a + 1 := by ring"),
    ("variable_include", "variable (n : ℕ) (hn : n = 5)\ninclude hn\ntheorem w3 : n = 5 := hn"),
    ("shadow_notation", "local notation \"ℕ\" => ℤ\ntheorem w4 (n : ℕ) : n + 0 = n := by simp"),
]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def summary(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "p50": round(statistics.median(values), 3),
        "p90": round(percentile(values, 0.9), 3),
        "max": round(max(values), 3),
    }


def verdict(result) -> tuple[bool, tuple[str, ...]]:  # type: ignore[no-untyped-def]
    codes = sorted(d.code for d in result.diagnostics if d.severity == "error")
    return result.success, tuple(codes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=ROOT / "lean-workspace")
    parser.add_argument(
        "--toolchain",
        default=str(Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1"),
    )
    parser.add_argument("--elan-home", default=str(Path.home() / ".elan"))
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--skip-cold-concurrent", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lean = f"{args.toolchain}/bin/lean"
    lake = f"{args.toolchain}/bin/lake"
    lean_path = subprocess.run(
        [lake, "env", "printenv", "LEAN_PATH"], cwd=args.project, capture_output=True, text=True,
        check=True,
    ).stdout.strip()
    scratch = Path(mkdtemp(prefix="pals-bench-", dir=args.out))

    def verifier(resident: ResidentLean | None) -> LeanVerifier:
        return LeanVerifier(
            lean_binary=lean, lake_binary=lake, project_dir=args.project,
            child_path=f"{args.toolchain}/bin:/usr/bin:/bin", elan_home=args.elan_home,
            scratch_dir=scratch, timeout_seconds=300.0, resident=resident,
        )

    resident = ResidentLean(
        ResidentConfig(
            lean_binary=lean,
            lean_path=lean_path,
            build_dir=scratch / "resident",
            max_children=args.concurrency,
            queue_timeout_s=30.0,
        )
    )
    report: dict[str, object] = {"load_start": os.getloadavg(), "cases": len(CASES)}
    startup = resident.start()
    report["resident_startup_s"] = round(startup, 2)
    modes = {"cold": verifier(None), "warm": verifier(resident)}
    sources = [(name, f"{HEADER}{body}\n") for name, body in CASES]
    verdicts: dict[str, dict[str, object]] = {"cold": {}, "warm": {}}
    timings: dict[str, dict[str, list[float]]] = {
        m: {"single": [], "concurrent": []} for m in modes
    }
    per_case: dict[str, dict[str, list[float]]] = {m: {} for m in modes}
    try:
        for mode, instance in modes.items():
            for _ in range(args.repeats):
                for name, source in sources:
                    started = time.monotonic()
                    result = instance.verify(source)
                    elapsed = time.monotonic() - started
                    timings[mode]["single"].append(elapsed)
                    per_case[mode].setdefault(name, []).append(round(elapsed, 3))
                    verdicts[mode][name] = verdict(result)
        report["load_after_single"] = os.getloadavg()
        for mode, instance in modes.items():
            if mode == "cold" and args.skip_cold_concurrent:
                continue
            work = [s for _, s in sources] * max(1, args.concurrency // len(sources) + 1)
            work = work[: max(args.concurrency * 2, len(sources))]

            def one(source: str, instance: LeanVerifier = instance) -> float:
                started = time.monotonic()
                instance.verify(source)
                return time.monotonic() - started

            wall = time.monotonic()
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                timings[mode]["concurrent"] = list(pool.map(one, work))
            report[f"{mode}_concurrent_wall_s"] = round(time.monotonic() - wall, 2)
        report["load_end"] = os.getloadavg()
    finally:
        resident.close()
    report["verdicts_identical"] = verdicts["cold"] == verdicts["warm"]
    report["verdict_differences"] = {
        n: {"cold": verdicts["cold"][n], "warm": verdicts["warm"][n]}
        for n in verdicts["cold"]
        if verdicts["cold"][n] != verdicts["warm"][n]
    }
    report["verdicts"] = {
        n: [verdicts["cold"][n][0], list(verdicts["cold"][n][1])] for n in verdicts["cold"]
    }
    report["timing"] = {
        mode: {k: summary(v) for k, v in kinds.items() if v} for mode, kinds in timings.items()
    }
    report["per_case_seconds"] = per_case
    report["concurrency"] = args.concurrency
    (args.out / "bench_resident.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    shown = {k: v for k, v in report.items() if k != "per_case_seconds"}
    print(json.dumps(shown, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
