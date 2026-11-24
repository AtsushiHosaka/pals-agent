#!/usr/bin/env python3
"""Select the test files a change can affect, from the repository's import graph (pals#487).

Reads changed paths (arguments, or ``--git-diff BASE``), builds the import graph of the
project's own Python files with ``ast`` and prints the test files that import a changed
module, directly or through other modules, one per line. Standard library only.

The selection errs toward more tests. It prints the single line ``ALL`` when the change can
affect tests in ways an import graph cannot see: workflow, dependency pin, fixture, conftest,
qualification-manifest, Lean workspace, container or script-gate changes, any changed file
that is neither Python nor documentation, or a changed Python file outside the graph. A
string that equals a project module name counts as an import, so ``importlib.import_module``
with a literal is followed. Documentation-only changes select nothing.

This is advisory: the full regression stays the gate. See ``--help``.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ALL = "ALL"
ROOTS = ("pals_agent", "scripts", "tools", "tests")
_ALL_PREFIXES = (
    ".github/",
    "tests/fixtures/",
    "tests/qualification/",
    "lean-workspace/",
    "lean-workspaces/",
    "lean-indexes/",
    "docker/",
    "Dockerfile",
)
_ALL_NAMES = frozenset({"pyproject.toml", "uv.lock", "conftest.py", "agent_regression_gate.py"})
_DOC_PREFIXES = ("docs/", "history/")
_DOC_SUFFIXES = (".md", ".rst", ".txt")
_DOC_NAMES = frozenset({"LICENSE"})


def module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def project_files(root: Path) -> dict[str, Path]:
    """Module name -> repository-relative path, for every Python file under the roots."""
    modules: dict[str, Path] = {}
    for top in ROOTS:
        for path in sorted((root / top).rglob("*.py")) if (root / top).is_dir() else []:
            if ".venv" in path.parts:
                continue
            relative = path.relative_to(root)
            modules[module_name(relative)] = relative
    return modules


def _aliases(modules: dict[str, Path]) -> dict[str, set[str]]:
    """Short names that scripts and tests import after putting their directory on ``sys.path``.

    ``scripts/eval/extract_dev_split.py`` is ``scripts.eval.extract_dev_split`` in the graph but
    ``extract_dev_split`` to a test that adds ``scripts/eval`` to ``sys.path``. Every module under
    ``scripts`` or ``tools`` is also known by each trailing part of its dotted name.
    """
    aliases: dict[str, set[str]] = {}
    for name in modules:
        parts = name.split(".")
        if parts[0] not in ("scripts", "tools") or len(parts) < 2:
            continue
        for start in range(1, len(parts)):
            aliases.setdefault(".".join(parts[start:]), set()).add(name)
    return aliases


def _resolve(
    name: str, modules: dict[str, Path], aliases: dict[str, set[str]] | None = None
) -> set[str]:
    """The project modules a dotted name refers to, with every parent package."""
    found: set[str] = set()
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in modules:
            found.add(candidate)
        if aliases and candidate in aliases:
            found |= aliases[candidate]
    return found


def imports_of(
    path: Path,
    current: str,
    modules: dict[str, Path],
    root: Path,
    aliases: dict[str, set[str]] | None = None,
    basenames: dict[str, set[str]] | None = None,
) -> set[str]:
    try:
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    is_package = path.name == "__init__.py"
    package = current if is_package else current.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _resolve(alias.name, modules, aliases)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".") if package else []
                keep = len(base_parts) - (node.level - 1)
                base = ".".join(base_parts[: max(keep, 0)])
                target = f"{base}.{node.module}" if node.module and base else (node.module or base)
            else:
                target = node.module or ""
            if target:
                found |= _resolve(target, modules, aliases)
                for alias in node.names:
                    found |= _resolve(f"{target}.{alias.name}", modules, aliases)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in modules:
                found.add(node.value)
            elif basenames and node.value.endswith(".py"):
                # A file loaded by path (``spec_from_file_location``, ``runpy``, a subprocess).
                found |= basenames.get(node.value.rsplit("/", 1)[-1], set())
    found.discard(current)
    return found


def build_graph(root: Path) -> tuple[dict[str, Path], dict[str, set[str]]]:
    """Return the module table and the reverse graph (module -> modules that import it)."""
    modules = project_files(root)
    aliases = _aliases(modules)
    basenames: dict[str, set[str]] = {}
    for name, path in modules.items():
        basenames.setdefault(path.name, set()).add(name)
    reverse: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        for imported in imports_of(path, name, modules, root, aliases, basenames):
            reverse[imported].add(name)
    return modules, reverse


def _classify(path: str) -> str:
    if path.startswith(_ALL_PREFIXES) or path.rsplit("/", 1)[-1] in _ALL_NAMES:
        return "all"
    if path.endswith(".py"):
        return "python"
    if path.startswith(_DOC_PREFIXES) or path.endswith(_DOC_SUFFIXES) or path in _DOC_NAMES:
        return "doc"
    return "all"


def is_test_file(path: Path) -> bool:
    return path.parts[0] == "tests" and path.name.startswith("test_") and path.suffix == ".py"


def select(changed: list[str], root: Path) -> list[str]:
    """Test files affected by the changed paths, or ``["ALL"]``."""
    modules, reverse = build_graph(root)
    by_path = {path.as_posix(): name for name, path in modules.items()}
    seeds: set[str] = set()
    for raw in changed:
        path = raw.strip().removeprefix("./")
        if not path:
            continue
        kind = _classify(path)
        if kind == "all":
            return [ALL]
        if kind == "python":
            if path not in by_path:
                return [ALL]  # Deleted or unknown: importers cannot be recovered from the graph.
            seeds.add(by_path[path])
    reached = set(seeds)
    queue = list(seeds)
    while queue:
        for importer in reverse[queue.pop()]:
            if importer not in reached:
                reached.add(importer)
                queue.append(importer)
    return sorted(modules[name].as_posix() for name in reached if is_test_file(modules[name]))


def _git_changed(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{base}...HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="changed paths, relative to the root")
    parser.add_argument("--git-diff", metavar="BASE", help="use `git diff BASE...HEAD`")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    changed = list(args.paths)
    if args.git_diff:
        changed += _git_changed(args.git_diff)
    for line in select(changed, args.root):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
