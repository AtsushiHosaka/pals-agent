"""Smoke queries for the Stacks index (no model calls).

Each query is a plain-language question. A candidate counts as a hit when its *name* matches the
`topic` regex and, for `frontier` queries, it also comes from `StacksFrontier` (schemes, sheaf
cohomology and the like are not in the human-reviewed `StacksCore`). This is a smoke
check of the lexical search, not a held-out evaluation: the queries and patterns were written by
hand after looking at what the index contains.

    python -m tools.stacks_index.probe --index OUT [--scope core|all] [-k 5]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stacks_index.search import StacksIndex, natural_query_terms


@dataclass(frozen=True, slots=True)
class Probe:
    query: str
    topic: str
    frontier: bool = False


PROBES = (
    # Schemes and sheaf cohomology: formalized in StacksFrontier only.
    Probe("properties of a flat morphism of schemes", r"[Ff]lat", True),
    Probe("sheaf cohomology vanishing on a noetherian space", r"[Cc]ohomology", True),
    Probe("affine scheme is the spectrum of its ring of global sections", r"[Aa]ffine|Spec", True),
    Probe("separated morphism of schemes diagonal is a closed immersion", r"[Ss]eparated", True),
    Probe("quasi-compact and quasi-separated morphism", r"[Qq]uasi[Cc]ompact|[Qq]uasi[Ss]ep", True),
    # Commutative algebra, topology and sites underneath: StacksCore territory.
    Probe("flat module tensor product preserves injections", r"Flat"),
    Probe("spectrum of a ring prime ideals Zariski topology", r"PrimeSpectrum"),
    Probe("separated map of topological spaces diagonal is closed", r"[Ss]eparated"),
    Probe("noetherian topological space", r"[Nn]oetherian"),
    Probe("Jacobson ring closed points are dense", r"[Jj]acobson"),
    Probe("fibered category in groupoids over a site", r"[Ff]ibered"),
)


def run(index: StacksIndex, *, scope: str, k: int) -> list[tuple[Probe, int | None, list[str]]]:
    results = []
    for probe in PROBES:
        hits = index.text_search(natural_query_terms(probe.query), k=k, scope=scope)
        names = [hit.name for hit in hits]
        trusts = {row["name"]: row["trust"] for row in index.describe(names)}
        topic = re.compile(probe.topic)
        rank = next(
            (
                position
                for position, name in enumerate(names, 1)
                if topic.search(name) and (not probe.frontier or trusts.get(name) == "frontier")
            ),
            None,
        )
        results.append((probe, rank, names))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--scope", choices=("core", "all"), default="core")
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    index = StacksIndex(args.index / "index.sqlite")
    results = run(index, scope=args.scope, k=args.k)
    for probe, rank, names in results:
        label = "frontier-only" if probe.frontier else "core"
        status = f"hit@{rank}" if rank else "MISS"
        print(f"[{status}] ({label}) {probe.query}")
        for name in names:
            print(f"    {name}")
    for frontier, label in ((True, "frontier-only topics"), (False, "core topics")):
        group = [rank for probe, rank, _ in results if probe.frontier == frontier]
        print(f"scope={args.scope} top-{args.k} {label}: {sum(1 for r in group if r)}/{len(group)}")


if __name__ == "__main__":
    main()
