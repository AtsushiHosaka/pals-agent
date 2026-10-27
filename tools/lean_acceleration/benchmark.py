"""Real, serial same-corpus Lean import/setup benchmark; no provider or DB substitutes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import statistics
import subprocess
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pals_agent.lean import LeanVerifier
from pals_agent.lean_environment import LakeEnvironmentCache, VerificationTiming

CORPUS = Path(__file__).with_name("corpus.json")
INVALID_SOURCE = "import Mathlib\ntheorem pals_invalid_target : False := by trivial\n"


def load_corpus() -> list[dict[str, Any]]:
    return list(json.loads(CORPUS.read_text(encoding="utf-8"))["cases"])


def source_for(case: dict[str, Any], *, narrow: bool) -> str:
    imports = case["narrow_imports"] if narrow else ["Mathlib"]
    return "".join(f"import {module}\n" for module in imports) + "\n" + str(case["body"])


def percentiles(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)],
    }


def verifier_for(
    *, project_dir: Path, lean_binary: Path, lake_binary: Path,
    cache: LakeEnvironmentCache | None, events: list[VerificationTiming],
) -> LeanVerifier:
    return LeanVerifier(
        project_dir=project_dir,
        lean_binary=str(lean_binary),
        lake_binary=str(lake_binary),
        child_path=f"{lean_binary.parent}:/usr/local/bin:/usr/bin:/bin",
        elan_home=str(lean_binary.parent.parent.parent.parent),
        timeout_seconds=120,
        lake_environment_cache=cache,
        timing_observer=events.append,
    )


def run_one(
    case: dict[str, Any], *, narrow: bool, mode: str, repeat: int,
    project_dir: Path, lean_binary: Path, lake_binary: Path,
    cache: LakeEnvironmentCache | None,
) -> dict[str, Any]:
    events: list[VerificationTiming] = []
    source = source_for(case, narrow=narrow)
    verifier = verifier_for(
        project_dir=project_dir, lean_binary=lean_binary, lake_binary=lake_binary,
        cache=cache, events=events,
    )
    started = time.perf_counter()
    result = verifier.verify(source)
    row = {
        "mode": mode, "repeat": repeat, "case_id": case["id"],
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "success": result.success, "wall_ms": (time.perf_counter() - started) * 1000,
        "compiler_reported_ms": result.elapsed_ms,
        "diagnostic_codes": [item.code for item in result.diagnostics],
        "stages": [
            {"stage": item.stage, "elapsed_ms": item.elapsed_ms,
             "cache_status": item.cache_status}
            for item in events
        ],
    }
    if not result.success:
        raise RuntimeError(f"real proof failed: {case['id']}: {result.diagnostics}")
    return row


def check_concurrency_and_reset(
    *, project_dir: Path, lean_binary: Path, lake_binary: Path,
) -> dict[str, Any]:
    cache = LakeEnvironmentCache()
    case = load_corpus()[0]
    events: list[VerificationTiming] = []
    verifier = verifier_for(
        project_dir=project_dir, lean_binary=lean_binary, lake_binary=lake_binary,
        cache=cache, events=events,
    )
    source = source_for(case, narrow=True)
    assert verifier.verify(source).success
    events.clear()
    with ThreadPoolExecutor(max_workers=2) as pool:
        good = pool.submit(verifier.verify, source)
        bad = pool.submit(verifier.verify, INVALID_SOURCE)
        accepted, rejected = good.result(), bad.result()
    assert accepted.success and not rejected.success
    concurrent_stages = [
        {"stage": item.stage, "elapsed_ms": item.elapsed_ms, "cache_status": item.cache_status}
        for item in events
    ]
    cache.clear()
    events.clear()
    assert verifier.verify(source).success
    reset_statuses = [item.cache_status for item in events if item.stage == "environment_prepare"]
    assert "miss" in reset_statuses, reset_statuses
    return {
        "concurrent_valid_success": accepted.success,
        "concurrent_invalid_success": rejected.success,
        "concurrent_stages": concurrent_stages,
        "after_clear_prepare_statuses": reset_statuses,
    }


def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    repository = Path(__file__).resolve().parents[2]
    source_paths = [
        "pals_agent/lean.py", "pals_agent/lean_environment.py",
        "pals_agent/lean_verifier/http_runtime.py",
        "pals_agent/lean_verifier/http_server.py",
        "tools/lean_acceleration/benchmark.py",
    ]
    source_hashes = {
        name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
        for name in source_paths
    }
    common = {
        "project_dir": args.project_dir.resolve(),
        "lean_binary": args.lean_binary.resolve(),
        "lake_binary": args.lake_binary.resolve(),
    }
    corpus = load_corpus()
    memory_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # A cold sample means a new process-local setup cache. OS filesystem caches
    # remain uncontrolled; no purge or dependency-tree copies are performed.
    for mode in ("baseline_mathlib", "baseline_narrow", "environment_cold", "environment_warm"):
        cache = LakeEnvironmentCache() if mode == "environment_warm" else None
        if cache is not None:
            rows.append(run_one(corpus[0], narrow=True, mode="warmup", repeat=-1,
                                cache=cache, **common))
        for repeat in range(args.repeats):
            for case in corpus:
                row_cache = LakeEnvironmentCache() if mode == "environment_cold" else cache
                rows.append(run_one(case, narrow=mode != "baseline_mathlib", mode=mode,
                                    repeat=repeat, cache=row_cache, **common))
    summaries: dict[str, Any] = {}
    for mode in sorted({str(row["mode"]) for row in rows}):
        selected = [row for row in rows if row["mode"] == mode]
        stages = sorted({s["stage"] for row in selected for s in row["stages"]})
        summaries[mode] = {
            "wall": percentiles([row["wall_ms"] for row in selected]),
            "by_case": {
                case["id"]: percentiles([row["wall_ms"] for row in selected
                                         if row["case_id"] == case["id"]])
                for case in corpus
            },
            "stages": {
                stage: percentiles([s["elapsed_ms"] for row in selected for s in row["stages"]
                                    if s["stage"] == stage]) for stage in stages
            },
            "prepare_status_counts": {
                status: sum(s["cache_status"] == status for row in selected for s in row["stages"]
                            if s["stage"] == "environment_prepare")
                for status in ("miss", "hit", "fallback")
            },
        }
    checks = check_concurrency_and_reset(**common)
    final_hashes = {
        name: hashlib.sha256((repository / name).read_bytes()).hexdigest()
        for name in source_paths
    }
    if source_hashes != final_hashes:
        raise RuntimeError("benchmark source changed during measurement; rerun against stable code")
    version = subprocess.run([str(common["lean_binary"]), "--version"], check=True,
                             capture_output=True, text=True, timeout=20).stdout.strip()
    return {
        "schema_version": "pals.lean-environment-benchmark.v1",
        "source_sha256": source_hashes,
        "lean_version": version, "platform": platform.platform(),
        "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        "project_toolchain": (common["project_dir"] / "lean-toolchain").read_text(),
        "lake_manifest_sha256": hashlib.sha256(
            (common["project_dir"] / "lake-manifest.json").read_bytes()).hexdigest(),
        "repeats": args.repeats, "summaries": summaries, "rows": rows,
        "concurrency_lifecycle_checks": checks,
        "memory": {
            "children_ru_maxrss_before": memory_before,
            "children_ru_maxrss_after": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            "unit": "bytes" if platform.system() == "Darwin" else "KiB",
            "limitation": "Cumulative maximum child RSS for this Python process, not per mode; "
                          "not aggregate concurrent process-tree peak.",
        },
        "unmeasured_stages": [
            "structuring", "embedding", "database", "rerank", "application",
            "import_vs_elaboration_split",
        ],
        "limits": [
            "Local compiler only; no provider, live DB, admitted catalog or deployment proof.",
                   "Cold means empty process-local environment cache; OS caches uncontrolled.",
                   "Import variants are recompiled sources, not evidence of theorem equivalence.",
                   "Small-sample nearest-rank p95 is descriptive, not a stable tail estimate.",
                   "No proof verdict or generated compiled-artifact cache is implemented."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--lean-binary", required=True, type=Path)
    parser.add_argument("--lake-binary", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("--repeats must be between 1 and 100")
    result = benchmark(args)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summaries"], indent=2))


if __name__ == "__main__":
    main()
