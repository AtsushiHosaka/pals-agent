# ruff: noqa: E501, E702, E731, B023, SIM108, SIM115, F841
"""Aggregate run_e2e.py outputs: python summarize_e2e.py a.json b.json ... [--detail]"""
import collections
import json
import sys

files = [f for f in sys.argv[1:] if not f.startswith("--")]
allrows = [r for f in files for r in json.load(open(f))]
# transport/provider errors (network outage) are not measurements of the code under test
rows = [r for r in allrows if r["outcome"] not in ("error", "review_transport")]
print("excluded provider/transport errors:", len(allrows) - len(rows))
by = collections.defaultdict(list)
for r in rows:
    by[r["arm"]].append(r)
print("arm | trials | answered | terminal QA-reject | generation_failed | trials with >=1 QA rejection | QA rejections | answer in conclusion (of answered computation) | usd")
for arm, rs in sorted(by.items()):
    ans = [r for r in rs if r["outcome"] == "approved"]
    comp = [r for r in ans if r["id"] in ("dual_power", "dual_sum", "roots_quadratic", "det_nonzero", "cubic_derivative")]
    print(arm, len(rs), len(ans), sum(r["outcome"] == "review_rejected" for r in rs), sum(r["outcome"] == "generation_failed" for r in rs),
          sum(r["qa_rejections"] > 0 for r in rs), sum(r["qa_rejections"] for r in rs),
          f'{sum(bool(r["conclusion_answer"]) for r in comp)}/{len(comp)}', round(sum(r["est_usd"] for r in rs), 3))
if "--detail" in sys.argv:
    for r in rows:
        if r["qa_rejections"] or r["outcome"] != "approved" or (r["id"] in ("dual_power", "dual_sum", "roots_quadratic", "det_nonzero", "cubic_derivative") and not r["conclusion_answer"]):
            print("###", r["id"], r["arm"], r["outcome"], r["qa_rejections"], (r["error"] or "")[:150])
            for q in r["rejection_reasons"]:
                print("   REJ:", q[:260].replace("\n", " "))
            if r["outcome"] == "approved" and not r["conclusion_answer"]:
                print("   CONCL:", (r["final_content"] or {}).get("conclusion"))
