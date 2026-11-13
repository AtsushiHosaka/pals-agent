# ruff: noqa: E501, E702, E731, B023, SIM108, SIM115, F841
"""Aggregate run_fixed_qa.py outputs: python summarize_fixed_qa.py arm=file.json ..."""
import collections
import json
import sys

print("arm | valid approved | valid rejected (false rejections) | negatives rejected | negatives approved (missed) | by defect: rejected/total")
for spec in sys.argv[1:]:
    arm, path = spec.split("=", 1)
    res = json.load(open(path))["results"]
    v = [r for r in res if r["expected"] == "approve"]
    n = [r for r in res if r["expected"] == "reject"]
    per = collections.defaultdict(lambda: [0, 0])
    for r in n:
        k = r["case"].split("/")[1]
        per[k][1] += 1
        per[k][0] += r["verdict"] in ("reject", "invalid_before_qa")
    print(arm, sum(r["verdict"] == "approve" for r in v), sum(r["verdict"] != "approve" for r in v), sum(r["verdict"] in ("reject", "invalid_before_qa") for r in n),
          sum(r["verdict"] == "approve" for r in n), {k: f"{a}/{b}" for k, (a, b) in sorted(per.items())}, f"(valid n={len(v)}, negative n={len(n)})")
