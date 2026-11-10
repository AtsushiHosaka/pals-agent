"""Build testdata/generation-eval-v1/manifest.json from repository records.

Deterministic (fixed salt, no randomness beyond sha256 ordering) and read-only on the sources.
Sources live in the parent repository (docs/*.json, docs/first-sketch-failures-2026-11-08/data,
pals-agent/testdata/requested-math-seeds-v1). The manifest embeds the statement text so the eval
needs no parent checkout. Rebuilding with different inputs changes the split checksum: bump the
version instead of overwriting a published manifest.

    python3 scripts/eval/build_manifest.py --parent ../ --out testdata/generation-eval-v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pals_agent.evals.manifest import (  # noqa: E402
    BANNED_PATTERNS,
    SPLIT_SALT,
    assign_splits,
    derive_tags,
    detect_language,
    split_checksum,
)

CANDIDATE_QUOTAS = {
    # field -> (source files, domains, quota)
    "school-algebra": (
        [
            "highschool-polynomial-rational-candidates",
            "highschool-polynomial-rational-expansion-candidates",
        ],
        None,
        5,
    ),
    "trigonometry": (["highschool-trigonometry-expansion-candidates"], None, 2),
    "exp-log": (
        ["highschool-exponent-log-expansion-candidates", "exponent-log-number-theory-candidates"],
        {"exponentials_and_logarithms", "high_school_real_exponentials_and_logarithms"},
        2,
    ),
    "sequences-limits": (["highschool-sequences-limits-calculus-candidates"], None, 2),
    "coordinate-geometry": (
        ["highschool-coordinate-conics-candidates", "coordinate-geometry-candidates"],
        None,
        2,
    ),
    "number-theory": (
        [
            "typed-number-theory-v1-authoring-manifest.proposal",
            "exponent-log-number-theory-candidates",
        ],
        {None, "elementary_number_theory"},
        3,
    ),
    "discrete-logic": (
        [
            "discrete-relations-maps-combinatorics-candidates",
            "logic-proof-methods-set-foundations-candidates",
        ],
        None,
        4,
    ),
    "probability-ode": (
        [
            "typed-ode-v1-authoring-manifest.proposal",
            "typed-probability-v1-authoring-manifest.proposal",
        ],
        None,
        2,
    ),
}
DIFF_TIER = {
    "introductory": "easy",
    "standard": "medium",
    "intermediate": "medium",
    "advanced": "hard",
    "undergraduate_year_2": "hard",
}

# Hand-assigned tiers for the 20 Japanese seed questions (no recorded history): arithmetic or one
# standard lemma -> easy; one real argument -> medium; needs an external bound or a structure
# theorem -> hard. Basis is recorded as "assigned" so analyses can exclude them.
SEED_TIER = {
    "cubic_derivative": "easy",
    "determinant_nonzero_decision": "easy",
    "linear_system_unique_solution": "easy",
    "linear_system_inconsistent": "easy",
    "quadratic_not_injective": "easy",
    "projection_not_injective": "easy",
    "reciprocal_derivative": "easy",
    "sum_derivative": "easy",
    "natural_power_continuous": "easy",
    "absolute_value_not_differentiable": "easy",
    "exponential_product_derivative": "medium",
    "rational_power_continuous": "medium",
    "linear_injective_iff_zero_kernel": "medium",
    "composite_injective_implies_first": "medium",
    "product_determinant_nonzero_iff": "medium",
    "right_limit_and_discontinuity": "medium",
    "continuous_endpoint_sign_change_has_root": "medium",
    "pi_gt_305": "hard",
    "tan_one_degree_irrational": "hard",
    "rank_nullity": "hard",
}
SEED_FIELD = {
    "cubic_derivative": "calculus-analysis",
    "natural_power_continuous": "calculus-analysis",
    "rational_power_continuous": "calculus-analysis",
    "exponential_product_derivative": "calculus-analysis",
    "reciprocal_derivative": "calculus-analysis",
    "absolute_value_not_differentiable": "calculus-analysis",
    "sum_derivative": "calculus-analysis",
    "right_limit_and_discontinuity": "calculus-analysis",
    "continuous_endpoint_sign_change_has_root": "calculus-analysis",
    "pi_gt_305": "calculus-analysis",
    "tan_one_degree_irrational": "calculus-analysis",
    "linear_injective_iff_zero_kernel": "linear-algebra",
    "linear_system_unique_solution": "linear-algebra",
    "linear_system_inconsistent": "linear-algebra",
    "determinant_nonzero_decision": "linear-algebra",
    "product_determinant_nonzero_iff": "linear-algebra",
    "rank_nullity": "linear-algebra",
    "quadratic_not_injective": "discrete-logic",
    "projection_not_injective": "discrete-logic",
    "composite_injective_implies_first": "discrete-logic",
}
CODEX_FIELD = [
    ("real_analysis", "calculus-analysis"),
    ("real-analysis", "calculus-analysis"),
    ("number", "number-theory"),
    ("induction", "discrete-logic"),
    ("algebra-cancellation", "school-algebra"),
    ("linear_algebra", "linear-algebra"),
    ("group_theory", "abstract-algebra"),
    ("ring_theory", "abstract-algebra"),
    ("topology", "topology"),
]
CODEX_TIER = {  # the registry has no difficulty column; assigned from the proof's structure
    "real-square-continuity": "easy",
    "absolute-value-nondifferentiability": "easy",
    "sum-of-first-n-integers": "easy",
    "square-root-of-square-false-claim": "easy",
    "cancellation-zero-coefficient": "easy",
    "irrational-square-root-two": "medium",
    "real-sequence-limit-uniqueness": "medium",
    "positive-derivative-injectivity": "medium",
    "prime-above-every-bound": "medium",
    "continuous-interval-self-map-fixed-point": "medium",
    "idempotent-linear-map-unique-decomposition": "medium",
    "index-two-subgroup-normality": "medium",
    "bounded-monotone-real-sequence-convergence": "hard",
    "distinct-eigenvalues-linear-independence": "medium",
    "prime-order-group-nonidentity-generator": "medium",
    "coprime-moduli-unique-residue-solution": "hard",
    "compact-hausdorff-continuous-bijection-inverse": "hard",
    "finite-integral-domain-unique-inverse": "hard",
}


def h(text: str) -> str:
    return hashlib.sha256(f"{SPLIT_SALT}:{text}".encode()).hexdigest()


def banned(text: str, pid: str) -> bool:
    return any(p.search(text) for p in BANNED_PATTERNS) or bool(
        re.search(r"binomial_square|square_binomial", pid)
    )


def load_cards(docs: Path, stem: str) -> list[dict]:
    return json.loads((docs / f"{stem}.json").read_text(encoding="utf-8"))["cards"]


def observed_history(data_dir: Path) -> dict[str, dict]:
    hist: dict[str, dict] = defaultdict(
        lambda: {"runs": 0, "failed": 0, "max_repairs": 0, "mismatch": False}
    )
    for path in sorted(data_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            pid = row.get("problem")
            if not pid or "state" not in row or "repairs_used" not in row:
                continue
            e = hist[pid]
            e["runs"] += 1
            e["failed"] += row["state"] != "verified"
            e["max_repairs"] = max(e["max_repairs"], row.get("repairs_used") or 0)
            codes = {c for step in row.get("diagnostic_codes") or [] for c in step}
            e["mismatch"] |= any("mismatch" in c for c in codes)
    return hist


def tier_from_history(e: dict) -> str:
    if e["failed"] or e["max_repairs"] >= 3:
        return "hard"
    return "medium" if e["max_repairs"] >= 1 else "easy"


def typed_field(pid: str) -> str:
    if pid.startswith(("mv_", "mv-")):
        return "multivariable"
    if pid.startswith("la_"):
        return "linear-algebra"
    if pid.startswith("commalg"):
        return "commutative-algebra"
    return "calculus-analysis"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    docs = args.parent / "docs"
    problems: dict[str, dict] = {}

    def add(**p) -> None:
        if p["id"] in problems or banned(p["statement"], p["id"]):
            return
        p.setdefault("language", detect_language(p["statement"]))
        p["tags"] = derive_tags(p["statement"], p.get("tags_extra", []))
        p.pop("tags_extra", None)
        problems[p["id"]] = p

    # 1. Typed catalog cards with recorded runs (36): statement text used only as a question.
    hist = observed_history(docs / "first-sketch-failures-2026-11-08" / "data")
    cards = {}
    for path in sorted(docs.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("cards"), list):
            for c in data["cards"]:
                if isinstance(c, dict) and "canonical_statement" in c:
                    cards.setdefault(c["id"], c)
    for pid in sorted(hist):
        c = cards.get(pid)
        if c is None:
            continue
        e = hist[pid]
        history = (
            ["observed"]
            + (["exhausted-repairs"] if e["failed"] else [])
            + (["statement-mismatch"] if e["mismatch"] else [])
        )
        add(
            id=pid,
            source="catalog-typed-observed",
            field=typed_field(pid),
            tier=tier_from_history(e),
            tier_basis="observed",
            language="en",
            statement=c["canonical_statement"],
            fixed_lean_statement=c.get("lean_target"),
            expected_answer=None,
            history=history,
            has_catalog_witness=bool(c.get("lean_witness")),
        )

    # 2. Japanese requested seeds (20), with expected answers for decision/computation items.
    corpus = json.loads(
        (args.parent / "pals-agent/testdata/requested-math-seeds-v1/corpus.json").read_text(
            encoding="utf-8"
        )
    )
    for case in corpus["cases"]:
        key = case["id"].split(".", 1)[1]
        decision = bool(re.search(r"判定|求め|解け|か。", case["question"]))
        add(
            id=f"seed-{key}",
            source="requested-math-seeds-v1",
            field=SEED_FIELD[key],
            tier=SEED_TIER[key],
            tier_basis="assigned",
            statement=case["question"],
            fixed_lean_statement=None,
            expected_answer=case["answer"] if decision else None,
            history=[],
            has_catalog_witness=True,
            tags_extra=["computation"] if decision else [],
        )

    # 3. Codex prompt-quality problems with Lean required (shared ids).
    shared = json.loads((args.out / "codex_shared_problems.json").read_text(encoding="utf-8"))[
        "problems"
    ]
    for s in shared:
        if str(s["requires_lean"]).lower() != "true":
            continue
        field = next(v for k, v in CODEX_FIELD if k in s["topic_group"])
        add(
            id=f"pq-{s['id']}",
            source="prompt-quality-registry",
            field=field,
            tier=CODEX_TIER[s["id"]],
            tier_basis="assigned",
            language="ja",
            statement=s["statement"],
            fixed_lean_statement=None,
            expected_answer=None,
            history=[],
            has_catalog_witness=False,
            shared={
                "prompt_quality_id": s["id"],
                "case_id": s["case_id"],
                "fixture_sha256": s["fixture_sha256"],
            },
        )

    # 4. Scheme-theory M cards (fixed Lean statement, Mathlib only), first measured outcomes.
    scheme = json.loads(
        (docs / "scheme-theory-measurement-cards-2026-11-09.json").read_text(encoding="utf-8")
    )["cards"]
    arm_a = {}
    for line in (
        (docs / "scheme-theory-measurement-rows-arm-a-2026-11-09.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        row = json.loads(line)
        arm_a[row["id"]] = row
    m_cards = sorted(
        (c for c in scheme if c["id"].startswith("M") and c["id"] in arm_a),
        key=lambda c: h(c["id"]),
    )[:6]
    for c in m_cards:
        row = arm_a[c["id"]]
        failed = row.get("state") != "verified"
        add(
            id=f"scheme-{c['id']}",
            source="scheme-theory-measurement-cards",
            field="algebraic-geometry",
            tier="hard" if failed or (row.get("repairs_used") or 0) >= 3 else "medium",
            tier_basis="observed",
            language="en",
            statement=c["nl"],
            fixed_lean_statement=c["formal"],
            expected_answer=None,
            history=["observed"] + (["exhausted-repairs"] if failed else []),
            has_catalog_witness=False,
        )

    # 5. Declared-difficulty candidate cards (statement text only; no Lean witness exists).
    taken_stmt: set[str] = set()
    for field, (stems, domains, quota) in CANDIDATE_QUOTAS.items():
        pool = []
        for stem in stems:
            for c in load_cards(docs, stem):
                if domains is not None and c.get("domain") not in domains:
                    continue
                st = c["canonical_statement"]
                if c["id"] in problems or st in taken_stmt or banned(st, c["id"]):
                    continue
                pool.append((stem, c))
        by_tier: dict[str, list] = defaultdict(list)
        for stem, c in pool:
            tier = DIFF_TIER.get(c.get("difficulty") or "", "medium")
            by_tier[tier].append((stem, c))
        for t in by_tier.values():
            t.sort(key=lambda sc: h(sc[1]["id"]))
        order = ["medium", "hard", "easy"]
        picked: list[tuple[str, dict]] = []
        while len(picked) < quota and any(by_tier[t] for t in order):
            for t in order:
                if by_tier[t] and len(picked) < quota:
                    picked.append(by_tier[t].pop(0))
        for stem, c in picked:
            taken_stmt.add(c["canonical_statement"])
            add(
                id=c["id"],
                source=f"candidate:{stem}",
                field=field,
                tier=DIFF_TIER.get(c.get("difficulty") or "", "medium"),
                tier_basis="declared" if c.get("difficulty") else "assigned",
                statement=c["canonical_statement"],
                fixed_lean_statement=None,
                expected_answer=None,
                history=[],
                has_catalog_witness=False,
            )

    items = sorted(problems.values(), key=lambda p: p["id"])
    assign_splits(items)
    for p in items:
        p["statement_sha256"] = hashlib.sha256(p["statement"].encode()).hexdigest()
        p.setdefault("shared", None)
    manifest = {
        "schema_version": "pals.generation-eval-manifest.v1",
        "version": "generation-eval-v1",
        "split_salt": SPLIT_SALT,
        "split_checksum": split_checksum(items),
        "problems": items,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "SPLIT.sha256").write_text(manifest["split_checksum"] + "\n", encoding="utf-8")
    print(f"{len(items)} problems; split checksum {manifest['split_checksum']}")


if __name__ == "__main__":
    main()
