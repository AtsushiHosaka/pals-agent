"""Generation-eval manifest: schema, deterministic split, frozen checksum, validation.

Pure standard library. The split is a function of (salt, id, field, tier) only, so it can be
recomputed and compared with the checksum committed in ``testdata/generation-eval-v1/SPLIT.sha256``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SPLIT_SALT = "pals-generation-eval-v1"
HELD_OUT_FRACTION = 0.3
TIERS = ("easy", "medium", "hard")
TIER_BASES = ("observed", "declared", "assigned")
SPLITS = ("tuning", "held_out")
LANGUAGES = ("ja", "en")
TAGS = (
    "needs-induction",
    "epsilon-delta",
    "inequality",
    "linear-algebra",
    "counterexample",
    "computation",
    "existence-uniqueness",
    "equivalence",
)
# The squared binomial expansion (x+y)^2 is banned as test material (repository AGENTS.md).
BANNED_PATTERNS = (
    re.compile(r"\(\s*[A-Za-z0-9]+\s*[+\-]\s*[A-Za-z0-9]+\s*\)\s*(?:\^|\*\*)\s*2"),
    re.compile(r"\(\s*[A-Za-z0-9]+\s*[+\-]\s*[A-Za-z0-9]+\s*\)\s*²"),
)
_CJK = re.compile(r"[぀-ヿ一-鿿]")
_TAG_RULES = {
    "needs-induction": r"induction|帰納|for every natural|任意の自然数|first n ",
    "epsilon-delta": r"limit|converg|continuous|連続|極限|収束|derivative|微分|differentiab",
    "inequality": r"inequal|不等式|[<>≤≥]|at most|at least|bound",
    "linear-algebra": r"matrix|matrices|linear map|vector space|eigen"
    r"|determinant|行列|線形|固有|dimension",
    "counterexample": r"counterexample|反例|not injective|単射か"
    r"|ではない|does not exist|存在しない|false",
    "computation": r"compute|evaluate|calculate|求め|解け|solve",
    "existence-uniqueness": r"exists|unique|存在|一意",
    "equivalence": r"if and only if|iff|同値|であることと",
}
REQUIRED = (
    "id",
    "source",
    "field",
    "tier",
    "tier_basis",
    "split",
    "language",
    "statement",
    "statement_sha256",
    "tags",
    "history",
)


def detect_language(text: str) -> str:
    return "ja" if _CJK.search(text) else "en"


def derive_tags(statement: str, extra: list[str] | tuple[str, ...] = ()) -> list[str]:
    low = statement.lower()
    found = {t for t, rule in _TAG_RULES.items() if re.search(rule, low)}
    return sorted(found | set(extra))


def _rank(pid: str) -> str:
    return hashlib.sha256(f"{SPLIT_SALT}:{pid}".encode()).hexdigest()


def assign_splits(items: list[dict[str, Any]]) -> None:
    """Stratified by (field, tier): the per-stratum held-out count is round-half-up of 30%,
    then totals are corrected to round(0.3 N) using the strata with the largest remainders."""

    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in items:
        strata[(p["field"], p["tier"])].append(p)
    quota = {k: int(len(v) * HELD_OUT_FRACTION) for k, v in strata.items()}
    target = round(len(items) * HELD_OUT_FRACTION)
    by_remainder = sorted(
        strata, key=lambda k: (-(len(strata[k]) * HELD_OUT_FRACTION - quota[k]), k)
    )
    for k in by_remainder:
        if sum(quota.values()) >= target:
            break
        quota[k] += 1
    for k, members in strata.items():
        ordered = sorted(members, key=lambda p: _rank(p["id"]))
        for i, p in enumerate(ordered):
            p["split"] = "held_out" if i < quota[k] else "tuning"


def split_checksum(items: list[dict[str, Any]]) -> str:
    lines = sorted(
        f"{p['id']}\t{p['split']}\t{p['statement_sha256']}"
        for p in items
        if "statement_sha256" in p
    )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def validate_manifest(manifest: dict[str, Any], frozen_checksum: str | None = None) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""

    errors: list[str] = []
    items = manifest.get("problems", [])
    ids = [p.get("id") for p in items]
    errors += [f"duplicate id {i}" for i, n in Counter(ids).items() if n > 1]
    statements = Counter(p.get("statement") for p in items)
    errors += [f"duplicate statement text ({n}x)" for s, n in statements.items() if n > 1]
    for p in items:
        pid = p.get("id", "?")
        for key in REQUIRED:
            if key not in p:
                errors.append(f"{pid}: missing {key}")
        if p.get("tier") not in TIERS:
            errors.append(f"{pid}: bad tier {p.get('tier')}")
        if p.get("tier_basis") not in TIER_BASES:
            errors.append(f"{pid}: bad tier_basis")
        if p.get("split") not in SPLITS:
            errors.append(f"{pid}: bad split")
        if p.get("language") not in LANGUAGES:
            errors.append(f"{pid}: bad language")
        if any(t not in TAGS for t in p.get("tags", [])):
            errors.append(f"{pid}: unknown tag")
        text = p.get("statement", "") + " " + (p.get("fixed_lean_statement") or "")
        if any(b.search(text) for b in BANNED_PATTERNS) or re.search(
            r"binomial_square|square_binomial", pid
        ):
            errors.append(f"{pid}: banned squared-binomial material")
        if hashlib.sha256(p.get("statement", "").encode()).hexdigest() != p.get("statement_sha256"):
            errors.append(f"{pid}: statement_sha256 does not match the text")
    held = sum(p.get("split") == "held_out" for p in items)
    if items and abs(held - round(len(items) * HELD_OUT_FRACTION)) > 1:
        errors.append(
            f"held-out size {held} is not ~{int(HELD_OUT_FRACTION * 100)}% of {len(items)}"
        )
    if split_checksum(items) != manifest.get("split_checksum"):
        errors.append("manifest split_checksum does not match its own problems/splits")
    if frozen_checksum is not None and split_checksum(items) != frozen_checksum.strip():
        errors.append("split differs from the frozen SPLIT.sha256 (held-out split must not change)")
    recomputed = [dict(p) for p in items]
    assign_splits(recomputed)
    if {p["id"]: p["split"] for p in recomputed} != {p["id"]: p.get("split") for p in items}:
        errors.append("splits are not the deterministic stratified assignment")
    return errors


def stratum_counts(manifest: dict[str, Any]) -> dict[str, Counter[str]]:
    items = manifest["problems"]
    return {
        "field": Counter(p["field"] for p in items),
        "tier": Counter(p["tier"] for p in items),
        "language": Counter(p["language"] for p in items),
        "split": Counter(p["split"] for p in items),
        "source": Counter(p["source"].split(":")[0] for p in items),
        "history": Counter(h for p in items for h in p["history"]),
    }
