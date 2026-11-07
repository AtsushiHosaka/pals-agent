"""Deterministic repair of Mathlib lemma names that a model wrote but the pinned Mathlib lacks.

The data lives in ``content_dictionaries/lean-lemma-aliases-v1.json``: one row per known wrong
name and the right name. A row is applied only when the compiler itself reported that exact name
as an unknown identifier in the compile being repaired, so a name that is merely listed never
changes a proof that compiled. The patch is a whole-token substitution in code (comments and
strings are untouched), it must leave the theorem statements as they were, and the caller
recompiles the result through the verifier that judged the original. Nothing here calls a model
or the network. Extending the table means adding a row, with an ``example`` that fails with the
wrong name and compiles with the right one at the pinned toolchain.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Final

from pals_agent.lean_source_policy import (
    find_source_violation,
    mask_lean_comments_and_strings,
    statement_reference,
)
from pals_agent.models import Diagnostic, VerificationResult

SCHEMA_VERSION: Final = "pals.lean-lemma-aliases.v1"
TABLE_RESOURCE: Final = "lean-lemma-aliases-v1.json"
# Rounds of "patch, recompile" per failed compile; each must replace a name not replaced before.
MAX_PATCH_ROUNDS: Final = 3

_IDENT_SEGMENT = r"[^\W\d][\w'!?]*"
_IDENTIFIER = re.compile(rf"{_IDENT_SEGMENT}(?:\.{_IDENT_SEGMENT})*")
_MATHLIB_REVISION = re.compile(r"[0-9a-f]{40}")
_ENTRY_KEYS = frozenset({"wrong", "right", "note", "example", "verified_with"})
_VERIFIED_WITH_KEYS = frozenset({"lean", "mathlib"})
_MAX_ENTRIES = 2000
_MAX_TEXT = 4000

_SYMBOL = r"[^\W\d][\w'!?.]{0,127}"
# Compiler wording (`Unknown identifier `x``, older `unknown identifier 'x'`) and the API's closed
# repair vocabulary (`Unknown identifier x; use an available declaration.`).
_UNKNOWN_NAME = (
    re.compile(rf"[Uu]nknown (?:identifier|constant) [`'‘]({_SYMBOL})[`'’]\.?"),
    re.compile(rf"Unknown identifier ({_SYMBOL}); use an available declaration\."),
)


class LemmaAliasTableError(ValueError):
    """The alias table is malformed; it is never partially applied."""


@dataclass(frozen=True, slots=True)
class LemmaAlias:
    wrong: str
    right: str
    note: str
    example: str
    lean: str
    mathlib: str


@dataclass(frozen=True, slots=True)
class LemmaAliasTable:
    aliases: tuple[LemmaAlias, ...]
    _by_wrong: dict[str, LemmaAlias] = field(default_factory=dict, repr=False, compare=False)

    def lookup(self, reported: str) -> tuple[LemmaAlias, str] | None:
        """Return the row for a reported name, and the field path that followed the lemma.

        ``abs_add.symm`` is reported whole by Lean when ``abs_add`` is unknown, so a name is also
        covered when it is a table name followed by ``.field`` segments.
        """
        parts = reported.split(".")
        for length in range(len(parts), 0, -1):
            alias = self._by_wrong.get(".".join(parts[:length]))
            if alias is not None:
                return alias, "".join(f".{part}" for part in parts[length:])
        return None


def parse_lemma_alias_table(payload: object) -> LemmaAliasTable:
    """Validate a table; reject duplicates, ``wrong == right``, chains and non-identifiers."""
    if not isinstance(payload, dict):
        raise LemmaAliasTableError("lemma alias table must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LemmaAliasTableError("lemma alias table has an unexpected schema version")
    if set(payload) - {"schema_version", "notes", "entries"}:
        raise LemmaAliasTableError("lemma alias table has unexpected top-level keys")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) > _MAX_ENTRIES:
        raise LemmaAliasTableError("lemma alias table entries must be a bounded list")
    aliases: list[LemmaAlias] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        alias = _parse_entry(entry, index)
        if alias.wrong in seen:
            raise LemmaAliasTableError(f"entry {index}: duplicate wrong name {alias.wrong!r}")
        seen.add(alias.wrong)
        aliases.append(alias)
    wrong_names = {alias.wrong for alias in aliases}
    for alias in aliases:
        if alias.right in wrong_names:
            # A chain would let one unknown name rewrite into another unknown name.
            raise LemmaAliasTableError(f"right name {alias.right!r} is also a wrong name")
    return LemmaAliasTable(
        aliases=tuple(aliases), _by_wrong={alias.wrong: alias for alias in aliases}
    )


def _parse_entry(entry: object, index: int) -> LemmaAlias:
    where = f"entry {index}"
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        raise LemmaAliasTableError(f"{where}: must have exactly {sorted(_ENTRY_KEYS)}")
    wrong, right = entry["wrong"], entry["right"]
    for label, name in (("wrong", wrong), ("right", right)):
        if not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None:
            raise LemmaAliasTableError(f"{where}: {label} is not a Lean identifier")
    if wrong == right:
        raise LemmaAliasTableError(f"{where}: wrong and right are the same name")
    for label in ("note", "example"):
        text = entry[label]
        if not isinstance(text, str) or not text.strip() or len(text) > _MAX_TEXT:
            raise LemmaAliasTableError(f"{where}: {label} must be nonblank bounded text")
    verified = entry["verified_with"]
    if not isinstance(verified, dict) or set(verified) != _VERIFIED_WITH_KEYS:
        raise LemmaAliasTableError(f"{where}: verified_with needs exactly lean and mathlib")
    lean, mathlib = verified["lean"], verified["mathlib"]
    if not isinstance(lean, str) or not lean.strip() or len(lean) > 64:
        raise LemmaAliasTableError(f"{where}: verified_with.lean must be a version string")
    if not isinstance(mathlib, str) or _MATHLIB_REVISION.fullmatch(mathlib) is None:
        raise LemmaAliasTableError(f"{where}: verified_with.mathlib must be a 40-hex revision")
    return LemmaAlias(
        wrong=wrong,
        right=right,
        note=entry["note"],
        example=entry["example"],
        lean=lean,
        mathlib=mathlib,
    )


@lru_cache(maxsize=1)
def default_lemma_alias_table() -> LemmaAliasTable:
    text = (
        resources.files("pals_agent.content_dictionaries")
        .joinpath(TABLE_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return parse_lemma_alias_table(json.loads(text))


def unknown_names(diagnostics: Iterable[Diagnostic]) -> tuple[str, ...]:
    """Names the compiler reported unknown, in report order without repeats."""
    names: dict[str, None] = {}
    for diagnostic in diagnostics:
        if diagnostic.severity != "error":
            continue
        first_line = diagnostic.message.splitlines()[0] if diagnostic.message else ""
        for pattern in _UNKNOWN_NAME:
            match = pattern.fullmatch(first_line.strip())
            if match is not None:
                names[match.group(1)] = None
                break
    return tuple(names)


@dataclass(frozen=True, slots=True)
class LemmaPatch:
    lean_code: str
    replacements: tuple[tuple[str, str], ...]  # (name Lean reported, name written instead)


def statement_fingerprint(lean_code: str) -> object:
    """What must not change: every declaration's statement, with proof bodies set aside."""
    return statement_reference(lean_code)


def patch_unknown_lemmas(
    lean_code: str,
    diagnostics: Iterable[Diagnostic],
    table: LemmaAliasTable,
    *,
    same_statement: Callable[[str, str], bool] | None = None,
) -> LemmaPatch | None:
    """Substitute table names that ``diagnostics`` report unknown; ``None`` if nothing applies.

    Only whole tokens in code are replaced: not part of a longer name (``abs_add_le``,
    ``abs_add'``, ``foo.abs_add``), not in a comment or string. Everything else stays
    byte-identical, and a result whose statements differ is refused.
    """
    wanted: dict[str, str] = {}
    for reported in unknown_names(diagnostics):
        hit = table.lookup(reported)
        if hit is not None:
            alias, suffix = hit
            wanted[reported] = alias.right + suffix
    if not wanted:
        return None
    violation = find_source_violation(lean_code)
    if violation is not None and violation.code == "lean.disallowed_ambiguous_lexing":
        return None
    masked = mask_lean_comments_and_strings(lean_code)
    spans: list[tuple[int, int, str, str]] = []
    for reported, replacement in wanted.items():
        for match in _token_pattern(reported).finditer(masked):
            spans.append((match.start(), match.end(), reported, replacement))
    if not spans:
        return None
    spans.sort()
    pieces: list[str] = []
    position = 0
    for start, end, _, replacement in spans:
        pieces += [lean_code[position:start], replacement]
        position = end
    pieces.append(lean_code[position:])
    patched = "".join(pieces)
    if patched == lean_code:
        return None
    unchanged = same_statement or _same_statement
    if not unchanged(lean_code, patched):
        return None
    applied = tuple(dict.fromkeys((reported, wanted[reported]) for _, _, reported, _ in spans))
    return LemmaPatch(lean_code=patched, replacements=applied)


def _same_statement(before: str, after: str) -> bool:
    return statement_fingerprint(before) == statement_fingerprint(after)


@lru_cache(maxsize=256)
def _token_pattern(name: str) -> re.Pattern[str]:
    # A Lean token is a maximal run of identifier characters and dots between them. The name must
    # be that whole run: not preceded by a character or `.` that would make it a suffix or a
    # field, and not followed by one that would make it a prefix or the start of a field path.
    return re.compile(
        rf"(?<![\w'!?.«]){re.escape(name)}(?![\w'!?»])(?!\.[^\W\d])"
    )


@dataclass(frozen=True, slots=True)
class LemmaRepairRound:
    patch: LemmaPatch
    verification: VerificationResult


@dataclass(frozen=True, slots=True)
class LemmaRepairRun:
    original_code: str
    lean_code: str
    verification: VerificationResult
    rounds: tuple[LemmaRepairRound, ...]

    @property
    def replacements(self) -> tuple[tuple[str, str], ...]:
        return tuple(pair for round_ in self.rounds for pair in round_.patch.replacements)


def repair_unknown_lemmas(
    lean_code: str,
    verification: VerificationResult,
    *,
    verify: Callable[[str], VerificationResult],
    table: LemmaAliasTable,
    accept: Callable[[str], bool] = lambda _code: True,
    same_statement: Callable[[str, str], bool] | None = None,
    on_round: Callable[[LemmaPatch], None] | None = None,
    max_rounds: int = MAX_PATCH_ROUNDS,
) -> LemmaRepairRun | None:
    """Patch, recompile with ``verify`` and repeat while the compiler names more table names.

    ``accept`` is the caller's own gate for a candidate (source policy and statement alignment);
    a patched source it refuses is never compiled. Each round must replace a name no earlier round
    replaced, so the loop ends within ``max_rounds`` and cannot cycle. ``None`` means no round ran.
    """
    current = lean_code
    current_verification = verification
    replaced: set[str] = set()
    rounds: list[LemmaRepairRound] = []
    for _ in range(max_rounds):
        if current_verification.success:
            break
        patch = patch_unknown_lemmas(
            current, current_verification.diagnostics, table, same_statement=same_statement
        )
        if patch is None or any(name in replaced for name, _ in patch.replacements):
            break
        if not accept(patch.lean_code):
            break
        replaced.update(name for name, _ in patch.replacements)
        if on_round is not None:
            on_round(patch)
        current = patch.lean_code
        current_verification = verify(current)
        rounds.append(LemmaRepairRound(patch=patch, verification=current_verification))
    if not rounds:
        return None
    return LemmaRepairRun(
        original_code=lean_code,
        lean_code=current,
        verification=current_verification,
        rounds=tuple(rounds),
    )


def repair_metadata(run: LemmaRepairRun) -> dict[str, Any]:
    """Trace record: what was replaced and the code it replaced, no model involved."""
    return {
        "replacements": [
            {"reported": reported, "replacement": replacement}
            for reported, replacement in run.replacements
        ],
        "rounds": len(run.rounds),
        "verified": run.verification.success,
        "original_lean_code": run.original_code,
    }
