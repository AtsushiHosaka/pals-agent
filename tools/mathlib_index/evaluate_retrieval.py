"""Measure candidate-search recall on held-out problems; no model is called.

Set A: Mathlib's `docs/100.yaml`, `docs/1000.yaml` and `docs/undergrad.yaml` (title to declaration).
Set B: proof-term premises of verified PALS cards from `extract_premises.py`.
Neither set is read by `build_index.py`. Tuning, if any, may only use the `dev` split of Set B.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mathlib_index.search import (
    Candidate,
    MathlibIndex,
    lean_query_terms,
    natural_query_terms,
    reciprocal_rank_fusion,
)

KS = (1, 5, 10, 20, 50)
POOL = 200


def load_tiers(decls_path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    with gzip.open(decls_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            rows[row["name"]] = {
                "tier": row["tier"],
                "additive_source": row["additive_source"],
                "signals": row["signals"],
            }
    return rows


def load_named_results(docs_dir: Path) -> list[dict[str, Any]]:
    import yaml  # type: ignore[import-untyped]

    results: list[dict[str, Any]] = []
    for filename in ("100.yaml", "1000.yaml"):
        data = yaml.safe_load((docs_dir / filename).read_text(encoding="utf-8"))
        for key, item in data.items():
            golds = [*([item["decl"]] if item.get("decl") else []), *(item.get("decls") or [])]
            if golds and item.get("title"):
                results.append(
                    {"set": filename, "id": str(key), "title": item["title"], "gold": golds}
                )

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, (*path, str(key)))
        elif isinstance(node, str) and node.strip():
            results.append(
                {
                    "set": "undergrad.yaml",
                    "id": "/".join(path),
                    "title": path[-1],
                    "gold": [node.strip()],
                }
            )

    walk(yaml.safe_load((docs_dir / "undergrad.yaml").read_text(encoding="utf-8")), ())
    return results


def rank_of(ranking: list[Candidate], gold: set[str]) -> int | None:
    for rank, candidate in enumerate(ranking, start=1):
        if candidate.name in gold:
            return rank
    return None


def evaluate_named(
    index: MathlibIndex, tiers: dict[str, dict[str, Any]], named: list[dict[str, Any]]
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for set_name in ("100.yaml", "1000.yaml", "undergrad.yaml"):
        entries = [entry for entry in named if entry["set"] == set_name]
        resolved = []
        for entry in entries:
            theorem_golds = {gold for gold in entry["gold"] if gold in tiers}
            if theorem_golds:
                resolved.append({**entry, "gold_theorems": theorem_golds})
        tier_counts = Counter(
            min(
                (tiers[gold]["tier"] for gold in entry["gold_theorems"]),
                key=(
                    "textbook",
                    "general",
                    "rewrite_api",
                    "generated_copy",
                    "instance",
                    "deprecated",
                    "tooling",
                    "internal",
                ).index,
            )
            for entry in resolved
        )
        scopes = {}
        for scope in ("textbook_only", "core", "full"):
            search_scope = "core" if scope != "full" else "full"
            ranks: list[int | None] = []
            for entry in resolved:
                pool = index.text_search(
                    natural_query_terms(entry["title"]), k=POOL, scope=search_scope
                )
                if scope == "textbook_only":
                    pool = [c for c in pool if tiers[c.name]["tier"] == "textbook"]
                ranks.append(rank_of(pool, entry["gold_theorems"]))
            scopes[scope] = {
                f"recall@{k}": round(sum(1 for r in ranks if r and r <= k) / max(len(ranks), 1), 4)
                for k in KS
            }
        report[set_name] = {
            "entries_with_decl": len(entries),
            "gold_is_theorem": len(resolved),
            "best_gold_tier": dict(tier_counts),
            "scopes": scopes,
        }
    return report


def split_of(card_id: str) -> str:
    return "dev" if hashlib.sha256(card_id.encode()).hexdigest()[0] < "4" else "test"


def explicit_premises(card: dict[str, Any], tiers: dict[str, dict[str, Any]]) -> set[str]:
    """Proof-term theorems whose last name component is also written in the proof source."""
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_']*", card["witness"]))
    return {
        premise
        for premise in card["premises"]
        if premise.rsplit(".", 1)[-1] in tokens
        and tiers.get(premise, {}).get("tier")
        in {"textbook", "general", "rewrite_api", "generated_copy"}
    }


def method_rankings(
    index: MathlibIndex, card: dict[str, Any], scope: str
) -> dict[str, list[Candidate]]:
    conclusion = card["conclusion_constants"]
    hypotheses = card["hypothesis_constants"]
    rankings = {
        "lean_text": index.text_search(lean_query_terms(card["lean_target"]), k=POOL, scope=scope),
        "symbol": index.symbol_search(conclusion, hypotheses, k=POOL, scope=scope),
    }
    if card.get("statement_en"):
        rankings["nl_text"] = index.text_search(
            natural_query_terms(card["statement_en"]), k=POOL, scope=scope
        )
        rankings["nl_plus_symbol"] = reciprocal_rank_fusion(
            [rankings["nl_text"], rankings["symbol"]], k=POOL
        )
    if card.get("statement_ja"):
        rankings["ja_text"] = index.text_search(
            natural_query_terms(card["statement_ja"]), k=POOL, scope=scope
        )
    rankings["lean_plus_symbol"] = reciprocal_rank_fusion(
        [rankings["lean_text"], rankings["symbol"]], k=POOL
    )
    return rankings


def evaluate_premises(
    index: MathlibIndex, tiers: dict[str, dict[str, Any]], cards: list[dict[str, Any]]
) -> dict[str, Any]:
    usable = []
    for card in cards:
        gold = explicit_premises(card, tiers)
        if gold:
            usable.append({**card, "gold": gold})
    report: dict[str, Any] = {
        "cards": len(cards),
        "cards_with_explicit_premises": len(usable),
        "explicit_premises": sum(len(card["gold"]) for card in usable),
        "gold_tiers": dict(
            Counter(tiers[gold]["tier"] for card in usable for gold in card["gold"]).most_common()
        ),
    }
    for scope in ("core", "full"):
        aggregates: dict[tuple[str, str], list[dict[int, tuple[float, bool]]]] = {}
        timings: dict[str, list[float]] = {}
        for card in usable:
            started = time.perf_counter()
            rankings = method_rankings(index, card, scope)
            timings.setdefault("all_methods_seconds", []).append(time.perf_counter() - started)
            for method, ranking in rankings.items():
                per_k = {}
                for k in KS:
                    top = {candidate.name for candidate in ranking[:k]}
                    found = len(top & card["gold"])
                    per_k[k] = (found / len(card["gold"]), found > 0)
                for key in (split_of(card["card_id"]), card["source_set"]):
                    aggregates.setdefault((method, key), []).append(per_k)
        report[scope] = {
            f"{method}/{key}": {
                "n": len(rows),
                **{f"recall@{k}": round(statistics.mean(row[k][0] for row in rows), 4) for k in KS},
                **{
                    f"hit@{k}": round(statistics.mean(row[k][1] for row in rows), 4)
                    for k in (10, 20)
                },
            }
            for (method, key), rows in sorted(aggregates.items())
        }
        report[scope]["median_seconds_per_card_all_methods"] = round(
            statistics.median(timings["all_methods_seconds"]), 3
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--mathlib-docs", type=Path, required=True)
    parser.add_argument("--gold-premises", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    index = MathlibIndex(args.index_dir / "index.sqlite")
    tiers = load_tiers(args.index_dir / "decls.jsonl.gz")
    cards = [json.loads(line) for line in args.gold_premises.read_text("utf-8").splitlines()]
    report = {
        "named_results": evaluate_named(index, tiers, load_named_results(args.mathlib_docs)),
        "premises": evaluate_premises(index, tiers, cards),
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
