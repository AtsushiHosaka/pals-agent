"""Parse a Lean 4 module header: the ``module`` marker and the ``import`` lines.

Source-only and lexical. Comments are masked with the same routine the declaration extractor uses,
so an ``import`` inside a doc comment is not an edge. Flags follow the Lean 4.35 module system:
``public import`` re-exports, ``meta import`` is for compile-time code, ``import all`` exposes
private declarations. A file without the ``module`` marker is a legacy file: every import is
transitively visible to its importers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extract import mask_source

_MODULE_ATOM = r"[A-Za-z_À-￿«][A-Za-z0-9_'!?À-￿«».]*"
_MODULE_MARK = re.compile(r"\s*module\b")
_PRELUDE = re.compile(r"\s*prelude\b")
_IMPORT = re.compile(
    r"\s*(?P<pre>(?:(?:public|meta|private)\s+)*)import\s+(?P<all>all\s+)?(?P<name>"
    + _MODULE_ATOM
    + r")"
)


@dataclass(frozen=True, slots=True)
class ImportEdge:
    imported: str
    public: bool  # re-exported to importers (always true in a legacy file)
    meta: bool
    all: bool


@dataclass(slots=True)
class Header:
    module_system: bool = False  # the file starts with ``module``
    prelude: bool = False
    imports: list[ImportEdge] = field(default_factory=list)


_PREFIX_CHARS = 16384


def parse_header(text: str) -> Header:
    """Return the header of one Lean source file. Stops at the first non-header command.

    Only the leading part of the file is masked; the whole file is used if the header reaches
    the end of that part (a very long license block or import list).
    """
    header, end = _parse(text[:_PREFIX_CHARS])
    if end >= _PREFIX_CHARS - 256 and len(text) > _PREFIX_CHARS:
        header, _ = _parse(text)
    return header


def _parse(text: str) -> tuple[Header, int]:
    masked, _ = mask_source(text)
    header = Header()
    pos = 0
    match = _MODULE_MARK.match(masked, pos)
    if match:
        header.module_system = True
        pos = match.end()
    match = _PRELUDE.match(masked, pos)
    if match:
        header.prelude = True
        pos = match.end()
    while True:
        match = _IMPORT.match(masked, pos)
        if match is None:
            break
        prefix = match.group("pre").split()
        header.imports.append(
            ImportEdge(
                imported=match.group("name").strip("."),
                public=("public" in prefix) or not header.module_system,
                meta="meta" in prefix,
                all=match.group("all") is not None,
            )
        )
        pos = match.end()
    return header, pos
