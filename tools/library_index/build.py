"""Build a declaration index of any library from its manifest (source text only, no Lean, no model).

    python -m tools.library_index.build --library mathlib-archive --source DIR --out OUT
        [--plugin stacks-tags]

``DIR`` is a checkout of the library at exactly the commit its manifest pins; the build refuses a
different commit. Every layer of the manifest names a directory at the checkout root and carries a
generic trust word, which each indexed row records. The index is an investigation and retrieval aid:
a row says a declaration *exists* in the source with this text, never that it is true or compiles.

Outputs: ``index.sqlite``, ``decls.jsonl.gz`` (deterministic) and ``manifest.json`` (commit,
licence, counts, build time, SHA-256 of the jsonl). Library-specific parsing (for example Stacks
tags) is an optional plugin that only adds a ``tags`` column.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from pals_agent.lean_library_manifest import LibraryManifest
from tools.stacks_index.extract import Declaration, extract_file, iter_lean_files

INDEX_SCHEMA: Final = "pals.library-declaration-index.v1"
PLUGINS: Final[dict[str, Callable[[Declaration], list[str]]]] = {
    # Stacks Project tags (`@[stacks 00DJ]`); the only library-specific parsing there is.
    "stacks-tags": lambda declaration: [tag.tag for tag in declaration.tags],
}


def _commit_of(source: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _row(declaration: Declaration, layer_root: str, trust: str, tags: list[str]) -> dict[str, Any]:
    return {
        "name": declaration.name,
        "kind": declaration.kind,
        "statement": declaration.signature,
        "context": declaration.context,
        "module": declaration.module,
        "path": declaration.path,
        "line": declaration.line,
        "layer": layer_root,
        "trust": trust,
        "has_doc": bool(declaration.doc),
        "tags": tags,
    }


def build(
    manifest: LibraryManifest,
    source: Path,
    out_dir: Path,
    *,
    plugin: str | None = None,
    verify_commit: bool = True,
    library_commit: str | None = None,
) -> dict[str, Any]:
    """Index every layer of ``manifest`` found under ``source``; return the written manifest."""
    expected = library_commit or manifest.commit
    actual = _commit_of(source)
    if verify_commit and actual != expected:
        raise SystemExit(f"{source} is at {actual}, the manifest pins {expected}")
    tag_plugin = PLUGINS[plugin] if plugin else None
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    files = 0
    for layer in manifest.layers:
        if not (source / layer.root).is_dir():
            continue  # a layer that is a dependency root (e.g. Mathlib) has no directory here
        for path in iter_lean_files(source, layer.root):
            result = extract_file(path, source)
            files += 1
            skipped.update(result.skipped)
            rows.extend(
                _row(d, layer.root, layer.trust, tag_plugin(d) if tag_plugin else [])
                for d in result.declarations
            )
    rows.sort(key=lambda r: (r["module"], r["line"], r["name"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / "decls.jsonl.gz"
    with gzip.GzipFile(jsonl, "wb", mtime=0) as handle:
        for row in rows:
            handle.write((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode())
    digest = hashlib.sha256(jsonl.read_bytes()).hexdigest()
    sqlite_path = out_dir / "index.sqlite"
    sqlite_path.unlink(missing_ok=True)
    with sqlite3.connect(sqlite_path) as db:
        db.execute(
            "CREATE TABLE decl (name TEXT NOT NULL, kind TEXT NOT NULL, statement TEXT NOT NULL,"
            " context TEXT NOT NULL, module TEXT NOT NULL, path TEXT NOT NULL, line INTEGER,"
            " layer TEXT NOT NULL, trust TEXT NOT NULL, tags TEXT NOT NULL)"
        )
        db.executemany(
            "INSERT INTO decl VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (r["name"], r["kind"], r["statement"], r["context"], r["module"], r["path"],
                 r["line"], r["layer"], r["trust"], " ".join(r["tags"]))
                for r in rows
            ],
        )
        db.execute("CREATE INDEX decl_name ON decl(name)")
        db.execute("CREATE INDEX decl_module ON decl(module)")
        db.execute("CREATE VIRTUAL TABLE decl_fts USING fts5(name, statement, tags)")
        db.execute("INSERT INTO decl_fts SELECT name, statement, tags FROM decl")
    elapsed = time.perf_counter() - started
    written = {
        "schema": INDEX_SCHEMA,
        "library": manifest.name,
        "repo": manifest.repo,
        "commit": expected,
        "license": manifest.license_spdx,
        "attribution": manifest.attribution,
        "plugin": plugin,
        "files": files,
        "declarations": len(rows),
        "by_kind": dict(sorted(Counter(r["kind"] for r in rows).items())),
        "by_layer": dict(sorted(Counter(r["layer"] for r in rows).items())),
        "by_trust": dict(sorted(Counter(r["trust"] for r in rows).items())),
        "skipped": dict(sorted(skipped.items())),
        "decls_jsonl_gz_sha256": digest,
        "sqlite_bytes": sqlite_path.stat().st_size,
        "jsonl_gz_bytes": jsonl.stat().st_size,
        "build_seconds": round(elapsed, 2),
        "claims": "declarations exist in the source text; not that they compile or are true",
    }
    (out_dir / "manifest.json").write_text(json.dumps(written, indent=2, sort_keys=True) + "\n")
    return written


def main() -> None:
    from pals_agent.lean_profiles import MANIFESTS

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", required=True, help="manifest name, e.g. mathlib-archive")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plugin", choices=sorted(PLUGINS))
    parser.add_argument(
        "--no-verify-commit", action="store_true",
        help="for a source tree that is not a git checkout (a package inside another workspace)",
    )
    parser.add_argument("--library-commit", help="commit the tree is known to be at (no git)")
    args = parser.parse_args()
    manifest = next((m for m in MANIFESTS if m.name == args.library), None)
    if manifest is None:
        raise SystemExit(f"no manifest named {args.library}")
    result = build(
        manifest, args.source, args.out, plugin=args.plugin,
        verify_commit=not args.no_verify_commit, library_commit=args.library_commit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
