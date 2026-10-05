"""Math convention IDs and model-facing meanings (MCV-001).

The API owns the catalog copy, settings and question text; it pins the same IDs in the same
order. "include" adopts the reading the item names; "exclude" keeps the other one.
"""

from __future__ import annotations

from typing import Any

CONVENTIONS: tuple[tuple[str, str, str], ...] = (
    ("zero_ring_domain", "exclude",
     "include: the zero ring (where 1 = 0) counts as an integral domain; "
     "exclude: an integral domain requires 1 != 0."),
    ("natural_zero", "include",
     "include: the natural numbers contain 0; exclude: the natural numbers start at 1."),
    ("ring_without_unit", "exclude",
     "include: rings without a multiplicative identity count as rings; "
     "exclude: every ring has a multiplicative identity."),
    ("ring_commutative", "exclude",
     "include: 'ring' means commutative ring; exclude: rings need not be commutative."),
    ("zero_pow_zero", "include",
     "include: 0^0 = 1; exclude: 0^0 is undefined."),
    ("division_by_zero", "exclude",
     "include: x / 0 = 0 as in Lean; exclude: division by 0 is undefined, so statements "
     "need nonzero hypotheses."),
    ("compact_hausdorff", "exclude",
     "include: 'compact' includes the Hausdorff property (Bourbaki); "
     "exclude: compact spaces need not be Hausdorff."),
    ("subset_proper", "exclude",
     "include: the symbol ⊂ means proper subset; exclude: ⊂ means ⊆."),
    ("positive_zero", "exclude",
     "include: 'positive' includes 0 (French positif); exclude: 'positive' means > 0."),
    ("log_base_ten", "exclude",
     "include: log without a base is base 10; exclude: log without a base is the natural "
     "logarithm."),
    ("monotone_nonstrict", "include",
     "include: 'increasing' means x <= y implies f(x) <= f(y); "
     "exclude: 'increasing' means strictly increasing."),
)
IDS = tuple(item[0] for item in CONVENTIONS)
DEFAULTS = {item[0]: item[1] for item in CONVENTIONS}
MEANINGS = {item[0]: item[2] for item in CONVENTIONS}


def reading(convention_id: str, choice: str) -> str:
    """The one adopted reading, e.g. 'the natural numbers start at 1'."""

    include, exclude = MEANINGS[convention_id].split("; exclude: ", 1)
    text = include.removeprefix("include: ") if choice == "include" else exclude
    return text.rstrip(".")


def with_readings(statement: str, applied: list[dict[str, str]]) -> str:
    """The statement with every adopted reading written out for the Lean formalization."""

    if not applied:
        return statement
    readings = "; ".join(reading(item["id"], item["choice"]) for item in applied)
    return (
        f"{statement.rstrip()}\n\nConventions: {readings}. "
        "Every other definition keeps its standard meaning."
    )


def parse_claim(value: Any) -> dict[str, Any] | None:
    """The claim's `math_conventions`: a policy and readings for known IDs, or None if malformed."""

    if (
        not isinstance(value, dict)
        or set(value) != {"policy", "choices"}
        or value["policy"] not in {"ask", "default"}
        or not isinstance(value["choices"], dict)
        or any(
            key not in DEFAULTS or choice not in {"include", "exclude"}
            for key, choice in value["choices"].items()
        )
    ):
        return None
    return {"policy": value["policy"], "choices": dict(value["choices"])}


def known_readings(conventions: dict[str, Any]) -> dict[str, str]:
    """Guests (policy "default") use the catalog default for every reading not given."""

    if conventions["policy"] == "default":
        return {**DEFAULTS, **conventions["choices"]}
    return dict(conventions["choices"])
