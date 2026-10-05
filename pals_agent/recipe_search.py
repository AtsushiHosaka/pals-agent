"""Strict DTO for API-owned, verified Recipe search (no Draft references)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

LANGUAGES = {"en", "ja", "zh-Hans", "zh-Hant"}
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}", re.ASCII)
RECIPE_FIELDS = {
    "recipe_id",
    "recipe_revision",
    "entry_sha256",
    "statement",
    "domain",
    "assumptions",
    "quantifiers",
    "conclusion",
    "proof_method_tag",
    "answer",
    "answer_sha256",
    "output_language",
    "target_source",
    "lean_code",
    "lean_sha256",
    "compiler_receipt_sha256",
    "toolchain_sha256",
}


def bounded_text(value: Any, maximum: int, *, empty: bool = False) -> bool:
    if not isinstance(value, str) or "\x00" in value or not empty and not value.strip():
        return False
    try:
        return len(value.encode("utf-8")) <= maximum
    except UnicodeEncodeError:
        return False


def validate_recipe_candidates(value: Any, *, language: str) -> list[dict[str, Any]]:
    """Fail closed on corrupt search responses; similarity never establishes scope.

    Entry/compiler/toolchain digests are opaque authenticated API attestations; the API
    revalidates their manifest and receipt bindings atomically at settlement. Source and
    answer bytes are cross-checked here as well, without rewriting either string.
    """
    if (not isinstance(language, str) or language not in LANGUAGES
            or not isinstance(value, list) or len(value) > 8):
        raise ValueError("invalid Recipe search response")
    seen: set[tuple[str, int]] = set()
    for candidate in value:
        if not isinstance(candidate, dict) or set(candidate) != RECIPE_FIELDS:
            raise ValueError("invalid Recipe search entry")
        identifier, revision = candidate["recipe_id"], candidate["recipe_revision"]
        if (
            not isinstance(identifier, str)
            or not _IDENTIFIER.fullmatch(identifier)
            or type(revision) is not int
            or not 1 <= revision <= 9_007_199_254_740_991
            or (identifier, revision) in seen
            or not isinstance(candidate["output_language"], str)
            or candidate["output_language"] not in LANGUAGES
        ):
            raise ValueError("invalid Recipe search identity")
        seen.add((identifier, revision))
        for field in ("statement", "domain", "conclusion", "target_source"):
            character_limit = 4000 if field == "domain" else (
                65_000 if field == "target_source" else 20_000
            )
            byte_limit = 65_000 if field == "target_source" else character_limit * 4
            if (
                not bounded_text(candidate[field], byte_limit)
                or len(candidate[field]) > character_limit
            ):
                raise ValueError("invalid Recipe mathematical metadata")
        for field in ("assumptions", "quantifiers"):
            entries = candidate[field]
            if (
                not isinstance(entries, list)
                or len(entries) > 64
                or not all(bounded_text(entry, 16_000) and len(entry) <= 4000 for entry in entries)
            ):
                raise ValueError("invalid Recipe mathematical metadata")
        if candidate["proof_method_tag"] is not None and not bounded_text(
            candidate["proof_method_tag"], 200
        ):
            raise ValueError("invalid Recipe proof method")
        if (
            not bounded_text(candidate["answer"], 240_000)
            or len(candidate["answer"]) > 60_000
            or not bounded_text(candidate["lean_code"], 200_000)
        ):
            raise ValueError("invalid Recipe source or answer")
        for field in (
            "entry_sha256",
            "answer_sha256",
            "lean_sha256",
            "compiler_receipt_sha256",
            "toolchain_sha256",
        ):
            if not isinstance(candidate[field], str) or not _DIGEST.fullmatch(candidate[field]):
                raise ValueError("invalid Recipe digest")
        if any(
            hashlib.sha256(candidate[source].encode()).hexdigest() != candidate[digest]
            for source, digest in (("answer", "answer_sha256"), ("lean_code", "lean_sha256"))
        ):
            raise ValueError("Recipe bytes do not match their digests")
    # A correctly sealed entry in a different language is ineligible, never translated.
    return [candidate for candidate in value if candidate["output_language"] == language]
