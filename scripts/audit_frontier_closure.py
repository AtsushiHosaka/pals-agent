"""Screen the StacksFrontier modules a verifier image will build, before building them.

Frontier is AI-generated and unreviewed, and importing a module runs its `initialize` blocks and
adopts its notation and macros. This applies the verifier's own source policy (no metaprogramming,
native evaluation, `unsafe`, `implemented_by`, ... ) to every Stacks module in the import closure
of the requested modules. Documentation attributes (`stacks`, `sga`, ...) are benign and removed
first. Exit status 1 lists the files that must not be built.

    python scripts/audit_frontier_closure.py <Stacks package dir> <Module> [<Module> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pals_agent.lean_source_policy import find_source_violation

_IMPORT = re.compile(r"^(?:public\s+)?(?:meta\s+)?import\s+(?:all\s+)?(\S+)", re.MULTILINE)
_BENIGN_ATTRIBUTE = re.compile(
    r'\b(?:stacks_fixed|stacks|sga|ega|kerodon)\b(?:[ \t]+[A-Za-z0-9]{4})?(?:[ \t]+"[^"\n]*")*'
)


def closure(package: Path, roots: list[str]) -> dict[str, str]:
    """Return {module: source} for every Stacks module reachable from ``roots``."""
    found: dict[str, str] = {}
    todo = list(roots)
    while todo:
        module = todo.pop()
        if module in found or module.split(".", 1)[0] not in {"StacksCore", "StacksFrontier"}:
            continue
        path = package / (module.replace(".", "/") + ".lean")
        found[module] = path.read_text(encoding="utf-8")
        todo.extend(_IMPORT.findall(found[module]))
    return found


def screened(source: str) -> str:
    """Remove the module-system header and benign attributes the candidate policy would reject."""
    text = re.sub(r"^module[ \t]*$", "", source, flags=re.MULTILINE)
    text = _IMPORT.sub("", text)
    text = re.sub(r"@\[expose\]\s+public\s+", "", text)
    return re.sub(r"@\[([^\]]*)\]", _without_benign_attributes, text)


def _without_benign_attributes(match: re.Match[str]) -> str:
    kept = [
        item.strip()
        for item in _BENIGN_ATTRIBUTE.sub("", match.group(1)).split(",")
        if item.strip()
    ]
    return f"@[{', '.join(kept)}]" if kept else ""


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    modules = closure(Path(argv[1]), argv[2:])
    bad = {
        name: violation
        for name, source in sorted(modules.items())
        # `StacksCore` is human-reviewed and its tag attributes are metaprograms by nature.
        if name.startswith("StacksFrontier.")
        and (violation := find_source_violation(screened(source))) is not None
    }
    print(f"{len(modules)} Stacks modules in the closure of {len(argv) - 2} requested")
    for name, violation in bad.items():
        print(f"REJECT {name}: {violation.code}: {violation.message}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
