"""Size of the minimal import set per statement, measured on the library's own declarations.

For a random sample of declarations it plans the imports its statement needs (the way a request's
statement would be planned) and reports how many modules Lean would load, against three
baselines: `import Mathlib` plus the whole Frontier, the declaration's own module's imports, and
the union of what the sample needs (the set an image must build to serve those statements).
Only numbers are printed: no statement text, no declaration names.

    python -m tools.stacks_index.measure_imports --index import_index.sqlite --stacks DIR \\
        --prefix StacksFrontier.AlgebraicGeometry --files 600 --per-file 2
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stacks_index.extract import extract_file
from tools.stacks_index.import_index import _OPEN, ImportIndex, _open_names
from tools.stacks_index.shape import statement_shape

KINDS = ("theorem", "def", "abbrev")


def _percentiles(values: list[int]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def at(q: float) -> float:
        return float(ordered[min(len(ordered) - 1, int(q * len(ordered)))])

    return {
        "min": float(ordered[0]),
        "p25": at(0.25),
        "median": float(statistics.median(ordered)),
        "p75": at(0.75),
        "p90": at(0.90),
        "max": float(ordered[-1]),
        "mean": round(statistics.fmean(ordered), 1),
    }


def measure(
    index: ImportIndex,
    stacks_dir: Path,
    *,
    prefix: str,
    files: int,
    per_file: int,
    seed: int = 0,
) -> dict[str, Any]:
    rows = index.db.execute(
        "SELECT name, path FROM module WHERE scanned = 1 AND n_decls > 0 AND name LIKE ?"
        " ORDER BY name",
        (f"{prefix}%",),
    ).fetchall()
    rng = random.Random(seed)
    rng.shuffle(rows)
    full_loaded = len(index.closure_of(["StacksFrontier", "Mathlib"], "all"))
    umbrella_loaded = len(index.closure_of(["StacksFrontier"], "all"))
    per_statement: dict[str, list[int]] = {
        "direct_imports": [],
        "loaded_modules": [],
        "stacks_modules": [],
        "frontier_modules": [],
        "own_module_loaded": [],
        "own_module_stacks": [],
    }
    needed: set[str] = set()
    unresolved_statements = 0
    count = 0
    for module, path in rows[:files]:
        text = (stacks_dir / path).read_text(encoding="utf-8", errors="replace")
        opens = [n for body in _OPEN.findall(text) for n in _open_names(body)]
        own_bits = index._bits(index.module_id[module], "all")
        own_stacks = sum(
            1
            for i in index._ids(own_bits)
            if index.module_name[i].startswith(("StacksFrontier", "StacksCore"))
        )
        candidates = [
            d for d in extract_file(stacks_dir / path, stacks_dir).declarations if d.kind in KINDS
        ]
        rng.shuffle(candidates)
        for declaration in candidates[:per_file]:
            shape = statement_shape(declaration.signature, declaration.context)
            names = [*shape["conclusion_constants"], *shape["hypothesis_constants"]]
            namespaces = [declaration.namespace] if declaration.namespace else []
            plan = index.plan(names, opens, namespaces)
            count += 1
            unresolved_statements += bool(plan.unresolved)
            per_statement["direct_imports"].append(len(plan.imports))
            per_statement["loaded_modules"].append(plan.loaded_size)
            per_statement["stacks_modules"].append(len(plan.stacks_modules))
            per_statement["frontier_modules"].append(len(plan.frontier_modules))
            per_statement["own_module_loaded"].append(own_bits.bit_count())
            per_statement["own_module_stacks"].append(own_stacks)
            needed.update(plan.stacks_modules)
    return {
        "prefix": prefix,
        "statements": count,
        "files": min(files, len(rows)),
        "baseline_import_everything_loaded": full_loaded,
        "baseline_frontier_umbrella_loaded": umbrella_loaded,
        "statements_with_unresolved_names": unresolved_statements,
        "per_statement": {k: _percentiles(v) for k, v in per_statement.items()},
        "union_of_stacks_modules_needed": len(needed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stacks", type=Path, required=True)
    parser.add_argument("--prefix", default="StacksFrontier.AlgebraicGeometry")
    parser.add_argument("--files", type=int, default=600)
    parser.add_argument("--per-file", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    result = measure(
        ImportIndex(args.index),
        args.stacks,
        prefix=args.prefix,
        files=args.files,
        per_file=args.per_file,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
