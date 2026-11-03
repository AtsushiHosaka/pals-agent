"""Compile verified PALS cards and record, from Lean, the theorems each proof really uses.

This produces held-out retrieval ground truth. It reads cards only for evaluation; `build_index.py`
never sees them. Gold premises come from the elaborated proof term, not from matching statements.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

TAIL = (Path(__file__).parent / "premise_tail.lean.txt").read_text(encoding="utf-8")
_CARD_MARKER = re.compile(r"^-- manifest card: (\S+)\s*$", re.MULTILINE)
_EXAMPLE = re.compile(r"^example\b", re.MULTILINE)
_THEOREM = r"^theorem {name}\b"


def bundle_source(text: str) -> tuple[str, dict[str, str]]:
    """Name each `example` after its manifest card so Lean keeps it in the environment."""
    marks = list(_CARD_MARKER.finditer(text))
    if not marks:
        return text, {}
    parts = [text[: marks[0].start()]]
    names: dict[str, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        segment = text[mark.start() : end]
        lean_name = f"pals_eval_{index}"
        renamed, replaced = _EXAMPLE.subn(f"theorem {lean_name}", segment, count=1)
        if replaced:
            names[lean_name] = mark.group(1)
        parts.append(renamed)
    return "".join(parts), names


def run_lean(
    source: str, *, lean: str, env: dict[str, str], timeout: float
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Bundle.lean"
        path.write_text(source + "\n" + TAIL, encoding="utf-8")
        try:
            output = subprocess.run(
                [lean, str(path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            ).stdout
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else ""
    return [
        json.loads(line.removeprefix("PALS_PREMISES "))
        for line in output.splitlines()
        if line.startswith("PALS_PREMISES ")
    ]


def catalog_bundles(inventory: Path, repo_root: Path) -> list[dict[str, Any]]:
    data = json.loads(inventory.read_text(encoding="utf-8"))
    cards_by_id = {card["id"]: card for card in data["cards"]}
    jobs: list[dict[str, Any]] = []
    for bundle in data["bundles"]:
        source, names = bundle_source((repo_root / bundle["witness_path"]).read_text("utf-8"))
        jobs.append(
            {
                "id": bundle["id"],
                "source": source,
                "cards": {
                    lean_name: {
                        "card_id": card_id,
                        "source_set": "catalog",
                        "statement_en": cards_by_id[card_id]["canonical_statement"],
                        "statement_ja": None,
                        "lean_target": cards_by_id[card_id]["lean_target"],
                        "witness": cards_by_id[card_id]["lean_witness"],
                    }
                    for lean_name, card_id in names.items()
                    if card_id in cards_by_id
                },
            }
        )
    return jobs


def requested_jobs(corpus: Path) -> list[dict[str, Any]]:
    data = json.loads(corpus.read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = []
    for case in data["cases"]:
        text = (corpus.parent / case["source_path"]).read_text(encoding="utf-8")
        lean_name = "pals_eval_0"
        source = re.sub(
            _THEOREM.format(name=re.escape(case["theorem_name"])),
            f"theorem {lean_name}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        declaration = source[source.index(f"theorem {lean_name}") :]
        statement, _, proof = declaration.partition(":= by")
        jobs.append(
            {
                "id": case["id"],
                "source": source,
                "cards": {
                    lean_name: {
                        "card_id": case["id"],
                        "source_set": "requested",
                        "statement_en": None,
                        "statement_ja": case["question"],
                        "lean_target": statement.strip(),
                        "witness": proof.strip(),
                    }
                },
            }
        )
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--requested-corpus", type=Path, required=True)
    parser.add_argument("--lean", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    env = dict(os.environ)
    jobs = catalog_bundles(args.inventory, args.repo_root) + requested_jobs(args.requested_corpus)

    def run(job: dict[str, Any]) -> list[dict[str, Any]]:
        results = run_lean(job["source"], lean=args.lean, env=env, timeout=args.timeout)
        merged = []
        for result in results:
            card = job["cards"].get(result["name"])
            if card is not None:
                merged.append({**card, **result, "bundle": job["id"]})
        print(f"{job['id']}: {len(merged)}/{len(job['cards'])}", flush=True)
        return merged

    with ThreadPoolExecutor(args.workers) as pool:
        records = [record for batch in pool.map(run, jobs) for record in batch]
    with args.out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"records: {len(records)}")


if __name__ == "__main__":
    main()
