"""Fidelity gate for model-written formal statements.

Lean proves the statement it is given; it cannot know whether that statement means what the
learner asked.  A statement written by a model must therefore never be released on Lean success
alone.  The gate has two independent parts, both required:

  (a) agreement of two independent formalisations (different instructions) checked in Lean:
      the two propositions must be defeq/identical up to simp-normalisation, with the
      hypothesis really used in both directions.  A bare ``P1 <-> P2`` would be useless: two
      different *true* statements are always equivalent.
  (b) a semantic review of (request, statement) by a model, run in parallel with the proof
      attempt.

The "all numerals of the request occur in the statement" check is only a signal (it wrongly
rejects many faithful statements), never a gate.  Every model call goes through an injected
``ModelCall`` so tests and measurements can fake or count it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

ModelCall = Callable[[str, dict[str, Any]], dict[str, Any]]

_COMMON: Final = (
    "Translate the mathematical statement below into ONE Lean 4 (Mathlib) proposition. "
    "Output only the proposition: a single line, no proof, no `theorem`/`example` keyword, no "
    "tactic, no comment. Quantify every variable explicitly. Do not drop, weaken or strengthen "
    "anything and do not choose a special case. Use Mathlib names. If the statement asks for a "
    "computation or a yes/no decision, state the claim that holds as a proposition. If it "
    "cannot be stated as one Lean proposition, return an empty string.\n"
)
FORMALISE_VARIANTS: Final = (
    _COMMON
    + "Prefer the usual Mathlib phrasing and put hypotheses as implications.\n\nSTATEMENT:\n",
    _COMMON
    + "Give the mathematically most faithful form: assume exactly the structure the wording "
    "names (no more specific and no more general), list each hypothesis as its own binder or "
    "implication, and write comparisons with ≤/< rather than ≥/>.\n\nSTATEMENT:\n",
)
FORMAL_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["formal"],
    "properties": {"formal": {"type": "string"}},
}
REVIEW_PROMPT: Final = (
    "You review a formalisation. REQUEST is what a learner asked. STATEMENT is a Lean 4 (Mathlib) "
    "proposition that will be proved. Approve only if STATEMENT is exactly the mathematical claim "
    "of REQUEST. First fill `checks`: for each of (1) the objects and their types, (2) every "
    "typeclass or structure assumed (what the request says about it, and whether STATEMENT assumes "
    "more or less), (3) each hypothesis (present, none added), (4) quantifiers and their order, "
    "(5) the conclusion, (6) bounds and constants, (7) general claim versus special case, write "
    "one short line. A statement that is weaker OR stronger than the request must be rejected. If "
    "REQUEST also asks for an explanation or a decision, judge only the mathematical claim. Then "
    "set `faithful` and, if false, `issue`. Reply with JSON.\n\n"
)
REVIEW_SCHEMA: Final = {
    "type": "object",
    "additionalProperties": False,
    "required": ["checks", "faithful", "issue"],
    "properties": {
        "checks": {"type": "string"},
        "faithful": {"type": "boolean"},
        "issue": {"type": "string"},
    },
}


def formalise(model: ModelCall, request: str, variant: int) -> str:
    out = model(FORMALISE_VARIANTS[variant] + request, FORMAL_SCHEMA)
    return " ".join(str(out.get("formal", "")).split())


def review(model: ModelCall, request: str, formal: str) -> tuple[bool, str]:
    out = model(REVIEW_PROMPT + f"REQUEST:\n{request}\n\nSTATEMENT:\n{formal}\n", REVIEW_SCHEMA)
    return bool(out.get("faithful")) is True, str(out.get("issue", ""))[:300]


_UNIVERSE = re.compile(r"\b(Type|Sort)\*")


def equivalence_source(first: str, second: str) -> tuple[str, str]:
    """Lean text proving ``first <-> second`` by identity/simp with the hypothesis really used.

    ``Type*`` is replaced by ``Type`` on both sides (separate universe parameters would make two
    identical statements unequal); this only affects the agreement check, never the answer.
    """
    one, two = (_UNIVERSE.sub(r"\1", text) for text in (first, second))
    name = "pals_agree"
    text = (
        f"set_option maxHeartbeats 40000 in\n"
        f"theorem {name} : ({one}) ↔ ({two}) := by\n"
        f"  first\n"
        f"  | exact Iff.rfl\n"
        f"  | (constructor <;> intro pals_h <;> first | exact pals_h | simpa using pals_h)\n"
        f"set_option pp.proofs true in\n#print {name}\n#print axioms {name}\n"
    )
    return text, name


_AX_OK = re.compile(
    r"'pals_agree' (?:depends on axioms: \[([^\]]*)\]|does not depend on any axioms)"
)


def equivalence_verdict(output: str) -> bool:
    """True iff Lean accepted the agreement proof and the hypothesis is used in both directions."""
    from pals_agent import general_recipe_lane as lane

    if "pals_agree" in lane.errored_declarations(output):
        return False
    match = _AX_OK.search(output)
    if match is None:
        return False
    axioms = {a.strip() for a in (match.group(1) or "").split(",") if a.strip()}
    if "sorryAx" in axioms or not axioms <= lane.ALLOWED_AXIOMS:
        return False
    body = output.split("theorem pals_agree", 1)[-1]
    if "pals_h" not in body:
        return "Iff.rfl" in body
    return len(re.findall(r"pals_h", body)) >= 4  # two binders + two uses


@dataclass(slots=True)
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)  # why it failed (empty when passed)
    agree: bool | None = None
    reviewed: bool | None = None
    review_issue: str = ""
    structure: list[str] = field(default_factory=list)  # structure words missing from the statement
    numerals_signal: bool | None = None  # signal only, never a gate
    seconds: dict[str, float] = field(default_factory=dict)


_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def numerals_signal(request: str, formal: str) -> bool:
    """Signal: every number written in the request also occurs in the statement."""

    def numbers(text: str) -> set[str]:
        return set(re.findall(r"\d+", text.translate(_SUP)))

    return numbers(request) <= numbers(formal)


def openai_model_call(
    api_key: str, *, timeout_seconds: float = 60.0, effort: str | None = None
) -> ModelCall:
    """A ModelCall on the pipeline's assessment binding (``proof_reuse_judge``: low effort)."""
    import dataclasses
    import json

    from pals_agent.model_roles import ModelRole, fixed_model_default
    from pals_agent.openai import OpenAIResponsesClient

    binding = fixed_model_default(ModelRole.PROOF_REUSE_JUDGE)
    client = dataclasses.replace(
        OpenAIResponsesClient(
            api_key=api_key, timeout_seconds=timeout_seconds, max_output_tokens=800
        ),
        reasoning_effort=effort or binding.reasoning_effort,  # type: ignore[arg-type]
    )

    def call(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        raw = client.generate(
            model=binding.model,
            prompt=prompt,
            response_schema=schema,
            timeout_seconds=timeout_seconds,
        )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("model reply is not an object")
        return value

    return call


# Deterministic structure vocabulary: a request that NAMES a structure must see it in the
# statement.  Added after the review model approved `Field` for a request about a skew field
# three times out of three (at every reasoning effort) and both formalisations repeated the same
# error; it is therefore tuned on that failure and its held-out power is not measured.  It does
# not understand negations ("do not assume X"), so only rules whose words are rarely negated
# are listed.
# (request pattern, regex the statement must contain, forbidden regex or None, label)
STRUCTURE_RULES: Final = (
    (r"斜体|skew[- ]?field|division ring", r"DivisionRing", None, "division ring"),
    (r"可換環|commutative ring", r"CommRing", None, "commutative ring"),
    (r"整域|integral domain", r"IsDomain", None, "integral domain"),
    (
        r"可換群|アーベル群|abelian group|commutative group",
        r"CommGroup|AddCommGroup",
        None,
        "abelian group",
    ),
    (r"(?<![可換加部])群|\bgroup\b", r"Group", r"\[CommGroup|\[AddCommGroup", "group, not abelian"),
)


def structure_check(request: str, formal: str) -> list[str]:
    """Names of the structures the request mentions but the statement does not reflect."""
    low = request.lower()
    abelian = re.search(r"可換|アーベル|abelian|commutative", low) is not None
    out: list[str] = []
    for pattern, required, forbidden, label in STRUCTURE_RULES:
        if re.search(pattern, low) is None:
            continue
        if (
            re.search(required, formal) is None
            or forbidden
            and not abelian
            and re.search(forbidden, formal)
        ):
            out.append(label)
    return out
