"""Ask Lean whether a statement is already closed by Mathlib, using `exact?` on the elaborated goal.

This is the identity check the index relies on: it compares types inside Lean, never statement text.
A closed goal is Lean's own result; the statements come from verified cards and `by exact?` replaces
their proofs. No model is called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.mathlib_index.extract_premises import catalog_bundles, requested_jobs

_DECLARATION = re.compile(r"^(example|theorem|lemma)\b", re.MULTILINE)


def header_of(source: str) -> str:
    """Keep imports and `open` lines, replacing any narrower import with the pinned full Mathlib."""
    match = _DECLARATION.search(source)
    head = source[: match.start()] if match else source
    kept = [line for line in head.splitlines() if not line.startswith("import ")]
    marker = next((i for i, line in enumerate(kept) if line.startswith("-- manifest card:")), None)
    if marker is not None:
        kept = kept[:marker]
    return "import Mathlib\n" + "\n".join(kept) + "\n"


def check_batch(batch: dict[str, Any], *, lean: str, timeout: float) -> list[dict[str, Any]]:
    body = [batch["header"], "set_option maxHeartbeats 400000\n"]
    for position, card in enumerate(batch["cards"]):
        statement = card["lean_target"].strip()
        body.append(f'#eval IO.println "PALS_START {position}"\n{statement} := by exact?\n')
    body.append('#eval IO.println "PALS_DONE"\n')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Check.lean"
        path.write_text("\n".join(body), encoding="utf-8")
        started = time.monotonic()
        try:
            output = subprocess.run(
                [lean, "--json", str(path)],
                env=dict(os.environ),
                capture_output=True,
                text=True,
                timeout=timeout,
            ).stdout
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout.decode() if isinstance(exc.stdout, bytes) else ""
        elapsed = time.monotonic() - started
    outcomes: dict[int, dict[str, Any]] = {}
    current = -1
    for line in output.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = message.get("data", "")
        started_card = re.match(r"PALS_START (\d+)", text)
        if started_card:
            current = int(started_card.group(1))
            outcomes[current] = {"closed": False, "error": None, "suggestion": None}
            continue
        if current < 0 or text.startswith("PALS_DONE"):
            continue
        outcome = outcomes[current]
        if "Try this" in text and outcome["suggestion"] is None:
            outcome["closed"] = message.get("severity") != "error"
            outcome["suggestion"] = text.replace("Try this:", "").strip()[:300]
        elif message.get("severity") == "error" and outcome["suggestion"] is None:
            outcome["error"] = text[:200]
    return [
        {
            "card_id": card["card_id"],
            "source_set": card["source_set"],
            "batch_seconds": round(elapsed, 1),
            "batch_size": len(batch["cards"]),
            **outcomes.get(position, {"closed": False, "error": "no result", "suggestion": None}),
        }
        for position, card in enumerate(batch["cards"])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--requested-corpus", type=Path, required=True)
    parser.add_argument("--lean", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalog-sample", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=1200.0)
    args = parser.parse_args()
    catalog = catalog_bundles(args.inventory, args.repo_root)
    ranked = sorted(
        (
            (hashlib.sha256(card["card_id"].encode()).hexdigest(), job["source"], card)
            for job in catalog
            for card in job["cards"].values()
        ),
        key=lambda item: item[0],
    )[: args.catalog_sample]
    batches: dict[str, dict[str, Any]] = {}
    for _, source, card in ranked:
        header = header_of(source)
        batches.setdefault(header, {"header": header, "cards": []})["cards"].append(card)
    runs: list[dict[str, Any]] = []
    for batch in batches.values():
        cards = batch["cards"]
        for start in range(0, len(cards), args.batch_size):
            runs.append(
                {"header": batch["header"], "cards": cards[start : start + args.batch_size]}
            )
    for job in requested_jobs(args.requested_corpus):
        runs.append({"header": header_of(job["source"]), "cards": list(job["cards"].values())})

    with ThreadPoolExecutor(args.workers) as pool:
        results = [
            row
            for rows in pool.map(
                lambda run: check_batch(run, lean=args.lean, timeout=args.timeout), runs
            )
            for row in rows
        ]
    args.out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in results) + "\n", encoding="utf-8"
    )
    usable = [row for row in results if row["error"] is None or row["closed"]]
    print(
        json.dumps(
            {
                "checked": len(results),
                "closed": sum(row["closed"] for row in results),
                "not_closed": sum(1 for row in results if not row["closed"]),
                "without_error_message": len(usable),
            }
        )
    )


if __name__ == "__main__":
    main()
