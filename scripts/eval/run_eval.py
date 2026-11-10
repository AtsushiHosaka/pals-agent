"""Generation-eval CLI: schedule, Tier 0 replay, Tier 1 sketch-only, replay-file helper.

Examples (Tier 0 needs no credentials and costs nothing):

    python3 scripts/eval/run_eval.py schedule --arms base,new --repeats 2 --split tuning
    python3 scripts/eval/run_eval.py witness-replay --parent .. \\
        --ids calculus_v3_limit_sum --out replay.jsonl
    python3 scripts/eval/run_eval.py tier0 --replay replay.jsonl --out RUN_DIR --arm base \\
        --lean "$LEAN" --lake "$LAKE" --project "$PROJECT" --elan-home "$ELAN_HOME"

Tier 1 spends model money and needs OPENAI_API_KEY; it refuses to start without ``--max-usd``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pals_agent.evals.manifest import load_manifest, validate_manifest  # noqa: E402
from pals_agent.evals.records import JsonlSink  # noqa: E402
from pals_agent.evals.runner import Scope, interleaved_schedule, run_tier0  # noqa: E402

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "testdata/generation-eval-v1/manifest.json"


def _verifier(args: argparse.Namespace):
    from pals_agent.lean import LeanVerifier

    return LeanVerifier(
        lean_binary=args.lean,
        lake_binary=args.lake,
        project_dir=Path(args.project),
        child_path=f"{Path(args.lean).parent}:/usr/bin:/bin",
        elan_home=args.elan_home,
        scratch_dir=Path(args.scratch or tempfile.mkdtemp(prefix="pals-eval-")),
        timeout_seconds=args.lean_timeout,
    )


def _select(manifest: dict, split: str | None, ids: str | None) -> list[dict]:
    items = manifest["problems"]
    if split in ("tuning", "held_out"):
        items = [p for p in items if p["split"] == split]
    if ids:
        wanted = set(ids.split(","))
        items = [p for p in items if p["id"] in wanted]
    return items


def cmd_schedule(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    if args.split == "held_out" and not args.open_held_out:
        sys.exit(
            "held_out is opened only for final comparisons: pass --open-held-out and record why"
        )
    ids = [p["id"] for p in _select(manifest, args.split, args.ids)]
    for pid, arm, rep in interleaved_schedule(ids, args.arms.split(","), args.repeats, args.seed):
        print(json.dumps({"problem_id": pid, "arm": arm, "repeat": rep}))


def cmd_witness_replay(args: argparse.Namespace) -> None:
    docs = Path(args.parent) / "docs"
    wanted = set(args.ids.split(","))
    rows = []
    for path in sorted(docs.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for card in data.get("cards", []) if isinstance(data, dict) else []:
            if isinstance(card, dict) and card.get("id") in wanted and card.get("lean_witness"):
                code = f"import Mathlib\n\n{card['lean_target']} :=\n  {card['lean_witness']}\n"
                rows.append(
                    {"problem_id": card["id"], "lean_code": code, "source": "catalog_witness"}
                )
                wanted.discard(card["id"])
    Path(args.out).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"wrote {len(rows)} replays; missing: {sorted(wanted)}")


def cmd_tier0(args: argparse.Namespace) -> None:
    out = Path(args.out)
    sink = JsonlSink(out / "records.jsonl", artifacts_dir=out / "artifacts")
    scope = Scope(run_id=args.run_id or out.name, sink=sink)
    replays = [
        json.loads(line)
        for line in Path(args.replay).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = load_manifest(args.manifest)
    splits = {p["id"]: p["split"] for p in manifest["problems"]}
    config = {"lean": Path(args.lean).parent.parent.name, "project": Path(args.project).name}
    rows = run_tier0(
        replays,
        _verifier(args),
        scope,
        arm=args.arm,
        repeat=args.repeat,
        splits=splits,
        config=config,
    )
    for r in rows:
        print(f"{r['problem_id']}: success={r['success']} wall_s={r['wall_s']} error={r['error']}")


def cmd_validate(args: argparse.Namespace) -> None:
    frozen = (Path(args.manifest).parent / "SPLIT.sha256").read_text(encoding="utf-8")
    errors = validate_manifest(load_manifest(args.manifest), frozen)
    print("\n".join(errors) or "manifest valid")
    sys.exit(1 if errors else 0)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("schedule")
    s.add_argument("--arms", required=True)
    s.add_argument("--repeats", type=int, default=2)
    s.add_argument("--split", default="tuning", choices=["tuning", "held_out", "all"])
    s.add_argument("--ids")
    s.add_argument("--seed", type=int, default=20261110)
    s.add_argument("--open-held-out", action="store_true")
    s.set_defaults(fn=cmd_schedule)
    w = sub.add_parser("witness-replay")
    w.add_argument("--parent", required=True)
    w.add_argument("--ids", required=True)
    w.add_argument("--out", required=True)
    w.set_defaults(fn=cmd_witness_replay)
    t = sub.add_parser("tier0")
    t.add_argument("--replay", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--arm", required=True)
    t.add_argument("--run-id")
    t.add_argument("--repeat", type=int, default=1)
    for name in ("lean", "lake", "project", "elan-home"):
        t.add_argument(f"--{name}", required=True)
    t.add_argument("--scratch")
    t.add_argument("--lean-timeout", type=float, default=180.0)
    t.set_defaults(fn=cmd_tier0)
    v = sub.add_parser("validate")
    v.set_defaults(fn=cmd_validate)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
