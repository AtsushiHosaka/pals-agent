"""Build the versioned Mathlib statement index from `ExportDecls.lean` shards."""

from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mathlib_index.tiers import (
    SEARCHABLE_FULL,
    TIER_ORDER,
    classify,
    origin_of,
    shared_positions,
)

SCHEMA_VERSION = 1
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# Mathlib naming conventions (see its contribution guide), not derived from evaluation problems.
_NAMING_EXPANSIONS = {
    "deriv": "derivative",
    "fderiv": "derivative",
    "det": "determinant",
    "ker": "kernel",
    "inv": "inverse",
    "nhds": "neighborhood",
    "irred": "irreducible",
    "comm": "commutative",
    "assoc": "associative",
    "sq": "square",
    "pow": "power",
    "mul": "multiplication product",
    "add": "addition sum",
    "sub": "subtraction",
    "div": "division",
    "le": "less equal",
    "lt": "less",
    "ge": "greater equal",
    "gt": "greater",
    "dvd": "divides",
    "gcd": "greatest common divisor",
    "lcm": "least common multiple",
    "abs": "absolute",
    "exp": "exponential",
    "log": "logarithm",
    "sqrt": "square root",
    "iff": "equivalent",
    "tendsto": "limit",
    "lim": "limit",
    "cont": "continuous",
    "diff": "differentiable",
    "eval": "evaluation",
    "orth": "orthogonal",
    "lin": "linear",
    "dim": "dimension",
    "finrank": "dimension rank",
    "matrix": "matrix",
    "poly": "polynomial",
    "seq": "sequence",
    "conj": "conjugate",
    "card": "cardinality",
    "subgroup": "subgroup",
    "ideal": "ideal",
}


def name_tokens(name: str) -> str:
    """Split a Lean name into searchable words, keeping naming-convention expansions."""
    words: list[str] = []
    for part in re.split(r"[._'\s]+", name):
        for word in _CAMEL.split(part):
            lowered = word.lower()
            if lowered and not lowered.isdigit():
                words.append(lowered)
                expansion = _NAMING_EXPANSIONS.get(lowered)
                if expansion and expansion != lowered:
                    words.append(expansion)
    return " ".join(words)


def read_shards(raw_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(raw_dir / "shard-*.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            records.extend(json.loads(line) for line in handle)
    records.sort(key=lambda record: record["name"])
    return records


def proof_usage(records: list[dict[str, Any]]) -> tuple[Counter[str], dict[str, int]]:
    uses: Counter[str] = Counter()
    modules: dict[str, set[str]] = {}
    for record in records:
        for used in set(record["proof_constants"]):
            uses[used] += 1
            modules.setdefault(used, set()).add(record["module"])
    return uses, {name: len(mods) for name, mods in modules.items()}


def primary_positions(records: list[dict[str, Any]]) -> dict[tuple[str, int, int], str]:
    """Pick the source-written theorem at each position, preferring a documented non-copy."""
    primary: dict[tuple[str, int, int], str] = {}
    best: dict[tuple[str, int, int], tuple[int, int, str]] = {}
    for record in records:
        if record["line"] is None or record["attrs"]["internal"]:
            continue
        if record["additive_source"] is not None:
            continue
        position = (record["module"], record["line"], record["column"])
        rank = (0 if record["doc"] else 1, record["name"].count("."), record["name"])
        if position not in best or rank < best[position]:
            best[position] = rank
            primary[position] = record["name"]
    return primary


def build(raw_dir: Path, out_dir: Path, *, mathlib_rev: str, toolchain: str) -> dict[str, Any]:
    records = read_shards(raw_dir)
    uses, use_modules = proof_usage(records)
    positions = shared_positions(records)
    primary = primary_positions(records)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "index.sqlite"
    db_path.unlink(missing_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE decl (
          id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, tier TEXT NOT NULL,
          module TEXT NOT NULL, line INTEGER, type TEXT NOT NULL, doc TEXT, type_hash TEXT NOT NULL,
          signals TEXT NOT NULL, proof_uses INTEGER NOT NULL, proof_use_modules INTEGER NOT NULL,
          conclusion_head TEXT, conclusion_constants TEXT NOT NULL,
          hypothesis_constants TEXT NOT NULL, classes TEXT NOT NULL, prop_args INTEGER NOT NULL,
          additive_source TEXT
        );
        CREATE VIRTUAL TABLE decl_fts USING fts5(
          name_words, doc, statement_words, tokenize = 'porter unicode61'
        );
        """
    )
    tiers: Counter[str] = Counter()
    signals_total: Counter[str] = Counter()
    export_path = out_dir / "decls.jsonl.gz"
    digest = hashlib.sha256()
    with gzip.GzipFile(export_path, "wb", mtime=0) as export:
        for record in records:
            modules_using = use_modules.get(record["name"], 0)
            tier, signals = classify(
                record,
                proof_use_modules=modules_using,
                position_counts=positions,
                primary_at_position=primary,
            )
            tiers[tier] += 1
            signals_total.update(signals)
            shape = record["shape"]
            row = {
                "schema_version": SCHEMA_VERSION,
                "name": record["name"],
                "tier": tier,
                "signals": list(signals),
                "module": record["module"],
                "line": record["line"],
                "type": record["type"],
                "type_hash": record["type_hash"],
                "doc": record["doc"],
                "attrs": record["attrs"],
                "cross_refs": record["cross_refs"],
                "additive_source": record["additive_source"],
                "proof_uses": uses.get(record["name"], 0),
                "proof_use_modules": modules_using,
                "shape": shape,
            }
            line = json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n"
            digest.update(line)
            export.write(line)
            if tier not in SEARCHABLE_FULL:
                continue
            statement_constants = shape["conclusion_constants"] + shape["hypothesis_constants"]
            cursor = connection.execute(
                "INSERT INTO decl (name, tier, module, line, type, doc, type_hash, signals,"
                " proof_uses, proof_use_modules, conclusion_head, conclusion_constants,"
                " hypothesis_constants, classes, prop_args, additive_source)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["name"],
                    tier,
                    record["module"],
                    record["line"],
                    record["type"],
                    record["doc"],
                    record["type_hash"],
                    json.dumps(signals),
                    uses.get(record["name"], 0),
                    modules_using,
                    shape["conclusion_head"],
                    json.dumps(shape["conclusion_constants"]),
                    json.dumps(shape["hypothesis_constants"]),
                    json.dumps(shape["classes"]),
                    shape["prop_args"],
                    record["additive_source"],
                ),
            )
            connection.execute(
                "INSERT INTO decl_fts (rowid, name_words, doc, statement_words) VALUES (?,?,?,?)",
                (
                    cursor.lastrowid,
                    name_tokens(record["name"]),
                    record["doc"] or "",
                    " ".join(name_tokens(constant) for constant in statement_constants),
                ),
            )
    connection.commit()
    connection.execute("INSERT INTO decl_fts(decl_fts) VALUES('optimize')")
    connection.execute("CREATE INDEX decl_tier ON decl(tier)")
    connection.commit()
    connection.execute("VACUUM")
    connection.close()
    duplicate_type_groups = Counter(
        (record["type_hash"], record["type"]) for record in records if record["type"]
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "mathlib_rev": mathlib_rev,
        "lean_toolchain": toolchain,
        "theorem_constants": len(records),
        "tiers": {tier: tiers.get(tier, 0) for tier in TIER_ORDER},
        "textbook_signals": dict(signals_total.most_common()),
        "origins": dict(Counter(origin_of(record["module"]) for record in records).most_common()),
        "with_docstring": sum(1 for record in records if record["doc"]),
        "duplicate_statement_groups": sum(1 for n in duplicate_type_groups.values() if n > 1),
        "decls_sha256": digest.hexdigest(),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mathlib-rev", required=True)
    parser.add_argument("--toolchain", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.raw, args.out, mathlib_rev=args.mathlib_rev, toolchain=args.toolchain),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
