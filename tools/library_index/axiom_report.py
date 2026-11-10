"""Print the axioms of every non-internal theorem of the compiled Archive/Counterexamples modules.

    python -m tools.library_index.axiom_report --compile compile.json --package DIR \
        --workspace-packages DIR --toolchain-bin DIR --scratch DIR --out axioms.json

One ``lean`` process imports every module that compiled in ``compile_inventory`` (their ``.olean``
files are in ``--scratch``), walks the environment, and runs ``Lean.collectAxioms`` per theorem.
Nothing is written to the shared workspace. ``sorryAx`` in a list means the theorem is not proved.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

LEAN_TEMPLATE = """\
{imports}
open Lean

#eval show CoreM Unit from do
  let env ← getEnv
  let roots : List String := ["Archive", "Counterexamples"]
  let mut total := 0
  let mut internal := 0
  let mut found : Array (Name × Name) := #[]
  for (n, i) in env.constants.map₁.toList do
    if !i.isTheorem then continue
    match env.getModuleIdxFor? n with
    | some idx =>
      let m := env.header.moduleNames[idx.toNat]!
      if roots.contains m.getRoot.toString then
        total := total + 1
        if n.isInternalDetail then internal := internal + 1 else found := found.push (n, m)
    | none => pure ()
  IO.println s!"COUNT\\t{{total}}\\t{{internal}}"
  for (n, m) in found do
    let axs ← collectAxioms n
    IO.println s!"AXIOMS\\t{{m}}\\t{{n}}\\t{{String.intercalate "," (axs.toList.map toString)}}"
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--compile", type=Path, required=True)
    parser.add_argument("--workspace-packages", type=Path, required=True)
    parser.add_argument("--toolchain-bin", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    modules = [c["module"] for c in json.loads(args.compile.read_text()) if c["status"] == "ok"]
    source = LEAN_TEMPLATE.format(imports="\n".join(f"import {m}" for m in modules))
    script = args.scratch / "AxiomReport.lean"
    script.write_text(source)
    libs = [
        str(p / ".lake" / "build" / "lib" / "lean")
        for p in sorted(args.workspace_packages.iterdir()) if (p / ".lake").is_dir()
    ]
    env = {**os.environ, "LEAN_PATH": os.pathsep.join([*libs, str(args.scratch / "lib")])}
    started = time.perf_counter()
    done = subprocess.run(
        ["/usr/bin/time", "-l", "nice", "-n", "10", str(args.toolchain_bin / "lean"), str(script)],
        capture_output=True, text=True, env=env, cwd=args.scratch, timeout=3600,
    )
    wall = time.perf_counter() - started
    rows = []
    count = None
    for line in done.stdout.splitlines():
        parts = line.split("\t")
        if parts[0] == "AXIOMS" and len(parts) == 4:
            rows.append({"module": parts[1], "name": parts[2],
                         "axioms": [a for a in parts[3].split(",") if a]})
        elif parts[0] == "COUNT" and len(parts) == 3:
            count = {"theorems_total": int(parts[1]), "internal_aux": int(parts[2])}
    rss = re.search(r"(\d+)\s+maximum resident set size", done.stderr)
    args.out.write_text(json.dumps({
        "exit_code": done.returncode, "wall_s": round(wall, 1), "counts": count,
        "max_rss_bytes": int(rss.group(1)) if rss else None,
        "stdout_head": done.stdout[:600] if not rows else "", "stderr_head": done.stderr[:600],
        "rows": rows,
    }, indent=1))
    print(f"exit {done.returncode}, {len(rows)} theorems, {wall:.1f}s")


if __name__ == "__main__":
    main()
