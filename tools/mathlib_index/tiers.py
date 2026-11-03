"""Mechanical classification of exported Mathlib theorems.

Every rule reads Lean environment data or the exported docstring. Evaluation problems and Mathlib's
`docs/*.yaml` must stay out of this module so that recall measured against them remains held out.
`@[wikidata]` is ignored for the same reason: its QIDs are the keys of `docs/1000.yaml`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

TIER_ORDER = (
    "textbook",
    "general",
    "rewrite_api",
    "generated_copy",
    "instance",
    "deprecated",
    "tooling",
    "internal",
)
SEARCHABLE_CORE = frozenset({"textbook", "general"})
SEARCHABLE_FULL = SEARCHABLE_CORE | {"rewrite_api", "generated_copy"}

MATH_ORIGINS = frozenset({"Init", "Batteries", "Mathlib"})
PROGRAMMING_NAME_ROOTS = frozenset({"Lean", "Std"})
NAMED_RESULT_DOC = re.compile(
    r"\*\*|\b(theorem|lemma|inequality|criterion|formula|principle|identity)\b|\blaw of\b",
    re.IGNORECASE,
)
NAMED_RESULT_NAME = re.compile(r"(theorem|lemma|inequality|criterion)", re.IGNORECASE)
API_SUFFIX = re.compile(
    r"(^|_)(coe|apply|symm_apply|def|mk|val|toFun|ext|ext_iff|congr|rfl|injective|surjective)$"
)
API_PREFIX = re.compile(r"^(coe_|mk_|toFun_|val_)")
CENTRAL_PROOF_MODULES = 50
REFERENCE_DATABASES = ("stacks:", "kerodon:")


def origin_of(module: str) -> str:
    return module.split(".", 1)[0] if module else ""


def shared_positions(records: Iterable[Mapping[str, Any]]) -> Counter[tuple[str, int, int]]:
    """Count user-visible theorems per source position.

    Generated declarations (`to_additive`, `simps`, `alias`, `to_dual`) reuse the position of the
    syntax that produced them, so more than one record at a position marks non-primary copies.
    """
    return Counter(
        (record["module"], record["line"], record["column"])
        for record in records
        if record["line"] is not None and not record["attrs"]["internal"]
    )


def is_generated_copy(
    record: Mapping[str, Any],
    position_counts: Mapping[tuple[str, int, int], int],
    primary_at_position: Mapping[tuple[str, int, int], str],
) -> bool:
    if record["additive_source"] is not None:
        return True
    if record["line"] is None:
        return True
    position = (record["module"], record["line"], record["column"])
    return (
        position_counts.get(position, 0) > 1 and primary_at_position.get(position) != record["name"]
    )


def textbook_signals(record: Mapping[str, Any], proof_use_modules: int) -> tuple[str, ...]:
    """Return the mechanical reasons a theorem resembles a textbook statement."""
    doc = record["doc"] or ""
    shape = record["shape"]
    signals: list[str] = []
    if NAMED_RESULT_DOC.search(doc):
        signals.append("doc_names_result")
    if any(ref.startswith(REFERENCE_DATABASES) for ref in record["cross_refs"]):
        signals.append("external_reference")
    if NAMED_RESULT_NAME.search(record["name"].rsplit(".", 1)[-1]):
        signals.append("name_names_result")
    if doc and shape["prop_args"] > 0:
        signals.append("documented_with_hypotheses")
    if proof_use_modules >= CENTRAL_PROOF_MODULES:
        signals.append("central_in_proofs")
    return tuple(signals)


def classify(
    record: Mapping[str, Any],
    *,
    proof_use_modules: int,
    position_counts: Mapping[tuple[str, int, int], int],
    primary_at_position: Mapping[tuple[str, int, int], str],
) -> tuple[str, tuple[str, ...]]:
    attrs = record["attrs"]
    if attrs["internal"] or attrs["private"] or attrs["completion_blocked"]:
        return "internal", ()
    if (
        origin_of(record["module"]) not in MATH_ORIGINS
        or record["name"].split(".", 1)[0] in PROGRAMMING_NAME_ROOTS
    ):
        return "tooling", ()
    if attrs["deprecated"]:
        return "deprecated", ()
    if attrs["instance"]:
        return "instance", ()
    if is_generated_copy(record, position_counts, primary_at_position):
        return "generated_copy", ()
    last = record["name"].rsplit(".", 1)[-1]
    signals = textbook_signals(record, proof_use_modules)
    is_rewrite_attr = attrs["simp"] or attrs["norm_cast"] or attrs["push_cast"] or attrs["ext"]
    if is_rewrite_attr or API_SUFFIX.search(last) or API_PREFIX.search(last):
        # A named result stays textbook even when it also carries a rewrite attribute.
        named = {"doc_names_result", "external_reference", "name_names_result"}
        if named.isdisjoint(signals):
            return "rewrite_api", ()
    if signals:
        return "textbook", signals
    return "general", ()
