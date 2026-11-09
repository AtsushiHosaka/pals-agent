"""Opt-in import planning: verify over a small import closure, then once over the full imports.

Loading the Stacks Frontier costs seconds and gigabytes on every verification, and most of it is
never used by one statement. A suggester (the source-only import index, see
``pals_agent.lean_import_index``) proposes the few modules a statement names. The verifier then
replaces the source's header imports with that proposal and compiles. A proposal is a guess, so
the original source, with all of its own imports, is verified once more whenever

* the suggester has no usable plan (declined: nothing was compiled over a plan), or
* the compile over the plan fails with an error that a missing import explains (retried).

Only the import header is rewritten (the line count is kept), so a proof that is accepted over the
plan is accepted for the very same statement and proof text, and the trusted audit runs over the
same, smaller imports. Nothing is cached and the verdict of a verification never comes from
anything but a Lean run.

Everything this module reports is a closed vocabulary or a number: a status code per
verification, never a question, a Lean source, a module name or a diagnostic message.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from pals_agent.models import VerificationResult

if TYPE_CHECKING:
    from pals_agent.lean_profiles import LibraryProfile

APPLIED: Final = "applied"
DECLINED_PREFIX: Final = "declined."
RETRIED_PREFIX: Final = "retried."

# The plan was never compiled; the original source is verified once, as without the flag.
DECLINE_REASONS: Final = frozenset({
    "statement_unreadable",  # the statements of the source could not be located
    "local_definitions",  # the source defines its own objects, which the index does not follow
    "plan_empty",  # no constant resolved, so there is nothing to import but the implicit Init
    "plan_unresolved",  # an identifier the index does not know
    "plan_conflict",  # a plan that would load two definitions of one name
    "plan_error",  # the suggester failed or returned something that is not a module list
    "header_unsupported",  # `module`, `prelude`, modified imports or code on a header line
    "no_imports",  # the source imports nothing, so there is nothing to shrink
    "same_imports",  # the plan is the source's own import header
    "plan_import_not_allowed",  # the plan names a module the library profile does not allow
})
# The plan was compiled and failed in a way a missing import explains; the original source is
# verified once more. A genuine proof error of the same kind (a misspelled lemma) takes this path
# too, because the two cannot be told apart without the full imports.
RETRY_REASONS: Final = frozenset({
    "unknown_identifier",
    "unknown_namespace",
    "unknown_constant",
    "unknown_tactic",
    "import_unavailable",  # the module is not built into this verifier's workspace
})
STATUS_CODES: Final = frozenset(
    {APPLIED}
    | {DECLINED_PREFIX + reason for reason in DECLINE_REASONS}
    | {RETRIED_PREFIX + reason for reason in RETRY_REASONS}
)

_MODULE_NAME_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")
_IMPORT_LINE_RE: Final = re.compile(
    r"^[ \t]*import[ \t]+(?P<first>[^\s]+)(?P<more>(?:[ \t]+import[ \t]+[^\s]+)*)[ \t]*"
    r"(?:--.*)?$"
)
_UNSUPPORTED_HEADER_RE: Final = re.compile(
    r"^[ \t]*(?:(?:module|prelude)\b|(?:(?:public|meta)[ \t]+)+import\b|import[ \t]+all\b)"
)
# Messages Lean prints when an import (not the proof) is what is missing. Matched case-insensitively
# against the diagnostic's code and message; the first rule that matches names the reason.
_RETRY_RULES: Final = (
    ("import_unavailable", ("unknown module prefix", "object file", "unknown package")),
    ("unknown_namespace", ("unknown namespace",)),
    ("unknown_identifier", ("unknown identifier", "lean.unknownidentifier")),
    ("unknown_constant", ("unknown constant",)),
    ("unknown_tactic", ("unknown tactic",)),
)


@dataclass(frozen=True, slots=True)
class ImportSuggestion:
    """What a suggester knows about one source: modules to import, or why it has no plan."""

    imports: tuple[str, ...] = ()
    loaded_modules: int | None = None  # modules Lean loads for these imports, for the metrics
    declined: str | None = None  # one of ``DECLINE_REASONS``


class ImportSuggester(Protocol):
    def suggest(self, source: str) -> ImportSuggestion: ...


@dataclass(frozen=True, slots=True)
class PlannedSource:
    source: str | None  # the source to compile; ``None`` means verify the original
    status: str | None  # the ``DECLINED_PREFIX`` status when ``source`` is ``None``
    loaded_modules: int | None = None


@dataclass(frozen=True, slots=True)
class ImportPlanning:
    suggester: ImportSuggester

    def prepare(self, source: str, profile: LibraryProfile | None) -> PlannedSource:
        """The source to compile over a plan, or the reason there is none."""
        header = _parse_header(source)
        if isinstance(header, str):
            return _declined(header)
        try:
            suggestion = self.suggester.suggest(source)
        except Exception:  # noqa: BLE001 -- a broken index must never fail a verification.
            return _declined("plan_error")
        if suggestion.declined is not None:
            return _declined(
                suggestion.declined if suggestion.declined in DECLINE_REASONS else "plan_error"
            )
        imports = list(dict.fromkeys(
            module for module in suggestion.imports if module.split(".", 1)[0] != "Init"
        ))
        if any(_MODULE_NAME_RE.fullmatch(module) is None for module in imports):
            return _declined("plan_error")
        if not imports:
            return _declined("plan_empty")
        if frozenset(imports) == header.modules:
            return _declined("same_imports")
        planned = _rewrite_header(source, header, imports)
        if profile is not None and profile.import_violation(planned) is not None:
            return _declined("plan_import_not_allowed")
        return PlannedSource(planned, None, suggestion.loaded_modules)

    @staticmethod
    def retry_reason(result: VerificationResult) -> str | None:
        """Why a failed verification over a plan deserves one over the full imports, if it does."""
        if result.success:
            return None
        messages = [
            f"{diagnostic.code} {diagnostic.message}".lower()
            for diagnostic in result.diagnostics
            if diagnostic.severity == "error"
        ]
        for reason, markers in _RETRY_RULES:
            if any(marker in message for message in messages for marker in markers):
                return reason
        return None


def declined_status(reason: str) -> str:
    return DECLINED_PREFIX + reason


def retried_status(reason: str) -> str:
    return RETRIED_PREFIX + reason


def _declined(reason: str) -> PlannedSource:
    return PlannedSource(None, declined_status(reason))


@dataclass(frozen=True, slots=True)
class _Header:
    import_lines: tuple[int, ...]  # indexes of the lines that hold imports
    modules: frozenset[str]  # the modules those lines import


def _parse_header(source: str) -> _Header | str:
    """The import lines of the header, or the decline reason when it cannot be rewritten safely.

    The header is the run of blank lines, comments and plain ``import`` lines before the first
    command. Anything Lean 4.35 treats specially there is left alone: the verification then runs
    over the source exactly as written.
    """
    lines = source.splitlines(keepends=True)
    imports: list[int] = []
    modules: set[str] = set()
    depth = 0
    for index, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if depth > 0 or line.lstrip().startswith("/-"):
            depth = max(depth + line.count("/-") - line.count("-/"), 0)
            if depth == 0:
                rest = line.rsplit("-/", 1)[-1].strip()
                if rest and not rest.startswith("--"):
                    return "header_unsupported"
            continue
        if not line.strip() or line.lstrip().startswith("--"):
            continue
        if _UNSUPPORTED_HEADER_RE.match(line):
            return "header_unsupported"
        written = _IMPORT_LINE_RE.match(line)
        if written is not None:
            imports.append(index)
            modules.add(written.group("first"))
            modules.update(re.findall(r"import[ \t]+([^\s]+)", written.group("more")))
            continue
        break
    if not imports:
        return "no_imports"
    return _Header(tuple(imports), frozenset(modules))


def _rewrite_header(source: str, header: _Header, modules: Sequence[str]) -> str:
    """Replace the header imports by ``modules`` without moving any other line.

    The first import line carries every new import (Lean accepts several per line); the other
    import lines become empty, so line and column numbers after the header do not change.
    """
    lines = source.splitlines(keepends=True)
    first = header.import_lines[0]
    for index in header.import_lines:
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        text = " ".join(f"import {module}" for module in modules) if index == first else ""
        lines[index] = text + ending
    return "".join(lines)
