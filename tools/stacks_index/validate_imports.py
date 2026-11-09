"""Self-consistency check of the import index against the library's own source.

A declaration D in module M compiled with M's imports, so every constant D's statement names
must live in M or in the closure of M's imports. For a sample of declarations this resolves the
statement's constants with the index and counts the ones whose chosen definition is *outside* that
closure (a wrong resolution) or not found at all (unresolved: Lean core, generated names, dot
notation on variables). It needs no Lean build and no model.

    python -m tools.stacks_index.validate_imports --index import_index.sqlite \\
        --stacks DIR --sample 400
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stacks_index.extract import extract_file
from tools.stacks_index.import_index import _OPEN, ImportIndex, _open_names
from tools.stacks_index.shape import statement_shape


def validate(
    index: ImportIndex, stacks_dir: Path, layer: str, *, sample: int, seed: int = 0
) -> dict[str, object]:
    rows = index.db.execute(
        "SELECT name, path FROM module"
        " WHERE layer = ? AND scanned = 1 AND n_decls > 0 ORDER BY name",
        (layer,),
    ).fetchall()
    random.Random(seed).shuffle(rows)
    totals: Counter[str] = Counter()
    wrong_examples: list[dict[str, str]] = []
    files = 0
    for module, path in rows:
        if files >= sample:
            break
        files += 1
        text = (stacks_dir / path).read_text(encoding="utf-8", errors="replace")
        opens = [n for body in _OPEN.findall(text) for n in _open_names(body)]
        scope = index._root_closure(index.module_id[module], "public")
        allowed = {index.module_name[i] for i in scope}
        result = extract_file(stacks_dir / path, stacks_dir)
        for declaration in result.declarations:
            if declaration.kind not in ("theorem", "def", "abbrev", "instance"):
                continue
            shape = statement_shape(declaration.signature, declaration.context)
            names = [*shape["conclusion_constants"], *shape["hypothesis_constants"]]
            namespaces = [declaration.namespace] if declaration.namespace else []
            for identifier in names:
                totals["constants"] += 1
                hits, prefix = index.resolve(identifier, opens, namespaces)
                if not hits:
                    totals["unresolved"] += 1
                    continue
                inside = [h for h in hits if h.module in allowed]
                if not inside:
                    totals["outside_closure"] += 1
                    if len(wrong_examples) < 20:
                        wrong_examples.append(
                            {"module": module, "identifier": identifier, "found_in": hits[0].module}
                        )
                    continue
                totals["resolved_inside"] += 1
                if prefix:
                    totals["via_prefix"] += 1
                if len({(h.name, h.module) for h in hits}) > 1:
                    totals["ambiguous"] += 1
    constants = totals["constants"] or 1
    return {
        "layer": layer,
        "files": files,
        "constants": totals["constants"],
        "resolved_inside_closure": totals["resolved_inside"],
        "outside_closure": totals["outside_closure"],
        "unresolved": totals["unresolved"],
        "via_prefix": totals["via_prefix"],
        "ambiguous": totals["ambiguous"],
        "share_inside": round(totals["resolved_inside"] / constants, 4),
        "share_outside": round(totals["outside_closure"] / constants, 4),
        "share_unresolved": round(totals["unresolved"] / constants, 4),
        "examples_outside": wrong_examples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stacks", type=Path, required=True)
    parser.add_argument("--layer", default="frontier")
    parser.add_argument("--sample", type=int, default=400, help="number of files")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    result = validate(
        ImportIndex(args.index), args.stacks, args.layer, sample=args.sample, seed=args.seed
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
