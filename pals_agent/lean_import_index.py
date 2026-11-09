"""The import index as an import suggester (see ``pals_agent.lean_import_plan``).

``tools.stacks_index.import_index`` knows, from source text alone, which module defines each
declaration of Lean, Mathlib, StacksCore and the Stacks Frontier, and which modules import which.
This adapter turns the constants a source's statements name into the few modules to import. It
reads statements only (proofs are replaced by ``sorry`` first), and it declines, instead of
guessing, whenever the source goes beyond what the index can resolve.

``tools`` is a development package that is not part of the wheel, so it is imported lazily: a
verifier that enables planning must ship it, and one that cannot import it refuses to start.
"""

from __future__ import annotations

import importlib
import json
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from pals_agent.lean_import_plan import ImportPlanning, ImportSuggestion
from pals_agent.lean_profiles import LibraryProfile
from pals_agent.lean_source_policy import statement_reference, strip_lean_comments_and_strings

_COMMAND_START: Final = re.compile(
    r"^(?:@\[[^\]\n]*\][ \t]*)?(?:(?:private|protected|noncomputable|unsafe|partial|nonrec)[ \t]+)*"
    r"(?P<keyword>[A-Za-z_]+)",
    re.MULTILINE,
)
_STATEMENT_KEYWORDS: Final = frozenset({"theorem", "lemma", "example"})
_SCOPE_KEYWORDS: Final = frozenset({
    "universe", "namespace", "section", "end", "set_option", "open", "export",
})
_COMMAND_KEYWORDS: Final = _STATEMENT_KEYWORDS | _SCOPE_KEYWORDS | frozenset({
    "def", "abbrev", "instance", "structure", "class", "inductive", "variable",
})
_MODULE_NAME: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")


class ImportPlanConfigurationError(ValueError):
    """Import planning was enabled with an index this verifier cannot use. Startup refuses."""


class IndexImportSuggester:
    """Suggest imports for a source from an ``ImportIndex`` (one index, calls are serialized)."""

    def __init__(self, index: Any, base_modules: Sequence[str] = ()) -> None:
        self._index = index
        self._base_modules = tuple(base_modules)
        self._lock = threading.Lock()

    def suggest(self, source: str) -> ImportSuggestion:
        reference = statement_reference(source)
        if reference is None:
            return ImportSuggestion(declined="statement_unreadable")
        statements = _statements(reference)
        if statements is None:
            return ImportSuggestion(declined="local_definitions")
        shape_of = importlib.import_module("tools.stacks_index.shape")
        identifiers: list[str] = []
        for statement in statements:
            shape = shape_of.query_shape(statement)
            identifiers += [*shape["conclusion_constants"], *shape["hypothesis_constants"]]
        # `open`/`namespace` lines are not part of the reference; read them from the written source.
        written = strip_lean_comments_and_strings(source)
        with self._lock:
            opens, namespaces = self._index.scope_of(written)
            plan = self._index.plan(
                identifiers, opens, namespaces, extra_modules=self._base_modules
            )
        if any(_names_a_constant(name) for name in plan.unresolved):
            return ImportSuggestion(declined="plan_unresolved")
        if plan.conflicts:
            return ImportSuggestion(declined="plan_conflict")
        return ImportSuggestion(imports=tuple(plan.imports), loaded_modules=plan.loaded_size)


def _names_a_constant(identifier: str) -> bool:
    """Whether an identifier the index cannot place is likely a constant, not a field access.

    The lexical shape cannot tell ``x.level`` (a field of a variable, whose name no index entry
    carries) from a constant. A qualified or capitalised name is taken for a constant the index does
    not know, and the plan is declined; a bare lowercase tail is left to the compile and its retry.
    """
    return "." in identifier or identifier[:1].isupper()


def _statements(reference: str) -> list[str] | None:
    """The theorem statements of a reference source, or ``None`` if it has other declarations.

    A ``def``, ``structure`` or ``instance`` is the user's own object, whose body the index would
    have to follow; ``universe``/``namespace``/``section``/``open`` lines carry no constants.
    """
    starts = [
        (match.start(), match.group("keyword"))
        for match in _COMMAND_START.finditer(reference)
        if match.group("keyword") in _COMMAND_KEYWORDS
    ]
    ends = [start for start, _ in starts[1:]] + [len(reference)]
    statements: list[str] = []
    for (start, keyword), end in zip(starts, ends, strict=False):
        if keyword in _SCOPE_KEYWORDS:
            continue
        if keyword not in _STATEMENT_KEYWORDS:
            return None
        statements.append(reference[start:end].strip())
    return statements


def build_import_planning(
    index_path: Path, profile: LibraryProfile, base_modules: Sequence[str] = ()
) -> ImportPlanning:
    """Load the index and bind it to ``profile``; refuse anything that does not match its pins."""
    pins = dict(profile.pins)
    if "stacks" not in pins or "mathlib" not in pins:
        raise ImportPlanConfigurationError(
            "import planning needs a library profile that pins the Stacks workspace"
        )
    try:
        index_module = importlib.import_module("tools.stacks_index.import_index")
    except ImportError as error:
        raise ImportPlanConfigurationError("the import index package is not installed") from error
    if not index_path.is_file():
        raise ImportPlanConfigurationError("the import index file was not found")
    try:
        index = index_module.ImportIndex(index_path, check_same_thread=False)
        provenance = json.loads(index.manifest()["provenance"])
    except Exception as error:  # noqa: BLE001 -- any unreadable index is a configuration error.
        raise ImportPlanConfigurationError("the import index is unreadable") from error
    if (
        provenance.get("stacks_commit") != pins["stacks"]
        or provenance.get("mathlib_commit") != pins["mathlib"]
    ):
        raise ImportPlanConfigurationError(
            f"the import index was not built from the revisions pinned by {profile.name}"
        )
    for module in base_modules:
        if _MODULE_NAME.fullmatch(module) is None or module not in index.module_id:
            raise ImportPlanConfigurationError("a base module of the import plan is not indexed")
    return ImportPlanning(IndexImportSuggester(index, base_modules))
