"""Deliver the verified answer even when its explanation cannot be approved.

Selected behind ``PALS_EXPLANATION_FALLBACK_ENABLED`` (default off). The worker calls
``deliver_unreviewed_explanation`` where it would otherwise record a terminal explanation
failure for a proof that is already verified and passed semantic review.

The pinned pals-api accepts a completed explanation only with approved review evidence
(``ProofExplanationCompletedRequest.review_evidence.decision`` is the literal ``approved``, and
the ``proof_output_reviews`` table has ``CHECK (decision = 'approved')``). This module therefore
never fabricates approval: it sends the content with an explicit ``review_status: "unreviewed"``
and no evidence. Until the API accepts that request, the call is rejected, this function returns
``None`` and the worker records the failure exactly as before.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

EXPLANATION_FALLBACK_ENV: Final = "PALS_EXPLANATION_FALLBACK_ENABLED"
UNREVIEWED_STATUS: Final = "explanation_unreviewed"
_MAX_REFERENCES: Final = 20
_MAX_EXCERPT_CHARS: Final = 20_000
_CHUNK_LINES: Final = 40
_LOGGER = logging.getLogger(__name__)

_TEXT: Final[dict[str, dict[str, str]]] = {
    "en": {
        "overview": "Lean has verified a proof of this statement: {statement}",
        "title": "Verified Lean proof",
        "summary": (
            "Lean accepted this proof. A step-by-step explanation could not be completed, so "
            "the verified Lean code is shown instead."
        ),
        "conclusion": "The statement is proved; the written explanation has not been reviewed.",
    },
    "ja": {
        "overview": "次の主張の証明を Lean が検証しました: {statement}",
        "title": "検証済みの Lean 証明",
        "summary": (
            "Lean がこの証明を受理しました。ステップごとの解説は完成できなかったため、"
            "検証済みの Lean コードを示します。"
        ),
        "conclusion": "主張は証明されています。ただし、文章による解説は未レビューです。",
    },
    "zh-Hans": {
        "overview": "Lean 已验证以下命题的证明：{statement}",
        "title": "已验证的 Lean 证明",
        "summary": "Lean 已接受该证明。逐步讲解未能完成，因此改为展示已验证的 Lean 代码。",
        "conclusion": "命题已被证明；文字讲解尚未经过审核。",
    },
    "zh-Hant": {
        "overview": "Lean 已驗證以下命題的證明：{statement}",
        "title": "已驗證的 Lean 證明",
        "summary": "Lean 已接受該證明。逐步講解未能完成，因此改為顯示已驗證的 Lean 程式碼。",
        "conclusion": "命題已被證明；文字講解尚未經過審核。",
    },
}


def explanation_fallback_enabled() -> bool:
    return os.environ.get(EXPLANATION_FALLBACK_ENV, "false") == "true"


def coarse_references(lean_code: str) -> list[dict[str, Any]]:
    """Blank-line separated blocks, merged up to 40 lines, as exact line-range references."""
    lines = lean_code.splitlines()
    blocks: list[list[int]] = []
    start: int | None = None
    for number, line in enumerate([*lines, ""], start=1):
        if line.strip():
            start = number if start is None else start
        elif start is not None:
            blocks.append([start, number - 1])
            start = None
    if not blocks:
        raise ValueError("verified Lean code has no non-blank lines")
    merged: list[list[int]] = []
    for begin, end in blocks:
        if merged and end - merged[-1][0] + 1 <= _CHUNK_LINES:
            merged[-1][1] = end
        else:
            merged.append([begin, end])
    references: list[dict[str, Any]] = []
    for begin, end in merged[:_MAX_REFERENCES]:
        excerpt = "\n".join(lines[begin - 1 : end])
        if len(excerpt) > _MAX_EXCERPT_CHARS:
            continue
        references.append({"start_line": begin, "end_line": end, "excerpt": excerpt})
    if not references:
        raise ValueError("verified Lean code has no block within the reference limit")
    return references


def minimal_explanation_content(
    *, theorem_statement: str, lean_code: str, language: str
) -> dict[str, Any]:
    """A deterministic explanation: the statement, a plain conclusion, and coarse references."""
    text = _TEXT[language]
    statement = " ".join(theorem_statement.split())[:400]
    return {
        "overview": text["overview"].format(statement=statement),
        "sections": [
            {
                "id": "verified-lean-proof",
                "title": text["title"],
                "summary": text["summary"],
                "references": coarse_references(lean_code),
            }
        ],
        "conclusion": text["conclusion"],
        "model": "deterministic-fallback",
        "provider": "pals-agent",
        "elapsed_ms": 0,
    }


def deliver_unreviewed_explanation(
    api_client: Any,
    *,
    proof_job_id: str,
    claim_id: str,
    theorem_statement: str,
    lean_code: str,
    language: str,
    reason: str,
    candidate_content: dict[str, Any] | None,
    private_review_failures: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Send the best available unreviewed explanation; ``None`` means it was not accepted.

    ``candidate_content`` is the last schema-valid candidate (for example one QA rejected twice);
    without one, the deterministic minimal explanation is sent. ``reason`` is a closed label.
    """
    source = "candidate" if candidate_content is not None else "deterministic"
    try:
        content = candidate_content or minimal_explanation_content(
            theorem_statement=theorem_statement, lean_code=lean_code, language=language
        )
        response: dict[str, Any] = api_client.upsert_unreviewed_proof_explanation(
            proof_job_id=proof_job_id,
            claim_id=claim_id,
            content=content,
            unreviewed_reason=reason,
            private_review_failures=private_review_failures,
        )
    except Exception as exc:  # the API may not accept this yet; the caller records the failure
        _LOGGER.warning(
            "explanation_unreviewed_not_delivered proof_job=%s reason=%s source=%s error=%s",
            proof_job_id,
            reason,
            source,
            type(exc).__name__,
        )
        return None
    _LOGGER.warning(
        "explanation_unreviewed_delivered proof_job=%s reason=%s source=%s",
        proof_job_id,
        reason,
        source,
    )
    return response
