"""Evaluate authored mathematics sources using the existing bounded Lean verifier.

Compilation is evidence about the exact Lean file, not natural-language alignment,
independent review, catalog admission, retrieval quality, or deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pals_agent.lean import LeanVerifier, _strip_lean_comments_and_strings

CORPUS_SCHEMA = "pals.mathematical-breadth-corpus.v1"
REPORT_SCHEMA = "pals.mathematical-breadth-evaluation.v1"


@dataclass(frozen=True)
class Case:
    identifier: str
    family_id: str
    theorem_name: str
    source_path: str | None
    source: str | None
    source_sha256: str | None


@dataclass(frozen=True)
class Corpus:
    path: Path
    sha256: str
    lean_toolchain: str
    mathlib_revision: str
    cases: tuple[Case, ...]


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("input is empty or exceeds size limit")
    return raw


def _source_path(root: Path, value: Any) -> Path:
    relative = Path(_text(value, "source_path"))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".lean":
        raise ValueError("source_path must be a relative .lean path without traversal")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("source_path must not contain symlinks")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("source_path escapes corpus directory or is not a file")
    return resolved


def load_corpus(path: Path) -> Corpus:
    path = path.resolve(strict=True)
    raw = _read(path, 4 * 1024 * 1024)
    payload = _object(json.loads(raw, object_pairs_hook=_pairs), "corpus")
    if payload.get("schema_version") != CORPUS_SCHEMA:
        raise ValueError("unsupported corpus schema")
    pins = _object(payload.get("toolchain"), "toolchain")
    toolchain = _text(pins.get("lean_toolchain"), "lean_toolchain")
    revision = _text(pins.get("mathlib_revision"), "mathlib_revision")
    if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        raise ValueError("mathlib_revision must be an exact commit")
    rows = payload.get("cases")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError("cases must contain 1..256 cases")
    seen: set[str] = set()
    cases = []
    for row in rows:
        row = _object(row, "case")
        identifier = _text(row.get("id"), "id")
        if identifier in seen:
            raise ValueError("duplicate case id")
        seen.add(identifier)
        family = _text(row.get("family_id"), "family_id")
        theorem = _text(row.get("theorem_name"), "theorem_name")
        if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9'.]*", theorem) is None:
            raise ValueError("theorem_name must be a simple Lean declaration identifier")
        _text(row.get("statement"), "statement")
        for field in ("assumptions", "proof_outline"):
            entries = row.get(field)
            if not isinstance(entries, list) or not entries:
                raise ValueError(f"{field} must be a nonempty list")
            for entry in entries:
                _text(entry, field)
        negative = _object(row.get("hard_negative"), "hard_negative")
        for field in ("statement", "counterexample"):
            _text(negative.get(field), f"hard_negative.{field}")
        provenance = _object(row.get("provenance"), "provenance")
        for field in ("kind", "license"):
            _text(provenance.get(field), f"provenance.{field}")
        if "source_path" not in row:
            raise ValueError("source_path is required, including for pending cases")
        source_path = row["source_path"]
        source = None
        source_hash = None
        if source_path is None:
            if row.get("status") != "authored_not_compiled":
                raise ValueError("source-less cases must be explicitly authored_not_compiled")
        else:
            source_file = _source_path(path.parent, source_path)
            source_bytes = _read(source_file, 1024 * 1024)
            source = source_bytes.decode("utf-8")
            checked = _strip_lean_comments_and_strings(source)
            if re.search(r"\btheorem\s+" + re.escape(theorem) + r"(?=\s|\(|\{|:)", checked) is None:
                raise ValueError("named theorem declaration is absent from source")
            source_hash = _hash(source_bytes)
        cases.append(Case(identifier, family, theorem, source_path, source, source_hash))
    return Corpus(path, _hash(raw), toolchain, revision, tuple(cases))


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        check=True,
        timeout=10,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if len(result.stdout) > 1024 * 1024:
        raise ValueError("git output exceeds limit")
    return result.stdout.decode("utf-8").strip()


def environment_binding(corpus: Corpus, project: Path) -> dict[str, Any]:
    toolchain_raw = _read(project / "lean-toolchain", 4096)
    manifest_raw = _read(project / "lake-manifest.json", 1024 * 1024)
    lakefiles = [project / name for name in ("lakefile.lean", "lakefile.toml")]
    lakefiles = [path for path in lakefiles if path.is_file()]
    if len(lakefiles) != 1:
        raise ValueError("exactly one Lake configuration file is required")
    lakefile = lakefiles[0]
    lakefile_raw = _read(lakefile, 1024 * 1024)
    manifest = _object(json.loads(manifest_raw, object_pairs_hook=_pairs), "Lake manifest")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not 1 <= len(packages) <= 256:
        raise ValueError("Lake packages missing or excessive")
    mathlibs = [p for p in packages if isinstance(p, dict) and p.get("name") == "mathlib"]
    if len(mathlibs) != 1 or mathlibs[0].get("rev") != corpus.mathlib_revision:
        raise ValueError("Mathlib manifest revision differs from corpus")
    if toolchain_raw.decode().strip() != corpus.lean_toolchain:
        raise ValueError("Lean toolchain differs from corpus")
    packages_relative = Path(_text(manifest.get("packagesDir", ".lake/packages"), "packagesDir"))
    if packages_relative.is_absolute() or ".." in packages_relative.parts:
        raise ValueError("packagesDir must stay within the Lean project")
    packages_dir = (project / packages_relative).resolve(strict=True)
    if not packages_dir.is_relative_to(project.resolve()):
        raise ValueError("packagesDir escapes the Lean project")
    dependencies = []
    seen: set[str] = set()
    for raw in packages:
        package = _object(raw, "Lake package")
        name = _text(package.get("name"), "package name")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) is None or name in seen:
            raise ValueError("invalid or duplicate package name")
        seen.add(name)
        revision = package.get("rev")
        if package.get("type") != "git" or not isinstance(revision, str):
            raise ValueError("every package must have an exact Git revision")
        if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
            raise ValueError("every package must have an exact Git revision")
        checkout = (packages_dir / name).resolve(strict=True)
        label = "Mathlib" if name == "mathlib" else name
        try:
            top = Path(_git(checkout, "rev-parse", "--show-toplevel")).resolve()
            if top != checkout:
                raise ValueError(f"{label} is not its own Git checkout")
            actual = _git(checkout, "rev-parse", "HEAD")
            if actual != revision:
                raise ValueError(f"actual {label} HEAD differs from manifest")
            if _git(checkout, "status", "--porcelain", "--untracked-files=no"):
                raise ValueError(f"{label} tracked source is dirty")
        except subprocess.SubprocessError as error:
            raise ValueError(f"{label} Git checkout could not be audited") from error
        dependencies.append({"name": name, "revision": actual, "tracked_source": "clean"})
    return {
        "lean_toolchain": corpus.lean_toolchain,
        "lean_toolchain_sha256": _hash(toolchain_raw),
        "lake_manifest_sha256": _hash(manifest_raw),
        "lakefile": lakefile.name,
        "lakefile_sha256": _hash(lakefile_raw),
        "mathlib_revision": corpus.mathlib_revision,
        "mathlib_tracked_source": "clean",
        "dependencies": sorted(dependencies, key=lambda dependency: dependency["name"]),
    }


def evaluate(corpus: Corpus, project: Path, *, elan_home: Path, child_path: str) -> dict[str, Any]:
    project = project.resolve(strict=True)
    binding = environment_binding(corpus, project)
    verifier = LeanVerifier(
        lean_binary=str(elan_home / "bin/lean"),
        lake_binary=str(elan_home / "bin/lake"),
        project_dir=project,
        timeout_seconds=45,
        elan_home=str(elan_home),
        child_path=child_path,
    )
    outcomes = []
    for case in corpus.cases:
        outcome: dict[str, Any] = {
            "id": case.identifier,
            "family_id": case.family_id,
            "theorem_name": case.theorem_name,
            "source_path": case.source_path,
            "source_sha256": case.source_sha256,
        }
        if case.source is None:
            outcome["status"] = "authored_not_compiled"
        else:
            result = verifier.verify(case.source)
            outcome.update(
                status="compiled" if result.success else "verification_failed",
                elapsed_ms=result.elapsed_ms,
                diagnostics=[asdict(item) for item in result.diagnostics],
                stdout_sha256=_hash(result.stdout.encode()),
                stderr_sha256=_hash(result.stderr.encode()),
            )
        outcomes.append(outcome)
    if environment_binding(corpus, project) != binding or load_corpus(corpus.path) != corpus:
        raise ValueError("corpus, source, or environment changed during verification")
    return {
        "schema_version": REPORT_SCHEMA,
        "corpus_sha256": corpus.sha256,
        "environment": binding,
        "timeout_seconds_per_case": 45,
        "all_compiled": all(case["status"] == "compiled" for case in outcomes),
        "evidence_scope": (
            "exact Lean source compilation only; semantic alignment and axiom audit separate"
        ),
        "cases": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--lean-project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--elan-home", type=Path, default=Path.home() / ".elan")
    parser.add_argument("--child-path")
    args = parser.parse_args()
    try:
        corpus = load_corpus(args.corpus)
        output = args.output.resolve()
        project = args.lean_project.resolve(strict=True)
        protected = {corpus.path} | {
            _source_path(corpus.path.parent, c.source_path)
            for c in corpus.cases
            if c.source_path is not None
        }
        if output in protected or output.is_relative_to(project):
            raise ValueError("output would overwrite an input or the reused Lean project")
        elan_home = args.elan_home.resolve(strict=True)
        report = evaluate(
            corpus,
            project,
            elan_home=elan_home,
            child_path=args.child_path or f"{elan_home / 'bin'}:/usr/bin:/bin",
        )
        output.write_text(json.dumps(report, indent=2) + "\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Breadth evaluation failed: {error}\n")
    return 0 if report["all_compiled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
