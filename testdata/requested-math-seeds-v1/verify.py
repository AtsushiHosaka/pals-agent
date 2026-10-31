"""Compile each exact witness and audit axioms without writing the reused Lean cache.

This emits local compiler evidence only, never a publication or admission receipt.
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

from pals_agent.breadth_evaluation import environment_binding, load_corpus


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--lean-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    corpus = load_corpus(root / "corpus.json")
    project = args.project.resolve(strict=True)
    binding = environment_binding(corpus, project)
    binary = args.lean_binary.resolve(strict=True)
    version = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    if "version 4.32.0-rc1" not in version:
        raise ValueError("Lean compiler version differs")
    manifest = json.loads((project / "lake-manifest.json").read_bytes())
    packages = project / manifest.get("packagesDir", ".lake/packages")
    libraries = [packages / p["name"] / ".lake/build/lib/lean" for p in manifest["packages"]]
    # Cli is a Lake tooling dependency and has no compiled Lean library here.
    # Only existing module search roots are needed; Lean itself rejects every
    # unresolved import. Never build or fetch a missing dependency.
    missing_libraries = [str(path.relative_to(packages)) for path in libraries if not path.is_dir()]
    libraries = [path for path in libraries if path.is_dir()]
    if not (packages / "mathlib/.lake/build/lib/lean/Mathlib.olean").is_file():
        raise ValueError("compiled Mathlib library is absent")
    environment = {**os.environ, "LEAN_PATH": ":".join(str(path) for path in libraries)}
    outcomes = []
    started = time.monotonic()
    for case in corpus.cases:
        if case.source is None:
            raise ValueError("every requested seed must have a witness")
        if re.search(r"\b(?:sorry|admit|axiom|unsafe)\b", case.source):
            raise ValueError("unverified source construct")
        before = (root / case.source_path).read_bytes()
        case_started = time.monotonic()
        result = subprocess.run(
            [str(binary), str((root / case.source_path).resolve())],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if (root / case.source_path).read_bytes() != before:
            raise ValueError("source changed while compiling")
        diagnostic = result.stdout + result.stderr
        if len(diagnostic.encode()) > 1024 * 1024:
            raise ValueError("compiler diagnostics unbounded")
        outcome = {
            "id": case.identifier,
            "theorem_name": case.theorem_name,
            "source_path": case.source_path,
            "source_sha256": sha(before),
            "elapsed_seconds": time.monotonic() - case_started,
            "exit_code": result.returncode,
            "compiled": result.returncode == 0,
            "diagnostics": diagnostic,
        }
        outcomes.append(outcome)
        print(json.dumps({"id": case.identifier, "compiled": outcome["compiled"]}), flush=True)
    audit_source = "import Mathlib\n\nopen Filter Topology\n\n"
    for case in corpus.cases:
        # Reuse the existing breadth-audit convention: import the library once,
        # then elaborate all unique witnesses before inspecting transitive axioms.
        declaration = re.sub(r"^import [^\n]+\n", "", case.source, flags=re.M)
        audit_source += declaration.replace("open Filter Topology", "") + "\n"
    for case in corpus.cases:
        audit_source += "#print axioms " + case.theorem_name + "\n"
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="requested-seed-axioms-", dir=args.output.parent
    ) as temporary:
        audit = Path(temporary) / "Axioms.lean"
        audit.write_text(audit_source)
        result = subprocess.run(
            [str(binary), str(audit)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
    if result.returncode != 0:
        raise ValueError("axiom audit did not compile")
    audit_output = result.stdout + result.stderr
    matches = re.findall(r"'([^']+)' depends on axioms: \[([^]]*)\]", audit_output, re.S)
    observed = {
        name: sorted(part.strip() for part in axioms.split(",") if part.strip())
        for name, axioms in matches
    }
    for case in corpus.cases:
        if case.theorem_name not in observed:
            if "'" + case.theorem_name + "' does not depend on any axioms" in audit_output:
                observed[case.theorem_name] = []
            else:
                raise ValueError("missing theorem axiom observation")
        if set(observed[case.theorem_name]) - {"propext", "Classical.choice", "Quot.sound"}:
            raise ValueError("unexpected theorem axiom")
    if sha((root / "corpus.json").read_bytes()) != corpus.sha256:
        raise ValueError("corpus changed during verification")
    if environment_binding(corpus, project) != binding:
        raise ValueError("dependency source binding changed")
    report = {
        "schema_version": "pals.requested-math-local-verification.v1",
        "corpus_sha256": corpus.sha256,
        "compiler_version": version,
        "compiler_binary_sha256": sha(binary.read_bytes()),
        "environment": binding,
        "cases": outcomes,
        "axioms": observed,
        "unbuilt_package_libraries": missing_libraries,
        "axiom_audit_source_sha256": sha(audit_source.encode()),
        "elapsed_seconds": time.monotonic() - started,
        "all_compiled": all(row["compiled"] for row in outcomes),
        "cache_or_primary_source_modified": False,
        "artifact_origin_audited": False,
        "independently_reviewed": False,
        "admitted": False,
        "published": False,
        "runtime_verified": False,
        "deployed": False,
    }
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(report, output, sort_keys=True, indent=2)
    print(
        json.dumps(
            {
                "compiled": sum(row["compiled"] for row in outcomes),
                "cases": len(outcomes),
                "axiom_audit_passed": True,
                "published": False,
            }
        ),
        flush=True,
    )
    return 0 if report["all_compiled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
