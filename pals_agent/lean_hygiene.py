"""Deterministic fixes for two first-attempt failures that are not mathematics.

Both were seen as the whole Lean error of an otherwise sound candidate (freshman-v1 dev_unseen):

* an ``import Mathlib.<Module>`` of a module that does not exist (a stale name such as
  ``Mathlib.Tactic.Omega``). ``import Mathlib`` already brings in every module, so the extra
  imports are redundant and are dropped.
* a scoped notation used without its namespace opened (``𝓝`` needs ``open Topology``): Lean reads
  the unknown symbol as an auto-bound variable and every use fails. The missing ``open`` is added.

The statement and the proof are untouched. Behind ``PALS_T2_SOURCE_HYGIENE_ENABLED`` (default off).
"""

from __future__ import annotations

import re

_MATHLIB_SUBMODULE_IMPORT = re.compile(r"^import\s+Mathlib\.\S+\s*$")
_ANY_IMPORT = re.compile(r"^import\s+\S+\s*$")
# Notation symbol -> the namespace whose ``open`` activates it.
_NOTATION_NAMESPACE: tuple[tuple[str, str], ...] = (
    ("𝓝", "Topology"),
    ("𝓝[", "Topology"),
    ("ℝ≥0∞", "ENNReal"),
    ("ℝ≥0", "NNReal"),
)


def _opens(lines: list[str], namespace: str) -> bool:
    word = re.compile(rf"(?<![\w.]){re.escape(namespace)}(?![\w.])")
    return any(
        line.lstrip().startswith("open") and word.search(line) is not None for line in lines
    )


def normalise_source_header(source: str) -> str:
    """The same source with redundant ``import Mathlib.*`` lines dropped and the opens that the
    notations it uses need. Idempotent; a source with nothing to fix is returned unchanged."""
    lines = source.split("\n")
    header_end = 0  # index after the last import line of the leading header
    for index, line in enumerate(lines):
        if _ANY_IMPORT.match(line.strip()):
            header_end = index + 1
        elif line.strip() and not line.lstrip().startswith("--"):
            break
    imports = lines[:header_end]
    if not imports:
        return source
    has_full = any(line.strip() == "import Mathlib" for line in imports)
    kept: list[str] = []
    replaced = False
    for line in imports:
        if _MATHLIB_SUBMODULE_IMPORT.match(line.strip()):
            if not has_full and not replaced:
                kept.append("import Mathlib")
                replaced = True
            continue
        kept.append(line)
    rest = lines[header_end:]
    body = "\n".join(rest)
    needed = []
    seen: set[str] = set()
    for symbol, namespace in _NOTATION_NAMESPACE:
        if namespace in seen or symbol not in body:
            continue
        seen.add(namespace)
        if not _opens(lines, namespace):
            needed.append(f"open {namespace}")
    # The opens go right after the imports; the blank line that followed them stays after.
    return "\n".join(kept + needed + rest)
