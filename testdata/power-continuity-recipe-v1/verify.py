"""Compile the exact materialized Recipe source and audit axioms without writing the Lean cache.

This emits local compiler evidence only: never an admission receipt, a publication, or proof
of the production verifier's behaviour. It does not call Lake and never builds a dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import publication
import rfc8785

ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def run(
    binary: Path, source: Path, environment: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), str(source)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--lean-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    card = publication.load_card()
    manifest = publication.authoring_manifest(card)
    fingerprint = manifest["toolchain"]["fingerprint"]
    project = args.project.resolve(strict=True)
    binary = args.lean_binary.resolve(strict=True)
    version = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    if "version 4.32.0-rc1" not in version:
        raise ValueError("Lean compiler version differs from the pinned toolchain")
    lake_manifest = (project / "lake-manifest.json").read_bytes()
    if sha(lake_manifest) != fingerprint["lake_manifest_sha256"]:
        raise ValueError("project lake manifest differs from the toolchain fingerprint")
    packages = project / json.loads(lake_manifest).get("packagesDir", ".lake/packages")
    libraries = [path for path in sorted(packages.glob("*/.lake/build/lib/lean")) if path.is_dir()]
    if not (packages / "mathlib/.lake/build/lib/lean/Mathlib.olean").is_file():
        raise ValueError("compiled Mathlib library is absent")
    environment = {**os.environ, "LEAN_PATH": ":".join(str(path) for path in libraries)}
    materialized = publication.materialize(manifest)
    theorem_source = (publication.ROOT / card["source_path"]).read_text()
    if not re.search(r"^theorem\s+" + card["theorem_name"] + r"\b", theorem_source, re.M):
        raise ValueError("theorem file lost its named theorem")
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="power-recipe-", dir=args.output.parent) as work:
        materialized_path = Path(work) / "Materialized.lean"
        materialized_path.write_bytes(materialized)
        first = run(binary, materialized_path, environment, 180)
        audit_path = Path(work) / "Axioms.lean"
        audit_path.write_text(theorem_source + "\n#print axioms " + card["theorem_name"] + "\n")
        second = run(binary, audit_path, environment, 180)
    observed = re.findall(r"depends on axioms: \[([^]]*)\]", second.stdout + second.stderr)
    axioms = sorted(part.strip() for part in observed[0].split(",")) if observed else []
    report = {
        "schema_version": "pals.power-recipe-local-verification.v1",
        "recipe_id": card["id"],
        "compiler_version": version,
        "compiler_binary_sha256": sha(binary.read_bytes()),
        "lake_manifest_sha256": sha(lake_manifest),
        "materialized_source_sha256": sha(materialized),
        "manifest_sha256": sha(rfc8785_bytes(manifest)),
        "materialized_exit_code": first.returncode,
        "materialized_diagnostics": first.stdout + first.stderr,
        "axiom_audit_exit_code": second.returncode,
        "axioms": axioms,
        "axioms_allowed": bool(observed) and set(axioms) <= ALLOWED_AXIOMS,
        "elapsed_seconds": time.monotonic() - started,
        "admitted": False,
        "reviewed": False,
    }
    publication.write_new(args.output, json.dumps(report, indent=1).encode())
    print(
        json.dumps(
            {key: report[key] for key in ("materialized_exit_code", "axioms", "axioms_allowed")}
        )
    )
    return 0 if first.returncode == 0 and second.returncode == 0 and report["axioms_allowed"] else 1


def rfc8785_bytes(value: dict[str, Any]) -> bytes:
    return bytes(rfc8785.dumps(value))


if __name__ == "__main__":
    raise SystemExit(main())
