"""Write the dev_unseen items of the freshman-v1 manifest (pals docs/generation-eval-freshman-v1)
to a problems file for ``run_hetero_api_sim.py --problems-file``.

The manifest holds both splits. Only items whose ``split`` is ``dev_unseen`` are kept; every other
item is dropped as it is read and nothing of it is printed, written or run (held_out is for the
final check only). The output is a local file with statements: keep it out of git.

    extract_dev_split.py --manifest PATH/manifest.json --out dev_unseen.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

KEEP = "dev_unseen"


def extract(manifest: dict) -> dict:
    kept = [p for p in manifest["problems"] if p.get("split") == KEEP]
    return {"faithfulness_rule": manifest.get("faithfulness_rule", ""), "problems": kept}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    out = extract(json.loads(args.manifest.read_text()))
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"wrote {len(out['problems'])} {KEEP} items to {args.out}")


if __name__ == "__main__":
    main()
