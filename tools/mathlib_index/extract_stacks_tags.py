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

_STACKS_IN_ATTRIBUTE = re.compile(r"\bstacks\s+([0-9A-Z]{4})\b")
_MODIFIERS = r"(?:(?:public|private|protected|noncomputable|nonrec|unsafe|partial|meta)\s+)*"
_DECL = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*" + _MODIFIERS +
    r"(theorem|lemma|instance|def|abbrev|class|structure|inductive|irreducible_def|opaque|axiom)"
    r"\b[ \t]*(?:\([^)]*\)[ \t]*)?([^\s:({\[]*)"
)
_PRIVATE = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:public|noncomputable|nonrec)\s+)*private\b")
_SCOPE_PREFIX = r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:public|noncomputable|meta|private|protected)\s+)*"
_NAMESPACE = re.compile(_SCOPE_PREFIX + r"namespace\s+([A-Za-z_][\w.']*)")
_SECTION = re.compile(_SCOPE_PREFIX + r"section\b[ \t]*([A-Za-z_][\w.']*)?")
_MUTUAL = re.compile(r"^\s*mutual\b")
_END = re.compile(r"^\s*end\b[ \t]*([A-Za-z_][\w.']*)?\s*$")
MAX_STATEMENT = 600
# An attribute that is not followed by a declaration within this many lines is dropped.
MAX_ATTRIBUTE_GAP = 8
_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def _blank_comments(text: str) -> str:
    """Replace comments by spaces/newlines (line numbers are kept)."""

    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return _LINE_COMMENT.sub(blank, _BLOCK_COMMENT.sub(blank, text))


def extract(root: Path) -> dict[str, list[dict[str, object]]]:
    tags: dict[str, list[dict[str, object]]] = {}
    for path in sorted(root.rglob("*.lean")):
        text = _blank_comments(path.read_text(encoding="utf-8", errors="replace"))
        lines = text.splitlines()
        module = "Mathlib." + ".".join(path.relative_to(root).with_suffix("").parts)
        stack: list[tuple[str, str]] = []  # (kind, name)
        pending: list[str] = []
        pending_since = 0
        number = 0
        while number < len(lines):
            line = lines[number]
            number += 1
            # Gather an attribute list that spans several lines.
            if "@[" in line and line.count("[") > line.count("]"):
                joined = line
                while number < len(lines) and joined.count("[") > joined.count("]"):
                    joined += " " + lines[number].strip()
                    number += 1
                line = joined
            if pending and number - pending_since > MAX_ATTRIBUTE_GAP:
                pending = []
            match = _NAMESPACE.match(line)
            if match:
                stack.append(("namespace", match.group(1)))
                continue
            match = _SECTION.match(line)
            if match:
                stack.append(("section", match.group(1) or ""))
                continue
            if _MUTUAL.match(line):
                stack.append(("section", ""))
                continue
            if _END.match(line):
                if stack:
                    stack.pop()
                continue
            for attribute in re.finditer(r"@\[[^\]]*\]", line):
                for tag in _STACKS_IN_ATTRIBUTE.findall(attribute.group(0)):
                    pending.append(tag)
                    pending_since = number
            if not pending:
                continue
            declaration = _DECL.match(line)
            if declaration is None:
                continue
            if _PRIVATE.match(line):
                pending = []  # a private name cannot be used from outside its file
                continue
            kind, name = declaration.group(1), declaration.group(2).rstrip(".")  # `w.{u}`
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
        "claims": "declarations whose attribute names the tag in the source text; names are "
        "implied by namespaces, not elaborated. Not every tag in Mathlib is covered (attributes on "
        "`attribute [...]` lines and on `proof_wanted` are skipped, private names are dropped)",
        "tags": dict(sorted(tags.items())),
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(tags)} tags, {sum(len(v) for v in tags.values())} declarations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
