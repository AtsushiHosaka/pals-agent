from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_frontier_closure.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_frontier_closure", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / (name.replace(".", "/") + ".lean")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


_HEADER = "module\n\npublic import Mathlib.Algebra.Group.Basic\n"


def test_a_plain_lemma_with_documentation_tags_passes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    audit = _load()
    package = _package(
        tmp_path,
        {
            "StacksFrontier.A": _HEADER
            + "public import StacksCore.Tactic.StacksAttribute\n\n@[expose] public section\n\n"
            '@[stacks 01QU "closed immersions are separated", simp]\n'
            "theorem a : True := trivial\n",
            "StacksCore.Tactic.StacksAttribute": _HEADER + "macro \"x\" : term => `(1)\n",
        },
    )

    assert audit.main(["x", str(package), "StacksFrontier.A"]) == 0
    assert "2 Stacks modules" in capsys.readouterr().out


@pytest.mark.parametrize(
    "body",
    [
        "notation3 \"∑ᶠ\" => id\n",
        "macro \"foo\" : term => `(1)\n",
        "initialize registerTraceClass `x\n",
        "theorem a : True := by native_decide\n",
        "@[implemented_by foo] def a := 1\n",
        "unsafe def a := 1\n",
    ],
)
def test_a_frontier_module_with_metaprogramming_stops_the_build(
    tmp_path: Path, body: str, capsys  # type: ignore[no-untyped-def]
) -> None:
    audit = _load()
    package = _package(
        tmp_path,
        {
            "StacksFrontier.A": _HEADER
            + "public import StacksFrontier.B\n\ntheorem ok : True := trivial\n",
            "StacksFrontier.B": _HEADER + "\n" + body,
        },
    )

    assert audit.main(["x", str(package), "StacksFrontier.A"]) == 1
    assert "REJECT StacksFrontier.B" in capsys.readouterr().out


def test_modules_outside_stacks_are_not_followed(tmp_path: Path) -> None:
    audit = _load()
    package = _package(
        tmp_path,
        {"StacksFrontier.A": _HEADER + "public import Mathlib.Does.Not.Exist\n"},
    )

    assert list(audit.closure(package, ["StacksFrontier.A"])) == ["StacksFrontier.A"]
