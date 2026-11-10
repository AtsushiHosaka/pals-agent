"""Model-free candidate search over the Stacks declaration index.

Same shape as `tools.mathlib_index.search.MathlibIndex` (`text_search`, `symbol_search`,
`describe`), so the two indexes can be queried and fused the same way. Results are unverified
candidates found by lexical matching on source text. They never establish that a statement
holds or applies: only Lean can decide that, in an environment that actually contains Stacks.

`scope="core"` (default) searches only human-reviewed `StacksCore`; `scope="all"` also returns
`StacksFrontier` entries when the index was built with `--include-frontier`. Entries of kind
`upstream` are Stacks tags attached to declarations defined elsewhere (Mathlib): only a name
and the tag, no statement.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from functools import cached_property
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mathlib_index.search import (
    Candidate,
    lean_query_terms,
    natural_query_terms,
    reciprocal_rank_fusion,
)
from tools.stacks_index.shape import query_shape

# Reviewed layers: the legacy word and its generic successor (see pals_agent.lean_library_manifest).
_REVIEWED = frozenset({"core", "kernel-checked-reviewed"})

__all__ = [
    "Candidate",
    "StacksIndex",
    "lean_query_terms",
    "natural_query_terms",
    "reciprocal_rank_fusion",
]

# bm25 weights for (name_words, doc, statement_words, module_words, tag_text, body_words)
DEFAULT_WEIGHTS = (8.0, 3.0, 1.0, 2.0, 3.0, 0.5)
COMMON_CONSTANT_IDF = 2.5


class StacksIndex:
    def __init__(self, path: Path) -> None:
        self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    @staticmethod
    def _filter(scope: str, include_upstream: bool) -> tuple[str, list[str]]:
        clauses: list[str] = []
        params: list[str] = []
        if scope == "core":
            clauses.append("d.trust IN ('core', 'kernel-checked-reviewed')")
        elif scope != "all":
            raise ValueError(f"unknown scope {scope!r}; use 'core' or 'all'")
        if not include_upstream:
            clauses.append("d.kind != 'upstream'")
        return (" AND " + " AND ".join(clauses)) if clauses else "", params

    def text_search(
        self,
        terms: list[str],
        *,
        k: int = 20,
        scope: str = "core",
        include_upstream: bool = True,
        weights: tuple[float, ...] = DEFAULT_WEIGHTS,
    ) -> list[Candidate]:
        unique = list(dict.fromkeys(terms))
        if not unique:
            return []
        weights = (*weights, *DEFAULT_WEIGHTS[len(weights) :])
        match = " OR ".join('"' + term.replace('"', "") + '"' for term in unique)
        extra, params = self._filter(scope, include_upstream)
        rows = self._db.execute(
            f"SELECT d.name, bm25(decl_fts, {', '.join('?' * len(weights))}) AS rank FROM decl_fts "
            f"JOIN decl d ON d.id = decl_fts.rowid WHERE decl_fts MATCH ?{extra} "
            f"ORDER BY rank, d.name LIMIT ?",
            (*weights, match, *params, k),
        ).fetchall()
        return [Candidate(name, -rank) for name, rank in rows]

    @cached_property
    def _symbols(
        self,
    ) -> tuple[list[str], list[str], list[float], dict[str, list[tuple[int, bool]]]]:
        names: list[str] = []
        scopes: list[str] = []
        mass_input: list[set[str]] = []
        postings: dict[str, list[tuple[int, bool]]] = defaultdict(list)
        rows = self._db.execute(
            "SELECT name, trust, conclusion_constants, hypothesis_constants FROM decl"
            " WHERE kind != 'upstream'"
        )
        for doc_id, (name, trust, conclusion, hypotheses) in enumerate(rows):
            names.append(name)
            scopes.append(trust)
            conclusion_set = set(json.loads(conclusion))
            hypothesis_set = set(json.loads(hypotheses)) - conclusion_set
            for constant in conclusion_set:
                postings[constant].append((doc_id, True))
            for constant in hypothesis_set:
                postings[constant].append((doc_id, False))
            mass_input.append(conclusion_set | hypothesis_set)
        total = max(len(names), 1)
        self._common_idf = min(COMMON_CONSTANT_IDF, math.log(total) / 2)
        self._idf = {constant: math.log(total / len(docs)) for constant, docs in postings.items()}
        masses = [sum(self._idf[c] for c in constants) for constants in mass_input]
        return names, scopes, masses, postings

    def symbol_search(
        self,
        conclusion_constants: list[str],
        hypothesis_constants: list[str],
        *,
        k: int = 20,
        scope: str = "core",
        hypothesis_weight: float = 0.5,
    ) -> list[Candidate]:
        """Rank by IDF-weighted overlap of constants read from the source statement."""
        names, trusts, masses, postings = self._symbols
        conclusion = set(conclusion_constants)
        hypotheses = set(hypothesis_constants) - conclusion
        overlap: dict[int, float] = defaultdict(float)
        query_mass = 0.0
        for constant, weight in [(c, 1.0) for c in conclusion] + [
            (c, hypothesis_weight) for c in hypotheses
        ]:
            idf = self._idf.get(constant)
            if idf is None:
                continue
            query_mass += idf * weight
            if idf < self._common_idf:
                continue
            for doc_id, in_conclusion in postings[constant]:
                overlap[doc_id] += idf * weight * (1.0 if in_conclusion else 0.5)
        scored = [
            Candidate(names[doc_id], value / (query_mass + masses[doc_id] - value + 1e-9))
            for doc_id, value in overlap.items()
            if scope == "all" or trusts[doc_id] in _REVIEWED
        ]
        scored.sort(key=lambda candidate: (-candidate.score, candidate.name))
        return scored[:k]

    def symbol_search_lean(self, lean_statement: str, **kwargs: Any) -> list[Candidate]:
        shape = query_shape(lean_statement)
        return self.symbol_search(
            shape["conclusion_constants"], shape["hypothesis_constants"], **kwargs
        )

    def describe(self, names: list[str]) -> list[dict[str, Any]]:
        results = []
        for name in names:
            row = self._db.execute(
                "SELECT name, kind, trust, type, module, line, doc, tags FROM decl WHERE name = ?",
                (name,),
            ).fetchone()
            if row:
                results.append(
                    {
                        "name": row[0],
                        "kind": row[1],
                        "trust": row[2],
                        "type": row[3],
                        "module": row[4],
                        "line": row[5],
                        "doc": row[6],
                        "tags": json.loads(row[7]),
                    }
                )
        return results

    def by_tag(self, tag: str, *, scope: str = "core") -> list[dict[str, str]]:
        """Declarations carrying a Stacks tag (e.g. `00DJ`), with where the tag came from."""
        rows = self._db.execute(
            "SELECT name, comment, source, trust FROM tag WHERE tag = ? ORDER BY name",
            (tag.upper(),),
        ).fetchall()
        return [
            {"name": n, "comment": c, "source": s, "trust": t}
            for n, c, s, t in rows
            if scope == "all" or t == "core"
        ]

    def manifest(self) -> dict[str, Any]:
        path = Path(self._db.execute("PRAGMA database_list").fetchone()[2]).parent / "manifest.json"
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True, help="directory with index.sqlite")
    parser.add_argument("query", nargs="?", help="natural-language query")
    parser.add_argument("--lean", help="a Lean statement; searched by the constants it mentions")
    parser.add_argument("--tag", help="list declarations carrying this Stacks tag")
    parser.add_argument("--scope", choices=("core", "all"), default="core")
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args()
    index = StacksIndex(args.index / "index.sqlite")
    if args.tag:
        print(json.dumps(index.by_tag(args.tag, scope=args.scope), ensure_ascii=False, indent=2))
        return
    rankings = []
    if args.query:
        rankings.append(index.text_search(natural_query_terms(args.query), k=50, scope=args.scope))
    if args.lean:
        rankings.append(index.symbol_search_lean(args.lean, k=50, scope=args.scope))
        rankings.append(index.text_search(lean_query_terms(args.lean), k=50, scope=args.scope))
    for candidate in reciprocal_rank_fusion(rankings, k=args.k):
        info = index.describe([candidate.name])
        row = info[0] if info else {}
        print(f"{candidate.score:.4f}  {candidate.name}  [{row.get('kind')}/{row.get('module')}]")


if __name__ == "__main__":
    main()
