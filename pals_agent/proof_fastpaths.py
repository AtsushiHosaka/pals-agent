"""Model-call-free shortcuts for the Draft/Sketch/Prove repair loop.

Both shortcuts are opt-in (see ``ProofPipeline.harness_splice`` and
``ProofPipeline.deterministic_repair_route``).  They never decide whether a proof is
correct: every candidate they produce still goes through the same preflight and Lean
verification as a model-written one.

* ``splice_formal_harness`` repairs a purely typographical difference between the fixed
  formal statement and the statement the model wrote (spacing around ``=``, ``;`` versus
  a newline after ``let``).  Without it the pipeline spends a route-selection call plus a
  Draft, Sketch and Prove call to ask the model for the same statement again.
* ``deterministic_repair_route`` picks the restart stage without a model call when the
  statement is fixed by the user and the failure is a plain Lean or generation failure.
"""

from __future__ import annotations

import re
from typing import Literal

from pals_agent.models import (
    GenerationFeedback,
    ProofRequest,
    RepairRoute,
    RepairRouteAttemptEvidence,
    RepairRouteDecision,
)

DETERMINISTIC_ROUTE_PROVIDER = "pals-deterministic-policy"

_TOKEN_RE = re.compile(
    r"""
    (?P<comment>--[^\n]*|/-.*?-/)
    |(?P<string>"(?:\\.|[^"\\])*")
    |(?P<token>\w+|[^\w\s])
    """,
    re.VERBOSE | re.DOTALL,
)

# A line break and ``;`` are interchangeable separators in a Lean ``let`` chain, so a
# separator token never decides equality.  All other tokens must match exactly.
_IGNORED_TOKENS = frozenset({";"})

# Failures where the restart point is a judgement about the mathematics or the proof
# method, not a mechanical consequence of the diagnostics.  The model keeps deciding.
_MODEL_DECIDES_CODES = frozenset(
    {
        "pals.repair_stagnation",
        "pals.proof_method_mismatch",
    }
)
_HARNESS_MISMATCH_CODE = "lean.formal_harness_mismatch"

Span = tuple[int, int]


def _tokens(text: str) -> list[tuple[str, Span]]:
    result: list[tuple[str, Span]] = []
    for match in _TOKEN_RE.finditer(text):
        if match.lastgroup == "comment":
            continue
        token = match.group(0)
        if token in _IGNORED_TOKENS:
            continue
        result.append((token, match.span()))
    return result


def _find_statement_span(lean_code: str, formal_statement: str) -> Span | None:
    harness = [token for token, _span in _tokens(formal_statement)]
    if not harness:
        return None
    code = _tokens(lean_code)
    width = len(harness)
    for start in range(len(code) - width + 1):
        if all(code[start + offset][0] == harness[offset] for offset in range(width)):
            return code[start][1][0], code[start + width - 1][1][1]
    return None


def contains_formal_statement_modulo_layout(lean_code: str, formal_statement: str) -> bool:
    """True when the statement appears with only layout and separator differences."""

    return _find_statement_span(lean_code, formal_statement) is not None


def splice_formal_harness(lean_code: str, formal_statement: str) -> str | None:
    """Return the code with the fixed statement restored verbatim, or ``None``.

    ``None`` means the model changed the statement itself (or wrote no statement), which
    only the model can repair.  A returned string differs from ``lean_code`` solely inside
    the statement's own span, where it now equals the user's formal statement.
    """

    span = _find_statement_span(lean_code, formal_statement)
    if span is None:
        return None
    start, end = span
    spliced = f"{lean_code[:start]}{formal_statement.strip()}{lean_code[end:]}"
    return None if spliced == lean_code else spliced


def deterministic_repair_route(
    request: ProofRequest,
    feedback: GenerationFeedback,
) -> RepairRouteDecision | None:
    """Pick the restart stage without a model call, or return ``None`` to ask the model.

    Applies only when the user fixed the formal statement.  In 59 of 59 recorded Terra
    repairs the model's choice was a function of one fact: ``draft`` exactly when the
    attempt failed ``lean.formal_harness_mismatch``, ``prove`` otherwise.  Restarting the
    prose Draft cannot repair a typographical or truncated statement, so a mismatch resumes
    at the earliest stage whose output does not already carry the statement.
    """

    if not request.formal_statement or not request.formal_statement.strip():
        return None
    codes = {diagnostic.code for diagnostic in feedback.diagnostics if diagnostic.code}
    if codes & _MODEL_DECIDES_CODES:
        return None

    draft = feedback.previous_draft
    sketch = feedback.previous_sketch
    route: RepairRoute
    reason: str
    if draft is None or not draft.text.strip():
        route, reason = "draft", "no usable Draft exists"
    elif sketch is None or not sketch.lean_code.strip():
        route, reason = "sketch", "no usable Sketch exists"
    elif _HARNESS_MISMATCH_CODE in codes and not contains_formal_statement_modulo_layout(
        sketch.lean_code, request.formal_statement
    ):
        route, reason = "sketch", "the Sketch does not carry the fixed formal statement"
    elif _HARNESS_MISMATCH_CODE in codes:
        route, reason = "prove", "the Sketch carries the fixed statement; Prove deviated"
    else:
        route, reason = "prove", "the statement is fixed and the failure is a proof failure"

    outcome: Literal["selected"] = "selected"
    return RepairRouteDecision(
        route=route,
        rationale=f"Deterministic policy: {reason}.",
        raw_model_output="",
        provider=DETERMINISTIC_ROUTE_PROVIDER,
        selector_attempts=(
            RepairRouteAttemptEvidence(
                attempt=1,
                outcome=outcome,
                diagnostic_code=None,
                route=route,
            ),
        ),
    )
