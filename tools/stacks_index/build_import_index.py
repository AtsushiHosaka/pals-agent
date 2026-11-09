"""Build the import index: declaration -> defining module, and module -> direct imports.

Source-only, no model and no compilation. It answers one question: *which modules must a
Lean file import to see the constants a statement mentions?* so a verifier can load a few
hundred modules instead of the whole of StacksFrontier.

Layers (recorded per module, so trust is never lost):

    core      StacksCore       human reviewed
    frontier  StacksFrontier   AI generated, not reviewed by a human (opt-in)
    mathlib   Mathlib          the pinned revision the Stacks workspace builds against
    dep       Batteries, Aesop, Qq, Plausible, ... (Mathlib's own dependencies, edges + names)
    lean      Init, Std, Lean  from the toolchain

Declaration names come from the same lexical extractor as the declaration index (PR #72);
`--from-stacks-index` takes the Stacks rows from an existing `index.sqlite` of that index instead
of re-parsing, so only headers are read. Only the import edges are new.

    python -m tools.stacks_index.build_import_index --stacks DIR --out OUT [--include-frontier] \\
        [--mathlib DIR] [--dep LAYER=DIR:Root1,Root2 ...] [--lean-src DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stacks_index.build_index import read_provenance
from tools.stacks_index.extract import extract_text, module_name
from tools.stacks_index.header import parse_header

SCHEMA_VERSION = 1
STACKS_LAYERS = (("StacksCore", "core"), ("StacksFrontier", "frontier"))
SHORT_TYPE = 24  # statements shorter than this are too generic to call "the same statement"


@dataclass(slots=True)
class Source:
    layer: str
    root: Path
    prefixes: tuple[str, ...]  # top-level module names under root, e.g. ("Mathlib",)


@dataclass(slots=True)
class ScannedFile:
    module: str
    layer: str
    path: str
    sha256: str
    lines: int
    module_system: bool
    prelude: bool
    imports: list[tuple[str, bool, bool, bool]]
    decls: list[tuple[str, str, int, str]] = field(default_factory=list)  # name, kind, line, hash
    aliases: list[tuple[str, int]] = field(default_factory=list)  # root-level `export N (a)`


def _scan(job: tuple[str, str, str, bool]) -> ScannedFile:
    layer, root, path, with_names = job
    file = Path(path)
    data = file.read_bytes()
    text = data.decode("utf-8", errors="replace")
    module = module_name(file, Path(root))
    header = parse_header(text)
    scanned = ScannedFile(
        module=module,
        layer=layer,
        path=str(file.relative_to(root)),
        sha256=hashlib.sha256(data).hexdigest(),
        lines=text.count("\n") + 1,
        module_system=header.module_system,
        prelude=header.prelude,
        imports=[(e.imported, e.public, e.meta, e.all) for e in header.imports],
    )
    if not header.prelude and module != "Init" and not module.startswith("Init."):
        # Every file that is not `prelude` implicitly imports `Init`, publicly.
        scanned.imports.append(("Init", True, False, False))
    scanned.aliases = _export_aliases(text)
    if with_names:
        result = extract_text(text, module=module, path=scanned.path)
        for declaration in result.declarations:
            full_type = f"{declaration.context} {declaration.signature}".strip()
            digest = hashlib.sha256(full_type.encode()).hexdigest()[:16]
            scanned.decls.append((declaration.name, declaration.kind, declaration.line, digest))
    return scanned


_EXPORT = re.compile(r"^export[ \t]+[\w.']+[ \t]*\(([^)]*)\)", re.MULTILINE)


def _export_aliases(text: str) -> list[tuple[str, int]]:
    """`export Ns (a b)` at the top level makes `a` and `b` usable bare: they live in this module.

    Only column-0 exports before any `namespace` line are taken, so the alias really is a root
    name; an export inside a namespace would need the namespace tracked.
    """
    first_namespace = re.search(r"^namespace\b", text, re.MULTILINE)
    limit = first_namespace.start() if first_namespace else len(text)
    found = []
    for match in _EXPORT.finditer(text, 0, limit):
        line = text.count("\n", 0, match.start()) + 1
        found.extend((name, line) for name in re.findall(r"[\w']+", match.group(1)))
    return found


def iter_sources(source: Source) -> list[Path]:
    paths: list[Path] = []
    for prefix in source.prefixes:
        top = source.root / f"{prefix}.lean"
        if top.is_file():
            paths.append(top)
        directory = source.root / prefix
        if directory.is_dir():
            paths.extend(sorted(directory.rglob("*.lean")))
    return paths


def scan_sources(
    sources: list[Source], *, workers: int, names_from_index: set[str]
) -> list[ScannedFile]:
    jobs = [
        (s.layer, str(s.root), str(p), s.layer not in names_from_index)
        for s in sources
        for p in iter_sources(s)
    ]
    if workers > 1 and len(jobs) > 500:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_scan, jobs, chunksize=64))
    return [_scan(job) for job in jobs]


def read_stacks_index_decls(path: Path) -> dict[str, list[tuple[str, str, int, str]]]:
    """Declaration rows of a PR #72 `index.sqlite`, grouped by module (reuse, no re-parse)."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows: dict[str, list[tuple[str, str, int, str]]] = defaultdict(list)
    for name, kind, module, line, type_hash in connection.execute(
        "SELECT name, kind, module, line, type_hash FROM decl WHERE kind != 'upstream'"
    ):
        rows[module].append((name, kind, line or 0, type_hash or ""))
    connection.close()
    return rows


def _layer_of(module: str, known: dict[str, str]) -> str:
    if module in known:
        return known[module]
    head = module.split(".", 1)[0]
    if head in ("Init", "Std", "Lean", "Lake"):
        return "lean"
    if head == "Mathlib":
        return "mathlib"
    return "dep"


SCHEMA = """
CREATE TABLE module (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, layer TEXT NOT NULL, scanned INTEGER NOT NULL,
  path TEXT, sha256 TEXT, lines INTEGER, module_system INTEGER, n_decls INTEGER NOT NULL
);
CREATE TABLE edge (
  src INTEGER NOT NULL, dst INTEGER NOT NULL, public INTEGER NOT NULL, meta INTEGER NOT NULL,
  all_ INTEGER NOT NULL, PRIMARY KEY (src, dst)
) WITHOUT ROWID;
CREATE TABLE decl (
  name TEXT NOT NULL, module INTEGER NOT NULL, kind TEXT NOT NULL, line INTEGER,
  type_hash TEXT, short TEXT NOT NULL, PRIMARY KEY (name, module)
) WITHOUT ROWID;
CREATE TABLE namespace (
  name TEXT NOT NULL, module INTEGER NOT NULL, PRIMARY KEY (name, module)
) WITHOUT ROWID;
CREATE TABLE conflict (name TEXT NOT NULL, modules TEXT NOT NULL, layers TEXT NOT NULL);
CREATE TABLE equivalent (type_hash TEXT NOT NULL, name TEXT NOT NULL, module TEXT NOT NULL,
  layer TEXT NOT NULL);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def build(
    sources: list[Source],
    out_dir: Path,
    *,
    workers: int = 4,
    stacks_index: Path | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    reused = {"core", "frontier"} if stacks_index is not None else set()
    scanned = scan_sources(sources, workers=workers, names_from_index=reused)
    scan_seconds = time.monotonic() - started
    reused_rows = read_stacks_index_decls(stacks_index) if stacks_index else {}
    for file in scanned:
        if file.layer in reused:
            file.decls = list(reused_rows.get(file.module, []))
        file.decls.extend((name, "alias", line, "") for name, line in file.aliases)

    scanned.sort(key=lambda f: (f.layer, f.module))
    known_layer = {f.module: f.layer for f in scanned}
    ids: dict[str, int] = {f.module: index for index, f in enumerate(scanned, start=1)}
    external: dict[str, int] = {}
    for file in scanned:
        for imported, *_ in file.imports:
            if imported not in ids and imported not in external:
                external[imported] = len(ids) + len(external) + 1

    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "import_index.sqlite"
    db_path.unlink(missing_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)
    for file in scanned:
        connection.execute(
            "INSERT INTO module VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ids[file.module], file.module, file.layer, 1, file.path, file.sha256, file.lines,
                int(file.module_system), len(file.decls),
            ),
        )  # fmt: skip
    for module, identifier in external.items():
        connection.execute(
            "INSERT INTO module VALUES (?,?,?,?,?,?,?,?,?)",
            (identifier, module, _layer_of(module, known_layer), 0, None, None, None, None, 0),
        )
    all_ids = {**ids, **external}
    edge_count = 0
    for file in scanned:
        merged: dict[str, list[int]] = {}
        for imported, public, meta, all_ in file.imports:
            flags = merged.setdefault(imported, [0, 0, 0])
            flags[0] |= int(public)
            flags[1] |= int(meta)
            flags[2] |= int(all_)
        for imported, flags in merged.items():
            connection.execute(
                "INSERT INTO edge VALUES (?,?,?,?,?)", (ids[file.module], all_ids[imported], *flags)
            )
            edge_count += 1

    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    by_hash: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    kinds: Counter[str] = Counter()
    for file in scanned:
        seen: set[str] = set()
        namespaces: set[str] = set()
        for name, kind, line, type_hash in file.decls:
            if name in seen:
                continue
            seen.add(name)
            parts = name.split(".")
            namespaces.update(".".join(parts[:i]) for i in range(1, len(parts)))
            connection.execute(
                "INSERT INTO decl VALUES (?,?,?,?,?,?)",
                (name, ids[file.module], kind, line, type_hash or None, name.rsplit(".", 1)[-1]),
            )
            by_name[name].append((file.module, file.layer))
            if type_hash and kind in (
                "theorem",
                "def",
                "abbrev",
                "structure",
                "class",
                "inductive",
            ):
                by_hash[type_hash].append((name, file.module, file.layer))
            kinds[kind] += 1
        connection.executemany(
            "INSERT INTO namespace VALUES (?,?)",
            [(n, ids[file.module]) for n in sorted(namespaces)],
        )
    conflicts: Counter[str] = Counter()
    for name, places in by_name.items():
        if len(places) > 1:
            layers = sorted({layer for _, layer in places})
            connection.execute(
                "INSERT INTO conflict VALUES (?,?,?)",
                (name, json.dumps([m for m, _ in places]), ",".join(layers)),
            )
            conflicts["+".join(layers)] += 1
    equivalents: Counter[str] = Counter()
    for type_hash, group in by_hash.items():
        names = {name for name, _, _ in group}
        layers = sorted({layer for _, _, layer in group})
        if len(names) < 2 or len(layers) < 2 or len(type_hash) == 0:
            continue
        for name, module, layer in group:
            connection.execute(
                "INSERT INTO equivalent VALUES (?,?,?,?)", (type_hash, name, module, layer)
            )
        equivalents["+".join(layers)] += 1
    connection.execute("CREATE INDEX edge_dst ON edge(dst)")
    connection.execute("CREATE INDEX decl_short ON decl(short)")
    connection.execute("CREATE INDEX equivalent_hash ON equivalent(type_hash)")
    connection.execute("CREATE INDEX equivalent_name ON equivalent(name)")
    connection.commit()

    layer_counts: dict[str, dict[str, int]] = {}
    for layer in sorted({f.layer for f in scanned} | {"dep", "lean", "mathlib"}):
        members = [f for f in scanned if f.layer == layer]
        layer_counts[layer] = {
            "modules": len(members),
            "edges": sum(len({i for i, *_ in f.imports}) for f in members),
            "declarations": sum(len(f.decls) for f in members),
            "lines": sum(f.lines for f in members),
        }
    digest = hashlib.sha256()
    per_layer: dict[str, Any] = {}
    for layer in sorted(layer_counts):
        layer_digest = hashlib.sha256()
        for file in (f for f in scanned if f.layer == layer):
            line = f"{file.module}\t{file.sha256}\n".encode()
            layer_digest.update(line)
            digest.update(line)
        per_layer[layer] = layer_digest.hexdigest()
    for key, value in {
        "schema_version": SCHEMA_VERSION,
        "source_digest": digest.hexdigest(),
        "layer_source_digests": json.dumps(per_layer),
        "provenance": json.dumps(provenance or {}),
        "layers": json.dumps(layer_counts),
        "names_from_stacks_index": str(stacks_index is not None),
    }.items():
        connection.execute("INSERT INTO meta VALUES (?,?)", (key, str(value)))
    connection.commit()
    connection.execute("VACUUM")
    connection.close()
    # The content hash is over the rows, not the file: the same sources give the same hash.
    content_hash = content_digest(db_path)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "provenance": provenance or {},
        "source_digest": digest.hexdigest(),
        "layer_source_digests": per_layer,
        "content_digest": content_hash,
        "layers": layer_counts,
        "modules_total": len(scanned) + len(external),
        "unscanned_modules": len(external),
        "edges_total": edge_count,
        "declarations_total": sum(kinds.values()),
        "kinds": dict(sorted(kinds.items())),
        "names_with_several_definitions": dict(sorted(conflicts.items())),
        "same_statement_groups": dict(sorted(equivalents.items())),
        "module_system_files": sum(1 for f in scanned if f.module_system),
        "scan_seconds": round(scan_seconds, 1),
        "build_seconds": round(time.monotonic() - started, 1),
        "db_bytes": db_path.stat().st_size,
    }
    (out_dir / "import_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def content_digest(db_path: Path) -> str:
    """Hash of the logical rows, in a fixed order, independent of SQLite page layout."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    digest = hashlib.sha256()
    for table, order in (
        ("module", "name"),
        ("edge", "src, dst"),
        ("decl", "name, module"),
        ("namespace", "name, module"),
        ("conflict", "name"),
        ("equivalent", "type_hash, name, module"),
    ):
        digest.update(table.encode())
        for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):  # noqa: S608
            digest.update(repr(row).encode())
    connection.close()
    return digest.hexdigest()


def compute_source_digest(sources: list[Source]) -> str:
    """The `source_digest` a build of these sources would record (hashes files, parses nothing)."""
    entries = []
    for source in sources:
        for path in iter_sources(source):
            data = path.read_bytes()
            entries.append(
                (source.layer, module_name(path, source.root), hashlib.sha256(data).hexdigest())
            )
    digest = hashlib.sha256()
    for _, module, sha in sorted(entries):
        digest.update(f"{module}\t{sha}\n".encode())
    return digest.hexdigest()


def diff_indexes(old_path: Path, new_path: Path) -> dict[str, Any]:
    """What changed between two builds: modules, import edges, and declaration locations."""

    def load(path: Path) -> tuple[dict[str, str], set[tuple[str, str]], dict[str, set[str]]]:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        modules = {
            n: (sha or "") for n, sha in connection.execute("SELECT name, sha256 FROM module")
        }
        edges = set(
            connection.execute(
                "SELECT a.name, b.name FROM edge e JOIN module a ON a.id = e.src"
                " JOIN module b ON b.id = e.dst"
            )
        )
        places: dict[str, set[str]] = defaultdict(set)
        for name, module in connection.execute(
            "SELECT d.name, m.name FROM decl d JOIN module m ON m.id = d.module"
        ):
            places[name].add(module)
        connection.close()
        return modules, edges, places

    old_modules, old_edges, old_places = load(old_path)
    new_modules, new_edges, new_places = load(new_path)
    moved = [n for n in old_places.keys() & new_places.keys() if old_places[n] - new_places[n]]
    return {
        "modules_added": len(new_modules.keys() - old_modules.keys()),
        "modules_removed": len(old_modules.keys() - new_modules.keys()),
        "modules_changed": sum(
            1 for m in old_modules.keys() & new_modules.keys() if old_modules[m] != new_modules[m]
        ),
        "edges_added": len(new_edges - old_edges),
        "edges_removed": len(old_edges - new_edges),
        "declarations_added": len(new_places.keys() - old_places.keys()),
        "declarations_removed": len(old_places.keys() - new_places.keys()),
        "declarations_moved": len(moved),
    }


def _parse_dep(spec: str) -> Source:
    layer, _, rest = spec.partition("=")
    directory, _, roots = rest.partition(":")
    return Source(layer, Path(directory), tuple(r for r in roots.split(",") if r))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stacks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--include-frontier", action="store_true")
    parser.add_argument("--mathlib", type=Path, help="Mathlib checkout at the pinned revision")
    parser.add_argument("--dep", action="append", default=[], metavar="LAYER=DIR:Root1,Root2")
    parser.add_argument("--lean-src", type=Path, help="toolchain `src/lean` (Init, Std, Lean)")
    parser.add_argument("--from-stacks-index", type=Path, help="reuse decl rows of index.sqlite")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--verify", type=Path, metavar="INDEX", help="check sources match INDEX")
    parser.add_argument("--diff", type=Path, metavar="OLD_INDEX", help="diff OLD_INDEX with --out")
    args = parser.parse_args(argv)
    if args.diff:
        print(json.dumps(diff_indexes(args.diff, args.out / "import_index.sqlite"), indent=2))
        return 0

    sources = [
        Source(layer, args.stacks, (prefix,))
        for prefix, layer in STACKS_LAYERS
        if layer == "core" or args.include_frontier
    ]
    provenance: dict[str, Any] = {
        **read_provenance(args.stacks),
        "include_frontier": args.include_frontier,
    }
    if args.mathlib:
        sources.append(Source("mathlib", args.mathlib, ("Mathlib",)))
        provenance["mathlib_commit"] = _git_head(args.mathlib)
    for spec in args.dep:
        source = _parse_dep(spec)
        sources.append(source)
        provenance.setdefault("deps", {})[source.root.name] = _git_head(source.root)
    if args.lean_src:
        sources.append(Source("lean", args.lean_src, ("Init", "Std", "Lean", "Lake")))
    if args.verify:
        recorded = dict(
            sqlite3.connect(f"file:{args.verify}?mode=ro", uri=True).execute(
                "SELECT key, value FROM meta"
            )
        )["source_digest"]
        actual = compute_source_digest(sources)
        print(json.dumps({"index": recorded, "sources": actual, "match": recorded == actual}))
        return 0 if recorded == actual else 1
    manifest = build(
        sources,
        args.out,
        workers=args.workers,
        stacks_index=args.from_stacks_index,
        provenance=provenance,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _git_head(path: Path) -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


if __name__ == "__main__":
    raise SystemExit(main())
