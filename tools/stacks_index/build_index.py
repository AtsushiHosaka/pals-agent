"""Build the Stacks declaration index (SQLite + FTS5) from a checkout of AxiomMath/Stacks.

Source-only: nothing is compiled. The default scope is `StacksCore` (human reviewed). The
unreviewed, AI-generated `StacksFrontier` is added only with `--include-frontier`, and every
entry records its trust level (`core` / `frontier`).

    python -m tools.stacks_index.build_index --stacks DIR --out OUT [--include-frontier]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mathlib_index.build_index import name_tokens
from tools.stacks_index.extract import Declaration, FileResult, extract_file, iter_lean_files
from tools.stacks_index.shape import statement_shape

SCHEMA_VERSION = 1
LAYERS = (("StacksCore", "core"), ("StacksFrontier", "frontier"))
STACKS_REPO = "https://github.com/AxiomMath/Stacks"
_PATH_LABEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _extract(args: tuple[str, str]) -> FileResult:
    path, root = args
    return extract_file(Path(path), Path(root))


def read_provenance(stacks_dir: Path) -> dict[str, str | None]:
    def git(*command: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(stacks_dir), *command],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip() or None

    toolchain_path = stacks_dir / "lean-toolchain"
    toolchain = toolchain_path.read_text().strip() if toolchain_path.exists() else None
    mathlib_rev = None
    manifest_path = stacks_dir / "lake-manifest.json"
    if manifest_path.exists():
        for package in json.loads(manifest_path.read_text()).get("packages", []):
            if package.get("name") == "mathlib":
                mathlib_rev = f"{package.get('inputRev')} ({package.get('rev')})"
    return {
        "stacks_repo": STACKS_REPO,
        "stacks_commit": git("rev-parse", "HEAD"),
        "lean_toolchain": toolchain,
        "mathlib": mathlib_rev,
    }


def collect(
    stacks_dir: Path, *, include_frontier: bool, workers: int
) -> list[tuple[str, FileResult]]:
    jobs: list[tuple[str, str]] = []
    trusts: list[str] = []
    for layer, trust in LAYERS:
        if trust == "frontier" and not include_frontier:
            continue
        for path in iter_lean_files(stacks_dir, layer):
            jobs.append((str(path), str(stacks_dir)))
            trusts.append(trust)
    if workers > 1 and len(jobs) > 500:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_extract, jobs, chunksize=64))
    else:
        results = [_extract(job) for job in jobs]
    return list(zip(trusts, results, strict=True))


def _resolve(target: str, namespace: str, defined: set[str]) -> str | None:
    if target.startswith("_root_."):
        target = target[len("_root_.") :]
        namespace = ""
    parts = namespace.split(".") if namespace else []
    for depth in range(len(parts), -1, -1):
        candidate = ".".join([*parts[:depth], target])
        if candidate in defined:
            return candidate
    return None


def _module_words(module: str, title: str) -> str:
    return (
        name_tokens(module.removeprefix("StacksCore.").removeprefix("StacksFrontier."))
        + " "
        + title
    )


def build(
    stacks_dir: Path,
    out_dir: Path,
    *,
    include_frontier: bool = False,
    workers: int = 8,
    provenance: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    provenance = provenance if provenance is not None else read_provenance(stacks_dir)
    files = collect(stacks_dir, include_frontier=include_frontier, workers=workers)

    records: dict[str, dict[str, Any]] = {}
    duplicates = 0
    skipped: Counter[str] = Counter()
    module_rows: list[dict[str, Any]] = []
    link_rows: list[tuple[str, Any]] = []
    for trust, result in files:
        skipped.update(result.skipped)
        info = result.module
        module_rows.append({**asdict(info), "trust": trust, "n_decls": len(result.declarations)})
        for declaration in result.declarations:
            if declaration.name in records:
                duplicates += 1
                continue
            records[declaration.name] = _declaration_record(declaration, trust, info.title)
        link_rows.extend((trust, link) for link in result.upstream)

    defined = set(records)
    upstream: dict[str, dict[str, Any]] = {}
    resolved_links = 0
    cross_trust_ignored = 0
    ref_links = 0
    for trust, link in link_rows:
        if link.tag.source.startswith("add_to_ega") or link.tag.source.startswith("add_to_sga"):
            ref_links += 1
            continue
        resolved = _resolve(link.target, link.namespace, defined)
        tag = {"tag": link.tag.tag, "comment": link.tag.comment, "source": "add_to_stacks"}
        tag["trust"] = trust
        if resolved is not None:
            target = records[resolved]
            if target["trust"] != trust:
                cross_trust_ignored += 1  # an unreviewed layer must not annotate a reviewed one
                continue
            resolved_links += 1
            if not any(
                t["tag"] == tag["tag"] and t["comment"] == tag["comment"] for t in target["tags"]
            ):
                target["tags"].append(tag)
            continue
        entry = upstream.setdefault(
            link.target,
            {
                "name": link.target,
                "kind": "upstream",
                "trust": trust,
                "module": link.module,
                "path": link.path,
                "line": link.line,
                "namespace": link.namespace,
                "tags": [],
                "modules": [],
            },
        )
        if trust == "core" and entry["trust"] != "core":
            entry.update(trust="core", module=link.module, path=link.path, line=link.line)
        entry["tags"].append(tag)
        entry["modules"].append(link.module)
    all_records = sorted(records.values(), key=lambda r: r["name"])
    upstream_records = sorted(upstream.values(), key=lambda r: r["name"])
    module_titles = {m["module"]: m["title"] for m in module_rows}

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "index.sqlite"
    db_path.unlink(missing_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE decl (
          id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
          trust TEXT NOT NULL, module TEXT NOT NULL, path TEXT NOT NULL, line INTEGER,
          namespace TEXT, signature TEXT, context TEXT, type TEXT, doc TEXT, body TEXT,
          attrs TEXT NOT NULL, tags TEXT NOT NULL, refs TEXT NOT NULL, type_hash TEXT,
          conclusion_constants TEXT NOT NULL, hypothesis_constants TEXT NOT NULL
        );
        CREATE TABLE module (
          module TEXT PRIMARY KEY, path TEXT NOT NULL, trust TEXT NOT NULL, title TEXT,
          doc TEXT, lines INTEGER, tags TEXT NOT NULL, n_decls INTEGER NOT NULL
        );
        CREATE TABLE tag (
          tag TEXT NOT NULL, name TEXT NOT NULL, comment TEXT, source TEXT NOT NULL,
          trust TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE decl_fts USING fts5(
          name_words, doc, statement_words, module_words, tag_text, body_words,
          tokenize = 'porter unicode61'
        );
        """
    )
    digest = hashlib.sha256()
    kinds: Counter[str] = Counter()
    export_path = out_dir / "decls.jsonl.gz"
    with gzip.GzipFile(export_path, "wb", mtime=0) as export:
        for record in [*all_records, *upstream_records]:
            record["tags"] = sorted(
                record["tags"], key=lambda t: (t["tag"], t["comment"], t["source"], t["trust"])
            )
            line = (
                json.dumps(
                    {"schema_version": SCHEMA_VERSION, **record}, ensure_ascii=False, sort_keys=True
                ).encode()
                + b"\n"
            )
            digest.update(line)
            export.write(line)
            kinds[record["kind"]] += 1
            _insert(connection, record, module_titles)
    for module in module_rows:
        connection.execute(
            "INSERT INTO module VALUES (?,?,?,?,?,?,?,?)",
            (
                module["module"],
                module["path"],
                module["trust"],
                module["title"],
                module["doc"],
                module["lines"],
                json.dumps(module["tags"]),
                module["n_decls"],
            ),
        )
    connection.commit()
    connection.execute("INSERT INTO decl_fts(decl_fts) VALUES('optimize')")
    connection.execute("CREATE INDEX decl_trust ON decl(trust, kind)")
    connection.execute("CREATE INDEX tag_tag ON tag(tag)")
    connection.commit()
    connection.execute("VACUUM")
    connection.close()

    manifest = _manifest(
        provenance,
        include_frontier=include_frontier,
        module_rows=module_rows,
        records=all_records,
        upstream=upstream_records,
        skipped=skipped,
        duplicates=duplicates,
        resolved_links=resolved_links,
        cross_trust_ignored=cross_trust_ignored,
        ref_links=ref_links,
        digest=digest.hexdigest(),
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _declaration_record(declaration: Declaration, trust: str, title: str) -> dict[str, Any]:
    full_type = f"{declaration.context} {declaration.signature}".strip()
    shape = statement_shape(declaration.signature, declaration.context)
    return {
        "name": declaration.name,
        "kind": declaration.kind,
        "trust": trust,
        "module": declaration.module,
        "path": declaration.path,
        "line": declaration.line,
        "namespace": declaration.namespace,
        "signature": declaration.signature,
        "context": declaration.context,
        "type": full_type,
        "doc": declaration.doc,
        "body": declaration.body,
        "attrs": declaration.attrs,
        "tags": [
            {"tag": t.tag, "comment": t.comment, "source": t.source, "trust": trust}
            for t in declaration.tags
        ],
        "refs": [list(ref) for ref in declaration.refs],
        "type_hash": hashlib.sha256(full_type.encode()).hexdigest()[:16],
        "shape": shape,
    }


def _insert(connection: sqlite3.Connection, record: dict[str, Any], titles: dict[str, str]) -> None:
    shape = record.get("shape", {"conclusion_constants": [], "hypothesis_constants": []})
    cursor = connection.execute(
        "INSERT INTO decl (name, kind, trust, module, path, line, namespace, signature, context,"
        " type, doc, body, attrs, tags, refs, type_hash, conclusion_constants,"
        " hypothesis_constants) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record["name"],
            record["kind"],
            record["trust"],
            record["module"],
            record["path"],
            record["line"],
            record.get("namespace", ""),
            record.get("signature"),
            record.get("context"),
            record.get("type"),
            record.get("doc"),
            record.get("body"),
            json.dumps(record.get("attrs", [])),
            json.dumps(record["tags"]),
            json.dumps(record.get("refs", [])),
            record.get("type_hash"),
            json.dumps(shape["conclusion_constants"]),
            json.dumps(shape["hypothesis_constants"]),
        ),
    )
    for tag in record["tags"]:
        if tag["tag"]:
            connection.execute(
                "INSERT INTO tag VALUES (?,?,?,?,?)",
                (tag["tag"], record["name"], tag["comment"], tag["source"], tag["trust"]),
            )
    statement_words = " ".join(
        name_tokens(constant)
        for constant in shape["conclusion_constants"] + shape["hypothesis_constants"]
    )
    tag_text = " ".join(
        f"{t['tag']} {t['comment']}" for t in record["tags"] if t["trust"] == record["trust"]
    )
    body_words = name_tokens(
        " ".join(re.findall(r"^\s*([A-Za-z_][\w']*)", record.get("body", ""), re.M))
    )
    connection.execute(
        "INSERT INTO decl_fts (rowid, name_words, doc, statement_words, module_words, tag_text,"
        " body_words) VALUES (?,?,?,?,?,?,?)",
        (
            cursor.lastrowid,
            name_tokens(record["name"]),
            record.get("doc") or "",
            statement_words,
            _module_words(record["module"], titles.get(record["module"], "")),
            tag_text,
            body_words + " " + (record.get("body") or ""),
        ),
    )


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _manifest(
    provenance: dict[str, str | None],
    *,
    include_frontier: bool,
    module_rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    upstream: list[dict[str, Any]],
    skipped: Counter[str],
    duplicates: int,
    resolved_links: int,
    cross_trust_ignored: int,
    ref_links: int,
    digest: str,
) -> dict[str, Any]:
    by_trust: dict[str, Any] = {}
    for trust in ("core", "frontier"):
        decls = [r for r in records if r["trust"] == trust]
        modules = [m for m in module_rows if m["trust"] == trust]
        if not decls and not modules:
            continue
        attribute_tagged = sum(
            1
            for r in decls
            if any(t["source"] in {"attribute", "add_to_stacks"} for t in r["tags"])
        )
        any_tagged = sum(1 for r in decls if r["tags"])
        stacks_tags = {t["tag"] for r in decls for t in r["tags"] if t["tag"]}
        stacks_tags |= {t["tag"] for r in upstream for t in r["tags"] if t["trust"] == trust}
        by_trust[trust] = {
            "files": len(modules),
            "lines": sum(m["lines"] for m in modules),
            "declarations": len(decls),
            "kinds": dict(Counter(r["kind"] for r in decls).most_common()),
            "with_docstring": sum(1 for r in decls if r["doc"]),
            "tagged_by_attribute_or_add_to_stacks": attribute_tagged,
            "tagged_share": _share(attribute_tagged, len(decls)),
            "tagged_including_docstring_mentions": any_tagged,
            "distinct_stacks_tags": len(stacks_tags),
            "upstream_tag_targets": sum(
                1 for r in upstream if any(t["trust"] == trust for t in r["tags"])
            ),
            "modules_without_declarations": sum(1 for m in modules if not m["n_decls"]),
        }
    unresolved_namespaced = sum(1 for r in upstream if r["namespace"])
    return {
        "schema_version": SCHEMA_VERSION,
        **provenance,
        "include_frontier": include_frontier,
        "trust_levels": by_trust,
        "upstream": {
            "note": "tags attached by add_to_stacks to declarations defined outside this source",
            "entries": len(upstream),
            "tag_links_resolved_to_stacks_declarations": resolved_links,
            "tag_links_from_a_less_trusted_layer_ignored": cross_trust_ignored,
            "ega_sga_links_not_indexed": ref_links,
            "entries_added_inside_a_namespace_name_may_need_prefix": unresolved_namespaced,
        },
        "skipped": dict(skipped),
        "duplicate_names_dropped": duplicates,
        "approximation": (
            "source-level extraction, not elaborated: names are namespace-qualified but not "
            "resolved against `open`; types are source signatures plus the `variable` binders "
            "they depend on"
        ),
        "decls_sha256": digest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stacks", type=Path, required=True, help="checkout of AxiomMath/Stacks")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--include-frontier",
        action="store_true",
        help="also index StacksFrontier (AI-generated, NOT human reviewed). Default: off.",
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.stacks,
                args.out,
                include_frontier=args.include_frontier,
                workers=args.workers,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
