#!/usr/bin/env python3
"""Recipe-instantiation experiment runner (real Lean, no model calls, one Lean process at a time).

usage: run.py build-lib | run --form import|append [--only IDS] [--closers i,ii,iib,iii,iv] --out FILE.jsonl
Env: LEAN (pinned 4.32.0-rc1 binary), LEAN_PATH (Mathlib etc. + LIBDIR).
"""
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
TD = HERE.parents[2] / "testdata"
sys.path.insert(0, str(HERE))
from statements import S

LEAN = os.environ.get("LEAN", "lean")
LIBDIR = Path(os.environ.get("PALS_EXP_LIB", "/private/tmp/claude-501/exp/lib"))

# key -> (lean name, testdata proof path or local extra, n_vars, n_hyps)
R = {
 "pow_c": ("power_continuous_explicit_epsilon_delta", TD/"power-continuity-recipe-v1/proofs/power_continuous_explicit_epsilon_delta.lean", 1, 0),
 "sq_c": ("square_continuous_explicit_epsilon_delta", TD/"square-continuity-recipe-v1/proofs/square_continuous_explicit_epsilon_delta.lean", 0, 0),
 "lin_c": ("linear_continuous_explicit_epsilon_delta", TD/"linear-continuity-recipe-v1/proofs/linear_continuous_explicit_epsilon_delta.lean", 1, 0),
 "aff_c": ("affine_continuous_explicit_epsilon_delta", TD/"affine-continuity-recipe-v1/proofs/affine_continuous_explicit_epsilon_delta.lean", 2, 0),
 "add_c": ("recipe_add_continuous_epsilon_delta", HERE/"extra_add_continuous.lean", 2, 2),
 "cmul_c": ("recipe_const_mul_continuous_epsilon_delta", HERE/"extra_const_mul_continuous.lean", 2, 1),
 "odd_m": ("odd_power_strictly_increasing_sign_cases", TD/"odd-power-strict-mono-recipe-v1/proofs/odd_power_strictly_increasing_sign_cases.lean", 1, 0),
 "pow_d": ("power_differentiable_induction_product_rule", TD/"power-differentiability-recipe-v1/proofs/power_differentiable_induction_product_rule.lean", 1, 0),
 "lin_d": ("linear_differentiable_difference_quotient", TD/"linear-differentiability-recipe-v1/proofs/linear_differentiable_difference_quotient.lean", 1, 0),
 "aff_d": ("affine_differentiable_difference_quotient", TD/"affine-differentiability-recipe-v1/proofs/affine_differentiable_difference_quotient.lean", 2, 0),
}
POOLS = {
 "cont": ["pow_c", "lin_c", "aff_c", "add_c", "cmul_c"],
 "mono": ["odd_m", "pow_c", "lin_c", "aff_c", "add_c"],
 "diff": ["pow_d", "lin_d", "aff_d", "odd_m", "pow_c"],
}
GLUE = "Continuous.continuousAt"

def src(key):
    t = R[key][1].read_text()
    return "\n".join(l for l in t.splitlines() if l.strip() != "import Mathlib").strip() + "\n"

def args_i(key):
    _, _, nv, nh = R[key]
    return " ".join(["_"] * nv + ["(by norm_num)"] * nh)

USED = r'''
open Lean Meta in
#eval show MetaM Unit from do
  let env ← getEnv
  let mut seen : NameSet := {}
  let mut todo : List Name := [`pals_recipe_instance]
  let mut out : NameSet := {}
  while !todo.isEmpty do
    match todo with
    | [] => pure ()
    | n :: rest =>
      todo := rest
      if seen.contains n then continue
      seen := seen.insert n
      match env.find? n with
      | some ci =>
        if let some v := (match ci with | .thmInfo t => some t.value | .defnInfo d => some d.value | _ => none) then
          for c in v.getUsedConstants do
            if (`pals_recipe_instance).isPrefixOf c then todo := c :: todo else out := out.insert c
      | none => pure ()
  IO.println ("USED: " ++ " ".join (out.toList.map toString))
#print axioms pals_recipe_instance
'''.replace('" ".join', '" ".intercalate')

def closer(s, c):
    G = s["G"]; g = R[G][0]; pool = POOLS[s["pool"]]
    if G not in pool and c in ("iii", "iv"): pool = pool + [G]
    a = args_i(G)
    if c == "i":
        return f"exact {g} {a}"
    if c == "ii":
        return f"first | simpa using {g} {a} | (convert {g} {a} using 2 <;> norm_num)"
    if c == "iib":
        if s["bind"] is None: return None
        b = s["bind"]
        if R[G][3]: b = a  # hypothesis recipes: no hand binding
        return f"first | exact {g} {b} | simpa using {g} {b} | (convert {g} {b} using 2 <;> norm_num)"
    if c == "v":  # extension beyond the task list: bound args + funext/ring for the residual function equality
        if s["bind"] is None or R[G][3]: return None
        b = s["bind"]
        return f"first | exact {g} {b} | (convert {g} {b} using 1; funext x; ring)"
    if c == "iii":
        return "first | " + " | ".join(f"exact {R[k][0]} {args_i(k)}" for k in pool)
    if c == "iv":
        names = ", ".join([R[k][0] for k in pool] + [GLUE])
        plain = ", ".join(R[k][0] for k in pool)
        return f"first | (apply_rules [{names}]) | (aesop (add safe apply [{plain}]))"
    raise ValueError(c)

def recipes_needed(s, c):
    G = s["G"]
    if c in ("iii", "iv"):
        keys = list(POOLS[s["pool"]]); 
        if G not in keys: keys.append(G)
        return keys
    return [G]

def build(s, c, form):
    cl = closer(s, c)
    if cl is None: return None
    head = "import Mathlib\n"
    if form == "import":
        head += "import PalsRecipes\n"
        body = ""
    else:
        body = "\n".join(src(k) for k in recipes_needed(s, c))
    return head + body + f"\ntheorem pals_recipe_instance : {s['stmt']} := by\n  {cl}\n" + USED

def run_lean(text, name, timeout=240):
    d = Path(os.environ.get("PALS_EXP_WORK", "/private/tmp/claude-501/exp/work")); d.mkdir(parents=True, exist_ok=True)
    f = d / f"{name}.lean"; f.write_text(text)
    env = dict(os.environ); lp = env.get("LEAN_PATH", "")
    env["LEAN_PATH"] = f"{LIBDIR}:{lp}" if lp else str(LIBDIR)
    t = time.time()
    try:
        p = subprocess.run([LEAN, str(f)], capture_output=True, text=True, timeout=timeout, env=env, cwd=d)
        out = p.stdout + p.stderr; rc = p.returncode; to = False
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")); rc = -1; to = True
    return out, rc, to, time.time() - t

OK_AX = {"propext", "Classical.choice", "Quot.sound"}
def parse(out, rc, to):
    errs = [l for l in out.splitlines() if re.search(r"error", l)]
    m = re.search(r"^USED: ?(.*)$", out, re.M)
    used = m.group(1).split() if m else []
    ax = re.search(r"depends on axioms: \[(.*?)\]", out, re.S)
    axs = [a.strip() for a in ax.group(1).split(",")] if ax else None
    sorry = "sorry" in out
    passed = (not to) and rc == 0 and not errs and axs is not None and set(axs) <= OK_AX and not sorry
    return dict(passed=passed, first_error=(errs[0][:300] if errs else ("timeout" if to else None)),
                axioms=axs, used=used, timeout=to)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("--form", default="import")
    ap.add_argument("--only"); ap.add_argument("--closers", default="i,ii,iib,iii,iv"); ap.add_argument("--out")
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    if a.cmd == "build-lib":
        LIBDIR.mkdir(parents=True, exist_ok=True)
        text = "import Mathlib\n\n" + "\n".join(src(k) for k in R)
        (LIBDIR / "PalsRecipes.lean").write_text(text)
        env = dict(os.environ)
        t = time.time()
        p = subprocess.run([LEAN, "-o", str(LIBDIR / "PalsRecipes.olean"), str(LIBDIR / "PalsRecipes.lean")], capture_output=True, text=True, env=env, cwd=LIBDIR)
        print(p.returncode, round(time.time() - t, 1), p.stdout[-2000:], p.stderr[-2000:])
        return
    only = set(a.only.split(",")) if a.only else None
    with open(a.out, "a") as fo:
        for s in S:
            if only and s["id"] not in only: continue
            for c in a.closers.split(","):
                text = build(s, c, a.form)
                if text is None: continue
                out, rc, to, dt = run_lean(text, f"{s['id']}_{c}_{a.form}")
                r = parse(out, rc, to)
                r.update(id=s["id"], kind=s["kind"], closer=c, form=a.form, wall=round(dt, 2), tag=a.tag)
                fo.write(json.dumps(r, ensure_ascii=False) + "\n"); fo.flush()
                print(s["id"], c, a.form, "PASS" if r["passed"] else "fail", r["wall"], flush=True)
main()
