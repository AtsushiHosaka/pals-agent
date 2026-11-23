"""Check that a Mathlib name the compiler called unknown exists in a declaration index (pals#381).

A repair that swaps one invented lemma name for another wastes a round. When the failed compile
names an unknown identifier, this module looks the name up in an index of declaration names built
from the pinned Mathlib source (``tools/mathlib_index``: ``decls.jsonl.gz``; the worker has no database capability, so SQLite is not read)
and returns a short prompt block that says one of three things for each name:

* it exists exactly, so the failure is a missing import or namespace;
* it exists only under a namespace (``Nat.succ_le`` for ``succ_le``), so qualify it;
* it is absent, with up to a few similarly named declarations.

The block is advice, never proof: the index reads source text, so it shows that a name is
declared, not that it compiles, applies or is true. Lean still decides every candidate. Every
name that reaches the prompt is a string from the index that matches a strict identifier grammar;
nothing from a diagnostic is echoed except the identifier the caller already validated. The
feature is off unless ``PALS_DECL_EXISTENCE_CHECK_ENABLED=true`` and an index path is given, and
with it off, or with an unreadable index, the prompt is exactly what it was before. Nothing here
calls a model or the network.
"""

from __future__ import annotations

import gzip
import json
import os
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Final

DECL_EXISTENCE_ENV: Final = "PALS_DECL_EXISTENCE_CHECK_ENABLED"
DECL_INDEX_PATH_ENV: Final = "PALS_DECL_INDEX_PATH"

MAX_NAMES: Final = 3  # unknown identifiers explained per prompt
MAX_CANDIDATES: Final = 4  # similar declarations listed per absent name
_MIN_SIMILARITY: Final = 0.45
_MAX_INDEX_NAMES: Final = 2_000_000
_MAX_NAME_CHARS: Final = 160

_NAME: Final = re.compile(r"[^\W\d][\w'!?]*(?:\.[^\W\d][\w'!?]*)*")
_CAMEL: Final = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")


def _tokens(name: str) -> frozenset[str]:
    words: set[str] = set()
    for part in re.split(r"[._'!?\s]+", name):
        words.update(word.lower() for word in _CAMEL.findall(part))
    return frozenset(words)


@dataclass(frozen=True, slots=True)
class Lookup:
    """What the index says about one reported name."""

    name: str
    exact: bool
    qualified: tuple[str, ...]
    similar: tuple[str, ...]


class DeclarationIndex:
    """Declaration names with exact, namespace-suffix and token-overlap lookup."""

    def __init__(self, names: Iterable[str]) -> None:
        unique = {
            name
            for name in names
            if len(name) <= _MAX_NAME_CHARS and _NAME.fullmatch(name) is not None
        }
        self._names = frozenset(unique)
        self._by_last: dict[str, list[str]] = defaultdict(list)
        self._by_token: dict[str, list[str]] = defaultdict(list)
        self._tokens: dict[str, frozenset[str]] = {}
        for name in sorted(unique):
            self._by_last[name.rsplit(".", 1)[-1]].append(name)
            tokens = _tokens(name.rsplit(".", 1)[-1])
            self._tokens[name] = tokens
            for token in tokens:
                self._by_token[token].append(name)

    def __len__(self) -> int:
        return len(self._names)

    def lookup(self, reported: str) -> Lookup:
        if reported in self._names:
            return Lookup(reported, True, (), ())
        last = reported.rsplit(".", 1)[-1]
        qualified = tuple(
            name for name in self._by_last.get(last, ()) if name.endswith("." + reported)
        )
        if qualified:
            return Lookup(reported, False, tuple(sorted(qualified, key=_rank)[:MAX_CANDIDATES]), ())
        return Lookup(reported, False, (), self._similar(last))

    def _similar(self, last: str) -> tuple[str, ...]:
        wanted = _tokens(last)
        if not wanted:
            return ()
        pool: dict[str, int] = defaultdict(int)
        for token in wanted:
            for name in self._by_token.get(token, ()):
                pool[name] += 1
        scored: list[tuple[float, str]] = []
        for name, shared in pool.items():
            union = len(wanted | self._tokens[name])
            overlap = shared / union
            text = SequenceMatcher(None, last, name.rsplit(".", 1)[-1]).ratio()
            score = 0.6 * overlap + 0.4 * text
            if score >= _MIN_SIMILARITY:
                scored.append((-score, name))
        scored.sort(key=lambda item: (item[0], _rank(item[1])))
        return tuple(name for _, name in scored[:MAX_CANDIDATES])


def _rank(name: str) -> tuple[int, str]:
    return (len(name), name)


def _read_names(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    names: list[str] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            name = record.get("name") if isinstance(record, dict) else None
            if isinstance(name, str):
                names.append(name)
            if len(names) > _MAX_INDEX_NAMES:
                raise ValueError("declaration index is too large")
    return names


@lru_cache(maxsize=2)
def _load(path: str, mtime_ns: int) -> DeclarationIndex | None:
    del mtime_ns  # part of the cache key: a rebuilt index is read again
    try:
        index = DeclarationIndex(_read_names(Path(path)))
    except (OSError, ValueError):
        return None
    return index if len(index) else None


def declaration_index_from_env() -> DeclarationIndex | None:
    """The configured index, or ``None`` when the check is off or the index is unreadable."""
    flag = os.environ.get(DECL_EXISTENCE_ENV, "false")
    if flag not in {"true", "false"}:
        raise ValueError(f"{DECL_EXISTENCE_ENV} must be true or false")
    raw = os.environ.get(DECL_INDEX_PATH_ENV, "").strip()
    if flag != "true" or not raw:
        return None
    try:
        return _load(raw, Path(raw).stat().st_mtime_ns)
    except OSError:
        return None


def declaration_existence_block(identifiers: Sequence[str], index: DeclarationIndex | None) -> str:
    """Prompt block for unknown identifiers, or the empty string when there is nothing to say."""
    if index is None or not identifiers:
        return ""
    lines: list[str] = []
    for reported in identifiers[:MAX_NAMES]:
        if _NAME.fullmatch(reported) is None:
            continue
        found = index.lookup(reported)
        if found.exact:
            lines.append(
                f"- `{reported}` is declared in the pinned Mathlib index, so the failure is a "
                "missing import or a wrong namespace or argument form, not a missing name."
            )
        elif found.qualified:
            lines.append(
                f"- `{reported}` is not a declaration name; the index has it under a namespace: "
                + ", ".join(f"`{name}`" for name in found.qualified)
                + ". Qualify it (or open the namespace) if one of them is what you meant."
            )
        elif found.similar:
            lines.append(
                f"- `{reported}` is not in the pinned Mathlib index. Declarations with similar "
                "names: "
                + ", ".join(f"`{name}`" for name in found.similar)
                + ". Read each one's statement before using it."
            )
        else:
            lines.append(
                f"- `{reported}` is not in the pinned Mathlib index and nothing close was found; "
                "use an automation tactic or prove the step with `have` instead of guessing a name."
            )
    if not lines:
        return ""
    return (
        "\nDeclaration index check (names from Mathlib source text; a listed name is a "
        "candidate only, and the Lean compiler alone decides whether it works):\n"
        + "\n".join(lines)
        + "\n"
    )
