"""Map Stacks Project tags to the Mathlib declarations that carry them (source text only).

Mathlib marks a declaration that formalises a Stacks Project statement with
``@[stacks TAG]`` or ``@[stacks TAG "comment"]``. This lexical pass reads those attributes and the
declaration that follows, tracks ``namespace``/``section`` to qualify the name, and writes a small
JSON file (tag -> declarations: name, kind, module, line, statement text). Nothing is built or
elaborated, so a name is the qualified name the source implies, not a checked one.

    python -m tools.mathlib_index.extract_stacks_tags --mathlib DIR/Mathlib --commit SHA \\
        --out pals_agent/content_dictionaries/mathlib-stacks-tags-v1.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ATTR = re.compile(r"@\[([^\]]*?\bstacks\s+([0-9A-Z]{4})\b[^\]]*)\]")
_DECL = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*"
    r"(theorem|lemma|instance|def|abbrev|class|structure|inductive)\s*([^\s:({\[]*)"
)
_NAMESPACE = re.compile(r"^\s*namespace\s+([A-Za-z_][\w.']*)")
_SECTION = re.compile(r"^\s*section\b\s*([A-Za-z_][\w.']*)?")
_END = re.compile(r"^\s*end\b\s*([A-Za-z_][\w.']*)?\s*$")
MAX_STATEMENT = 600


def extract(root: Path) -> dict[str, list[dict[str, object]]]:
    tags: dict[str, list[dict[str, object]]] = {}
    for path in sorted(root.rglob("*.lean")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        module = "Mathlib." + ".".join(path.relative_to(root).with_suffix("").parts)
        stack: list[tuple[str, str]] = []  # (kind, name)
        pending: list[str] = []
        for number, line in enumerate(lines, start=1):
            match = _NAMESPACE.match(line)
            if match:
                stack.append(("namespace", match.group(1)))
                continue
            match = _SECTION.match(line)
            if match and not line.strip().startswith("--"):
                stack.append(("section", match.group(1) or ""))
                continue
            if _END.match(line) and stack:
                stack.pop()
                continue
            for attribute in _ATTR.finditer(line):
                pending.append(attribute.group(2))
            if not pending and "@[" not in line:
                continue
            declaration = _DECL.match(line)
            if declaration is None and pending:
                # The attribute sits on its own line; the declaration starts on a later one.
                continue
            if declaration is None:
                continue
            kind, name = declaration.group(1), declaration.group(2)
            namespace = ".".join(n for k, n in stack if k == "namespace")
            if not name:
                qualified = ""  # an anonymous instance has no name of its own
            elif name.startswith("_root_."):
                qualified = name.removeprefix("_root_.")
            else:
                qualified = f"{namespace}.{name}" if namespace else name
            statement = _statement(lines, number - 1)
            for tag in dict.fromkeys(pending):
                tags.setdefault(tag, []).append({
                    "name": qualified or None, "kind": kind, "module": module,
                    "line": number, "statement": statement,
                })
            pending = []
    return tags


def _statement(lines: list[str], start: int) -> str:
    text: list[str] = []
    for line in lines[start : start + 14]:
        if ":=" in line:
            text.append(line.split(":=", 1)[0])
            break
        if line.strip().startswith(("|", "where")):
            break
        text.append(line)
    return " ".join(" ".join(text).split())[:MAX_STATEMENT]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mathlib", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    tags = extract(args.mathlib)
    payload = {
        "schema": "pals.mathlib-stacks-tags.v1",
        "mathlib_commit": args.commit,
        "claims": "declarations carry the tag attribute in the source text; names are implied "
        "by namespaces, not elaborated",
        "tags": dict(sorted(tags.items())),
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(tags)} tags, {sum(len(v) for v in tags.values())} declarations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
