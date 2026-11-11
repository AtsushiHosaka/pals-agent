"""Write the reviewed syntax-kind allow-list into scripts/eval/warm_worker.lean.

    uv run python scripts/eval/gen_allowed_kinds.py          # rewrite the Lean file
    uv run python scripts/eval/gen_allowed_kinds.py --check   # fail if the Lean file is stale

The single source of truth is pals_agent/content_dictionaries/allowed-syntax-kinds-v1.txt.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KINDS = ROOT / "pals_agent/content_dictionaries/allowed-syntax-kinds-v1.txt"
LEAN = ROOT / "scripts/eval/warm_worker.lean"
_BLOCK = re.compile(
    r"(-- BEGIN ALLOWED_KINDS[^\n]*\n)def allowedKinds : List Name := .*?(\n-- END ALLOWED_KINDS)",
    re.S,
)


def kinds() -> list[str]:
    return [
        line.strip()
        for line in KINDS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def lean_list(names: list[str]) -> str:
    items = ["`" + (n if n.startswith("«") or "«" in n else n) for n in names]
    body = ",\n   ".join(items)
    return f"[{body}]"


def rendered() -> str:
    text = LEAN.read_text()
    return _BLOCK.sub(
        lambda m: f"{m.group(1)}def allowedKinds : List Name := {lean_list(kinds())}{m.group(2)}",
        text,
    )


def main() -> int:
    new = rendered()
    if "--check" in sys.argv:
        return 0 if new == LEAN.read_text() else 1
    LEAN.write_text(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
