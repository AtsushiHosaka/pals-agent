"""Summarise an inventory: index rows + compile results + axiom report + 100/1000 yaml topics.

    python -m tools.library_index.inventory_report --index decls.jsonl.gz --compile compile.json \
        [--axioms axioms.json] --yaml docs/100.yaml docs/1000.yaml --out summary.json

Only counts what the inputs contain; it runs nothing. ``axioms.json`` is the output of
``Archive/AxiomReport.lean`` style runs: a list of ``{"module","name","axioms"}`` rows.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

STANDARD = frozenset({"propext", "Classical.choice", "Quot.sound"})


def parse_yaml_entries(path: Path) -> list[dict[str, Any]]:
    """The flat ``id: / key : value`` entries of Mathlib's docs/100.yaml and 1000.yaml."""
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    list_key: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("#") or not raw.strip():
            continue
        if not raw.startswith(" "):
            current = {"id": raw.rstrip(":").strip()}
            entries.append(current)
            list_key = None
            continue
        if current is None:
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and list_key:
            current.setdefault(list_key, []).append(item.group(1).strip())
            continue
        kv = re.match(r"^\s+([A-Za-z_]+)\s*:\s*(.*)$", raw)
        if kv:
            key, value = kv.group(1), kv.group(2).strip()
            if value:
                current[key] = value
                list_key = None
            else:
                list_key = key
    return entries


def _decl_names(entry: dict[str, Any]) -> list[str]:
    names = []
    if isinstance(entry.get("decl"), str):
        names.append(entry["decl"])
    names += [d for d in entry.get("decls", []) if isinstance(d, str)]
    return names


def distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {}
    ordered = sorted(values)

    def q(fraction: float) -> int:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {
        "n": len(values), "min": ordered[0], "median": statistics.median(ordered),
        "p90": q(0.9), "p99": q(0.99), "max": ordered[-1],
        "mean": round(statistics.mean(values), 1),
    }


def topic_of(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def summarise(
    rows: list[dict[str, Any]], compiled: list[dict[str, Any]], axioms: list[dict[str, Any]] | None,
    yaml_entries: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    ok_modules = {c["module"] for c in compiled if c["status"] == "ok"}
    theorem_rows = [r for r in rows if r["kind"] == "theorem"]
    by_topic: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_topic[topic_of(r["path"])][r["kind"]] += 1
    result: dict[str, Any] = {
        "files": len({r["module"] for r in rows}),
        "declarations": len(rows),
        "theorems_by_source_text": len(theorem_rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "topics": {t: dict(c) for t, c in sorted(by_topic.items())},
        "theorem_span_lines": distribution([r.get("span_lines", 0) for r in theorem_rows]),
        "compile": {
            "files": len(compiled),
            "ok": len(ok_modules),
            "failed": [
                {"module": c["module"], "status": c["status"], "first_error": c["first_error"]}
                for c in compiled if c["status"] != "ok"
            ],
            "files_with_sorry_warning": [c["module"] for c in compiled if c["sorry_warnings"]],
            "wall_s_total": round(sum(c["wall_s"] for c in compiled), 1),
            "wall_s_per_file": distribution([int(c["wall_s"]) for c in compiled]),
            "max_rss_bytes_peak": max((c.get("max_rss_bytes", 0) for c in compiled), default=0),
            "olean_bytes_total": sum(c["olean_bytes"] for c in compiled),
            "slowest": sorted(
                ({"module": c["module"], "wall_s": c["wall_s"]} for c in compiled),
                key=lambda x: -x["wall_s"],
            )[:5],
        },
    }
    theorems_in_ok = [r for r in theorem_rows if r["module"] in ok_modules]
    result["theorems_in_compiling_files"] = len(theorems_in_ok)
    if axioms is not None:
        usage: Counter[str] = Counter()
        beyond: dict[str, set[str]] = defaultdict(set)
        sorry_theorems: list[str] = []
        for row in axioms:
            extra = set(row["axioms"]) - STANDARD
            usage[",".join(sorted(row["axioms"])) or "(none)"] += 1
            for axiom in extra:
                beyond[axiom].add(row["name"])
            if "sorryAx" in row["axioms"]:
                sorry_theorems.append(row["name"])
        result["axioms"] = {
            "theorems_checked": len(axioms),
            "by_axiom_set": dict(usage.most_common()),
            "beyond_standard_three": {a: sorted(n)[:10] for a, n in beyond.items()},
            "beyond_standard_three_counts": {a: len(n) for a, n in beyond.items()},
            "sorryAx_theorems": len(sorry_theorems),
        }
    names = {r["name"]: r for r in rows}
    suffix_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        suffix_index[r["name"].split(".")[-1]].append(r)
    for label, entries in yaml_entries.items():
        listed = 0
        in_archive = 0
        for entry in entries:
            declared = _decl_names(entry)
            listed += bool(declared)
            if any(d in names for d in declared):
                in_archive += 1
        result[f"yaml_{label}"] = {
            "entries": len(entries), "with_decl": listed, "decl_in_archive_index": in_archive,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--compile", type=Path, required=True)
    parser.add_argument("--axioms", type=Path)
    parser.add_argument("--yaml", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with gzip.open(args.index, "rt") as handle:
        rows = [json.loads(line) for line in handle.read().splitlines()]
    compiled = json.loads(args.compile.read_text())
    axioms = json.loads(args.axioms.read_text())["rows"] if args.axioms else None
    yamls = {p.stem: parse_yaml_entries(p) for p in args.yaml}
    args.out.write_text(
        json.dumps(summarise(rows, compiled, axioms, yamls), indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
