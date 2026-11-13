"""Stacks Project tags named in a request, resolved to Mathlib declarations.

A learner may ask for "Stacks Project Tag 02LS". Mathlib marks the declarations that formalise a
Stacks statement with ``@[stacks TAG]``; ``tools/mathlib_index/extract_stacks_tags.py`` collects
those attributes from the pinned Mathlib source into ``mathlib-stacks-tags-v1.json``. This module
looks the tags a request names up in that file and returns a prompt block that points the model
at the declaration, so it does not have to rediscover a name it can only guess.

The block is advice, never proof: the names come from source text (qualified by the namespaces
that enclose them), and Lean still decides. A request that names no known tag gets the empty
string, so every other prompt is unchanged.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

_DATA: Final = Path(__file__).with_name("content_dictionaries") / "mathlib-stacks-tags-v1.json"
_TAG_NAMED: Final = re.compile(
    r"\b(?:tags?|stacks(?:\s+project)?)\s*[:#]?\s*`?([0-9][0-9A-Z]{3})\b", re.IGNORECASE
)
_MAX_TAGS: Final = 3
_MAX_DECLARATIONS: Final = 4


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    try:
        payload = json.loads(_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tags = payload.get("tags") if isinstance(payload, dict) else None
    return tags if isinstance(tags, dict) else {}


def named_tags(text: str) -> list[str]:
    """The distinct tags a request names, in order (e.g. ``Tag 02LS``, ``Stacks Project 01KJ``)."""
    return list(dict.fromkeys(match.group(1).upper() for match in _TAG_NAMED.finditer(text)))


def stacks_tag_guidance(*parts: str | None) -> str:
    """Prompt block for the known tags a request names, else the empty string."""
    text = "\n".join(part for part in parts if part)
    index = _index()
    lines: list[str] = []
    for tag in named_tags(text)[:_MAX_TAGS]:
        entries = index.get(tag)
        if not entries:
            continue
        for entry in entries[:_MAX_DECLARATIONS]:
            name = entry.get("name") or "(anonymous instance; found by type class inference)"
            lines.append(
                f"- Stacks tag {tag}: Mathlib `{name}` ({entry.get('kind')}, "
                f"{entry.get('module')}): `{entry.get('statement')}`"
            )
    if not lines:
        return ""
    return (
        "Stacks Project tags named in the request. Mathlib already has a declaration marked with "
        "each tag (names are implied by the source's namespaces; confirm by using them). Prefer "
        "stating the claim in this form and closing it with the declaration or with "
        "`inferInstance`:\n" + "\n".join(lines) + "\n"
    )
