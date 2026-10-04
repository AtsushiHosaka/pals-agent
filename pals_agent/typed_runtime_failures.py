"""Bounded private retrieval evidence; never serialize provider exceptions/secrets."""

from __future__ import annotations

import hashlib
from typing import Any

from pals_agent.openai_diagnostics import sanitize_openai_diagnostics
from pals_agent.reranker_diagnostics import sanitize_reranker_diagnostics

_CODES = frozenset(
    {
        "typed_structuring_unavailable",
        "typed_structuring_invalid",
        "typed_embedding_unavailable",
        "typed_candidates_unavailable",
        "typed_candidates_incompatible",
        "typed_reranking_unavailable",
        "typed_reranking_invalid",
    }
)


class TypedRetrievalFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        raw_openmath: str | None = None,
        validation_error: str | None = None,
        reranker_diagnostics: object = None,
        raw_json: str | None = None,
        provider_diagnostics: object = None,
    ) -> None:
        if code not in _CODES:
            raise ValueError("Unknown typed retrieval failure code")
        super().__init__(code)
        self.code = code
        self.private_evidence: dict[str, Any] = {"code": code}
        safe_provider = sanitize_openai_diagnostics(provider_diagnostics)
        if safe_provider:
            self.private_evidence["provider"] = safe_provider
        safe_reranker = sanitize_reranker_diagnostics(reranker_diagnostics)
        if safe_reranker:
            self.private_evidence["reranker"] = safe_reranker
        if validation_error is not None:
            # Only local XML-validator diagnostics are eligible; provider/transport
            # exception strings are deliberately never supplied here.
            self.private_evidence["validation_error_prefix"] = validation_error.encode(
                "utf-8", errors="replace"
            )[:512].decode("utf-8", errors="ignore")
        if raw_json is not None:
            raw = raw_json.encode("utf-8", errors="replace")
            self.private_evidence["bounded_private_json"] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "prefix": raw[:4096].decode("utf-8", errors="ignore"),
                "bytes": len(raw),
                "truncated": len(raw) > 4096,
            }
        if raw_openmath is not None:
            raw = raw_openmath.encode("utf-8", errors="replace")
            prefix = raw[:4096].decode("utf-8", errors="ignore")
            self.private_evidence.update(
                raw_openmath_sha256=hashlib.sha256(raw).hexdigest(),
                raw_openmath_prefix=prefix,
                raw_openmath_bytes=len(raw),
                raw_openmath_truncated=len(raw) > 4096,
            )
