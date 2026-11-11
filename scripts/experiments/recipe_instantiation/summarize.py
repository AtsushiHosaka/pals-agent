#!/usr/bin/env python3
"""Summarise results/*.jsonl into the tables used by the Japanese result document."""
import json, sys, collections, statistics, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from statements import S
res = Path(sys.argv[1])
KINDS = {s["id"]: s["kind"] for s in S}
TYPES = {"Continuous", "Differentiable", "StrictMono", "ContinuousAt", "UniformContinuous", "Monotone"}
SHORT = re.compile(r"^(continuous|Continuous\.|differentiable|Differentiable\.|strictMono|StrictMono\.|pow_lt_pow|Odd\.|hasDerivAt|HasDerivAt|ContinuousAt\.|continuousAt|uniformContinuous|UniformContinuous\.|fun_prop|Real\.continuous|Real\.differentiable)")
GLUE = {"Continuous.continuousAt"}
def recipe_used(u): return any(c.startswith(("power_continuous", "square_continuous", "linear_", "affine_", "recipe_", "odd_power", "power_differentiable")) for c in u)
def shortcuts(u): return sorted(c for c in u if c not in TYPES and c not in GLUE and SHORT.match(c))
def load(f):
    p = res / f
    return [json.loads(l) for l in p.open()] if p.exists() else []
imp = load("import.jsonl"); app = load("append.jsonl"); rer = load("import_rerun.jsonl")
CL = ["i", "ii", "iib", "iii", "iv", "v"]
def cell(r):
    if r is None: return "-"
    if not r["passed"]: return "×"
    sc = shortcuts(r["used"]); g = recipe_used(r["used"])
    if sc and not g: return "S"      # shortcut only
    if sc: return "G+S"
    return "G"                      # Recipe used, no shortcut
by = collections.defaultdict(dict)
for r in imp: by[r["id"]][r["closer"]] = r
print("| id | 種別 | " + " | ".join(CL) + " |\n|---|---|" + "---|" * len(CL))
for s in S:
    d = by[s["id"]]
    print(f"| {s['id']} | {s['kind']} | " + " | ".join(cell(d.get(c)) for c in CL) + " |")
print()
# counts
pos = [s["id"] for s in S if s["kind"] != "neg"]
fail_i = [i for i in pos if not by[i]["i"]["passed"]]
print("positives", len(pos), "(i) pass", len(pos) - len(fail_i), "(i) fail", len(fail_i))
for c in CL[1:]:
    rescued = [i for i in fail_i if c in by[i] and by[i][c]["passed"]]
    clean = [i for i in rescued if recipe_used(by[i][c]["used"]) and not shortcuts(by[i][c]["used"])]
    sc = [i for i in rescued if i not in clean]
    allp = [i for i in pos if c in by[i] and by[i][c]["passed"]]
    print(c, "rescued", len(rescued), "clean(G, no shortcut)", len(clean), "shortcut/no-G", len(sc), sc, "| total passes among positives", len(allp))
anyclean = [i for i in fail_i if any(c in by[i] and by[i][c]["passed"] and recipe_used(by[i][c]["used"]) and not shortcuts(by[i][c]["used"]) for c in CL[1:])]
print("union clean rescue", len(anyclean), "still failing", sorted(set(fail_i) - set(anyclean)))
neg = [r for r in imp if KINDS[r["id"]] == "neg" and r["passed"]]
print("negatives passed:", [(r["id"], r["closer"], recipe_used(r["used"]), shortcuts(r["used"])) for r in neg])
# timing
def med(xs): return round(statistics.median(xs), 1) if xs else None
for name, rows in (("import(main)", imp), ("append", app), ("import(rerun)", rer)):
    for c in CL:
        t = [r["wall"] for r in rows if r["closer"] == c]
        if t: print(name, c, "n", len(t), "median", med(t), "min", min(t), "max", max(t))
common = {(r["id"], r["closer"]) for r in app}
def pair(a, b):
    A = {(r["id"], r["closer"]): r for r in a}; B = {(r["id"], r["closer"]): r for r in b}
    return A, B
A, B = pair(imp, app); Rr = {(r["id"], r["closer"]): r for r in rer}
print("pairs same-statement same-closer: key import(main) / import(rerun) / append")
for c in ["i", "iii", "iv"]:
    ks = [k for k in B if k[1] == c and k in A and k in Rr]
    if ks:
        print(c, "n", len(ks), "import main", med([A[k]["wall"] for k in ks]), "rerun", med([Rr[k]["wall"] for k in ks]), "append", med([B[k]["wall"] for k in ks]))
# agreement of verdicts between forms
dis = [(k, A[k]["passed"], B[k]["passed"]) for k in B if k in A and A[k]["passed"] != B[k]["passed"]]
print("verdict disagreements import vs append:", dis)
