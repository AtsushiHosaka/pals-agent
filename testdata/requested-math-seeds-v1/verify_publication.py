"""Compile exact authoring materializations locally, without admission or cache writes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from publication import ROOT, materialize, read_object, sha, write_new

from pals_agent.breadth_evaluation import environment_binding, load_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--lean-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    corpus = load_corpus(ROOT / "corpus.json")
    project = args.project.resolve(strict=True)
    binding = environment_binding(corpus, project)
    binary = args.lean_binary.resolve(strict=True)
    version = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    if "version 4.32.0-rc1" not in version:
        raise ValueError("compiler version differs")
    lake = read_object(project / "lake-manifest.json")
    packages = project / lake.get("packagesDir", ".lake/packages")
    libraries = [packages / row["name"] / ".lake/build/lib/lean" for row in lake["packages"]]
    if not (packages / "mathlib/.lake/build/lib/lean/Mathlib.olean").is_file():
        raise ValueError("compiled Mathlib absent")
    environment = {**os.environ, "LEAN_PATH": ":".join(str(p) for p in libraries if p.is_dir())}
    outcomes = []
    for case in corpus.cases:
        path = ROOT / "publication" / (case.identifier + ".json")
        raw = path.read_bytes()
        manifest = read_object(path)
        source = materialize(manifest)
        if re.search(r"\b(?:sorry|sorryAx|admit|axiom|unsafe)\b", source.decode()):
            raise ValueError("forbidden source construct")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="requested-recipe-") as directory:
            lean = Path(directory) / "Main.lean"
            lean.write_bytes(source)
            result = subprocess.run(
                [str(binary), str(lean)],
                env=environment,
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=90,
            )
        if path.read_bytes() != raw:
            raise ValueError("authoring bytes changed")
        outcomes.append(
            {
                "recipe_id": case.identifier,
                "manifest_sha256": sha(raw),
                "materialized_source_sha256": sha(source),
                "exit_code": result.returncode,
                "elapsed_seconds": time.monotonic() - started,
                "diagnostics": result.stdout + result.stderr,
            }
        )
        print(
            json.dumps({"recipe_id": case.identifier, "compiled": result.returncode == 0}),
            flush=True,
        )
    if (
        environment_binding(corpus, project) != binding
        or sha((ROOT / "corpus.json").read_bytes()) != corpus.sha256
    ):
        raise ValueError("input binding changed")
    report = {
        "corpus_sha256": corpus.sha256,
        "compiler_version": version,
        "compiler_binary_sha256": sha(binary.read_bytes()),
        "environment": binding,
        "cases": outcomes,
        "all_compiled": all(row["exit_code"] == 0 for row in outcomes),
        "admitted": False,
        "reviewed": False,
        "published": False,
        "verifier_fingerprint_measured_at_runtime": False,
    }
    write_new(args.output, json.dumps(report, sort_keys=True, indent=2).encode())
    return 0 if report["all_compiled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
