"""Compile a source subtree of an already-built Mathlib package into a scratch directory.

    python -m tools.library_index.compile_inventory --package DIR --workspace-packages DIR \
        --toolchain-bin DIR --scratch DIR --roots Archive Counterexamples --out results.json

Runs ONE ``lean`` process at a time, in import order, with the shared package's built ``.olean``
files on ``LEAN_PATH`` and every output (``.olean``/``.ilean``) written under ``--scratch``. The
package and its build directory are only read. The build options are the ones Mathlib's lakefile
gives ``Archive`` and ``Counterexamples``. Per file it records exit status, wall time, user/system
CPU, peak resident memory (``/usr/bin/time -l``), and counts of errors, warnings and ``sorry``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

_IMPORT = re.compile(r"^(?:public\s+|meta\s+)*import\s+(?:all\s+)?(\S+)", re.MULTILINE)
# Mathlib's `mathlibLeanOptions` for `lean_lib Archive` / `lean_lib Counterexamples`.
LEAN_OPTIONS = ("-DautoImplicit=false", "-Dpp.unicode.fun=true", "-DmaxSynthPendingDepth=3")


def module_files(package: Path, roots: list[str]) -> dict[str, Path]:
    return {
        ".".join(path.relative_to(package).with_suffix("").parts): path
        for root in roots
        for path in sorted((package / root).rglob("*.lean"))
    }


def import_order(files: dict[str, Path]) -> list[str]:
    """Modules ordered so that a module follows every in-subtree module it imports."""
    deps = {
        module: [m for m in _IMPORT.findall(path.read_text(errors="replace")) if m in files]
        for module, path in files.items()
    }
    ordered: list[str] = []
    state: dict[str, int] = {}

    def visit(module: str) -> None:
        if state.get(module) == 2:
            return
        if state.get(module) == 1:
            raise SystemExit(f"import cycle at {module}")
        state[module] = 1
        for dep in sorted(deps[module]):
            visit(dep)
        state[module] = 2
        ordered.append(module)

    for module in sorted(files):
        visit(module)
    return ordered


def _rusage(stderr: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for key, pattern in (
        ("max_rss_bytes", r"(\d+)\s+maximum resident set size"),
        ("user_s", r"([\d.]+)\s+user"),
        ("sys_s", r"([\d.]+)\s+sys"),
        ("real_s", r"([\d.]+)\s+real"),
    ):
        match = re.search(pattern, stderr)
        if match:
            found[key] = float(match.group(1))
    return found


def compile_one(
    module: str, path: Path, *, package: Path, lean: Path, env: dict[str, str],
    scratch: Path, timeout: int,
) -> dict[str, Any]:
    out = scratch / "lib" / (module.replace(".", "/") + ".olean")
    out.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "/usr/bin/time", "-l", "nice", "-n", "10", str(lean), *LEAN_OPTIONS,
        f"--root={package}", "-o", str(out), "-i", str(out.with_suffix(".ilean")), str(path),
    ]
    started = time.perf_counter()
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, env=env, cwd=package,
        )
        status, code = ("ok" if done.returncode == 0 else "error"), done.returncode
        stdout, stderr = done.stdout, done.stderr
    except subprocess.TimeoutExpired as expired:
        status, code = "timeout", -1
        stdout = (expired.stdout or b"").decode() if isinstance(expired.stdout, bytes) else ""
        stderr = (expired.stderr or b"").decode() if isinstance(expired.stderr, bytes) else ""
    wall = time.perf_counter() - started
    messages = stdout + "\n" + stderr
    return {
        "module": module,
        "path": str(path.relative_to(package)),
        "status": status,
        "exit_code": code,
        "wall_s": round(wall, 2),
        **{k: v for k, v in _rusage(stderr).items() if k != "real_s"},
        "errors": len(re.findall(r": error:", messages)),
        "warnings": len(re.findall(r": warning:", messages)),
        "sorry_warnings": len(re.findall(r"declaration uses [`']sorry[`']", messages)),
        "first_error": next(
            (line[:300] for line in messages.splitlines() if ": error:" in line), None
        ),
        "olean_bytes": out.stat().st_size if out.exists() else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, required=True, help="the Mathlib package dir")
    parser.add_argument("--workspace-packages", type=Path, required=True,
                        help="workspace .lake/packages (built oleans are read from here)")
    parser.add_argument("--toolchain-bin", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--roots", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--only", nargs="*", help="compile just these modules (and no others)")
    args = parser.parse_args()

    package = args.package.resolve()
    scratch = args.scratch.resolve()
    if str(scratch).startswith(str(args.workspace_packages.resolve())):
        raise SystemExit("scratch must be outside the shared workspace")
    libs = [
        str(p / ".lake" / "build" / "lib" / "lean")
        for p in sorted(args.workspace_packages.iterdir()) if (p / ".lake").is_dir()
    ]
    env = {**os.environ, "LEAN_PATH": os.pathsep.join([*libs, str(scratch / "lib")])}
    files = module_files(package, args.roots)
    order = [m for m in import_order(files) if not args.only or m in args.only]
    lean = args.toolchain_bin / "lean"
    results: list[dict[str, Any]] = []
    for index, module in enumerate(order, 1):
        result = compile_one(
            module, files[module], package=package, lean=lean, env=env, scratch=scratch,
            timeout=args.timeout,
        )
        results.append(result)
        print(f"[{index}/{len(order)}] {module} {result['status']} {result['wall_s']}s", flush=True)
        args.out.write_text(json.dumps(results, indent=1))
    ok = sum(r["status"] == "ok" for r in results)
    print(f"done: {ok}/{len(results)} ok", flush=True)


if __name__ == "__main__":
    main()
