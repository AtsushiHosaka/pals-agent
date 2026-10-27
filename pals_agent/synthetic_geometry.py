"""Checked, opt-in synthetic geometry producer; no catalog or chat admission.

Only the reviewed isosceles/midpoint family is supported. User strings never
become Lean code. The trace, theorem and transitive axiom audit share exact bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import rfc8785

from pals_agent.geometry_diagram import GeometryDiagramUnavailable, geometry_diagram
from pals_agent.geometry_input import GeometryProblem
from pals_agent.lean import LeanVerifier, _limited_command, _run_limited_process

LEAN_TOOLCHAIN = "leanprover/lean4:v4.32.0-rc1"
MATHLIB_REVISION = "8b62164d808cd0f23b7d8cc28190a6c1a1bb483a"
PROOF_SHA256 = "59441abf6e6a92e7e6413b6435356c7c49430b1cfcda22cb7eb0f9686ee7fa80"
ALLOWED_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_DECLARATIONS = (
    "base_distinct",
    "apex_distinct_midpoint",
    "apex_mem_perpBisector",
    "midpoint_orthogonality",
    "isosceles_midpoint_perpendicular",
)
_AXIOMS = re.compile(r"'PalsGeometry\.(\w+)' depends on axioms: \[([^\]]*)\]")


class GeometryVerificationError(ValueError):
    """Missing, stale or inconsistent proof evidence; never a verified result."""


def proof_source() -> str:
    source = (
        resources.files("pals_agent")
        .joinpath("geometry_proofs/isosceles_midpoint.lean")
        .read_text(encoding="utf-8")
    )
    if hashlib.sha256(source.encode()).hexdigest() != PROOF_SHA256:
        raise GeometryVerificationError("geometry proof resource digest mismatch")
    return source


def _trace(problem: GeometryProblem, source: str) -> list[dict[str, Any]]:
    data = problem.to_data()
    hypotheses = {h["predicate"]: h["id"] for h in data["hypotheses"]}
    tri = hypotheses["non_collinear"]
    equal = hypotheses["equal_distance"]
    mid = hypotheses["midpoint"]
    entries: tuple[tuple[str, list[str], list[str], list[str], str, str], ...] = (
        (
            "base_distinct",
            [tri],
            [],
            ["ne₂₃_of_not_collinear"],
            "B and C are distinct because ABC is non-collinear.",
            "B ≠ C",
        ),
        (
            "apex_distinct_midpoint",
            [tri, mid],
            [],
            ["wbtw_midpoint", "Wbtw.collinear", "Set.insert_comm"],
            "M lies on BC; non-collinearity therefore gives A ≠ M.",
            "A ≠ M",
        ),
        (
            "apex_mem_perpBisector",
            [equal],
            [],
            ["AffineSubspace.mem_perpBisector_iff_dist_eq"],
            "Equal distances AB and AC put A on the perpendicular bisector of BC.",
            "A ∈ AffineSubspace.perpBisector B C",
        ),
        (
            "midpoint_orthogonality",
            [mid],
            ["apex_mem_perpBisector"],
            ["AffineSubspace.mem_perpBisector_iff_inner_eq_zero"],
            "Substitute M as midpoint: the directions AM and BC are orthogonal.",
            "⟪A -ᵥ M, C -ᵥ B⟫ = 0",
        ),
        (
            "isosceles_midpoint_perpendicular",
            [],
            list(_DECLARATIONS[:4]),
            ["And.intro"],
            "Both directions are nonzero and orthogonal, so AM is perpendicular to BC.",
            "B ≠ C ∧ A ≠ M ∧ ⟪A -ᵥ M, C -ᵥ B⟫ = 0",
        ),
    )
    lines = source.splitlines()
    result = []
    for name, premises, dependencies, rules, explanation, conclusion in entries:
        start = next(i for i, line in enumerate(lines) if line.startswith(f"theorem {name} "))
        end = next((i for i in range(start, len(lines)) if not lines[i]), len(lines))
        result.append(
            {
                "id": name,
                "declaration": "PalsGeometry." + name,
                "premises": premises,
                "dependencies": dependencies,
                "rules": rules,
                "explanation": explanation,
                "conclusion": conclusion,
                "role_ids": dict(problem.role_ids),
                "source_binding": {
                    "sha256": PROOF_SHA256,
                    "start_line": start + 1,
                    "end_line": end,
                },
            }
        )
    return result


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_OPTIONAL_LOCKS": "0"},
    )
    return completed.stdout.strip()


def _check_environment(verifier: LeanVerifier) -> dict[str, Any]:
    if verifier.project_dir is None:
        raise GeometryVerificationError("a pinned Lean workspace is required")
    workspace = verifier.project_dir
    if (workspace / "lean-toolchain").read_text().strip() != LEAN_TOOLCHAIN:
        raise GeometryVerificationError("Lean toolchain pin mismatch")
    # Compare the complete manifest and Lake configuration to this distribution,
    # then inspect every dependency's source revision and tracked cleanliness.
    pins = {
        "lake-manifest.json": "290f048c4a499d34a3b21f8db30ade48a2b8d05b0fe79709f1868fa6748944fa",
        "lakefile.lean": "57b216b973ddf2ef6a6e176a082c76cbc9d5c1b640df041c87c0fb9dc93ae2a6",
    }
    for name, digest in pins.items():
        if hashlib.sha256((workspace / name).read_bytes()).hexdigest() != digest:
            raise GeometryVerificationError(f"workspace {name} differs from packaged pin")
    manifest_bytes = (workspace / "lake-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    dependencies = {}
    for package in manifest["packages"]:
        root = workspace / manifest["packagesDir"] / package["name"]
        revision = _git(root, "rev-parse", "HEAD")
        if revision != package["rev"] or _git(
            root, "status", "--porcelain", "--untracked-files=no"
        ):
            raise GeometryVerificationError(f"dependency source mismatch: {package['name']}")
        dependencies[package["name"]] = revision
    if dependencies.get("mathlib") != MATHLIB_REVISION:
        raise GeometryVerificationError("Mathlib revision mismatch")
    return {
        "lean_toolchain": LEAN_TOOLCHAIN,
        "mathlib_revision": MATHLIB_REVISION,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "dependency_revisions": dependencies,
        "trust_boundary": "operator-provisioned Lean executable and compiled dependencies",
        "platform": sys.platform,
    }


def parse_axiom_report(output: str) -> dict[str, list[str]]:
    """Reject incomplete, duplicate, or non-foundational transitive axiom reports."""
    reports = {}
    for name, values in _AXIOMS.findall(output):
        axioms = [value.strip() for value in values.split(",") if value.strip()]
        if name not in _DECLARATIONS or name in reports or not set(axioms) <= ALLOWED_AXIOMS:
            raise GeometryVerificationError("unexpected transitive axiom footprint")
        reports[name] = axioms
    if set(reports) != set(_DECLARATIONS) or '"4.32.0-rc1"' not in output.splitlines():
        raise GeometryVerificationError("missing axiom or active Lean version evidence")
    return reports


def _audit(verifier: LeanVerifier, source: str) -> tuple[dict[str, list[str]], int]:
    """Run only fixed trusted audit commands through the existing child isolation.

    The public verifier continues rejecting interactive commands from generated
    code. No caller-provided source or declaration names can reach this path.
    """
    if source != proof_source():
        raise GeometryVerificationError("audit source differs from reviewed resource")
    lean = shutil.which(verifier.lean_binary)
    lake = shutil.which(verifier.lake_binary)
    if lean is None or lake is None:
        raise GeometryVerificationError("Lean/Lake unavailable for axiom audit")
    audit_source = (
        source
        + "\n#eval Lean.versionString\n"
        + "\n".join("#print axioms PalsGeometry." + name for name in _DECLARATIONS)
        + "\n"
    )
    started = time.monotonic()
    with TemporaryDirectory(prefix="pals-geometry-audit-", dir=verifier.scratch_dir) as tmp:
        root = Path(tmp)
        (root / "home").mkdir(mode=0o700)
        target = root / "Audit.lean"
        target.write_text(audit_source)
        target.chmod(0o400)
        command, cwd = verifier._command_for(target, lean_binary=lean, lake_binary=lake)
        completed = _run_limited_process(
            _limited_command(command, timeout_seconds=verifier.timeout_seconds, scratch_dir=root),
            cwd=cwd,
            environment={
                "PATH": verifier.child_path,
                "HOME": str(root / "home"),
                "TMPDIR": str(root),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "ELAN_HOME": verifier.elan_home,
            },
            timeout_seconds=verifier.timeout_seconds,
            output_limit_bytes=verifier.output_limit_bytes,
        )
    if completed.returncode or completed.timed_out or completed.output_limited:
        raise GeometryVerificationError("bounded Lean axiom audit failed")
    return parse_axiom_report(completed.stdout), int((time.monotonic() - started) * 1000)


def check_geometry(problem: GeometryProblem, verifier: LeanVerifier) -> dict[str, Any]:
    data = problem.to_data()
    binding = hashlib.sha256(rfc8785.dumps(data)).hexdigest()
    result: dict[str, Any] = {
        "schema_version": "pals.checked-geometry.v1",
        "input": data,
        "input_sha256": binding,
        "scope": "opt-in agent domain; no catalog admission",
        "diagram_status": "not_produced",
        "role_ids": dict(problem.role_ids),
    }
    if not problem.ready:
        return {**result, "status": "needs_input", "clarification": problem.clarification}
    source = proof_source()
    environment = _check_environment(verifier)
    verification = verifier.verify(source)
    result.update(
        {
            "lean_source": source,
            "proof_sha256": PROOF_SHA256,
            "environment": environment,
            "verification": asdict(verification),
        }
    )
    if not verification.success:
        return {**result, "status": "failed"}
    axioms, audit_ms = _audit(verifier, source)
    # Pin state again after both compiler runs; do not publish stale metadata.
    if environment != _check_environment(verifier):
        raise GeometryVerificationError("environment changed during verification")
    try:
        diagrams = [geometry_diagram(problem, proof_sha256=PROOF_SHA256)]
        result.update({"diagrams": diagrams, "diagram_status": "prepared_unrendered"})
    except GeometryDiagramUnavailable as exc:
        result.update({"diagrams": [], "diagram_status": "unavailable", "diagram_error": str(exc)})
    trace = _trace(problem, source)
    return {
        **result,
        "status": "checked",
        "trace": trace,
        "trace_sha256": hashlib.sha256(rfc8785.dumps(trace)).hexdigest(),
        "axioms": axioms,
        "axiom_audit_elapsed_ms": audit_ms,
        "formal_model": "real inner-product affine space; nonzero orthogonal line directions",
        "correspondence": (
            "caller-declared structured hypotheses; no natural-language equivalence claim"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--lean-workspace", required=True, type=Path)
    parser.add_argument("--lean", default="lean")
    parser.add_argument("--lake", default="lake")
    parser.add_argument("--elan-home", default="/opt/elan")
    parser.add_argument("--child-path", default="/opt/elan/bin:/usr/local/bin:/usr/bin:/bin")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    try:
        with args.request.open("rb") as stream:
            raw = stream.read(300_001)
        if len(raw) > 300_000:
            raise GeometryVerificationError("geometry input exceeds byte bound")
        problem = GeometryProblem.parse(json.loads(raw))
        verifier = LeanVerifier(
            project_dir=args.lean_workspace,
            lean_binary=args.lean,
            lake_binary=args.lake,
            timeout_seconds=args.timeout,
            elan_home=args.elan_home,
            child_path=args.child_path,
        )
        result = check_geometry(problem, verifier)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "checked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
