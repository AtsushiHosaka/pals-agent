"""The manifest-driven declaration index (tools/library_index) on a tiny synthetic library."""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from pals_agent.lean_profiles import MANIFESTS
from tools.library_index.build import build

_SOURCE = """\
import Mathlib

/-- A toy statement. -/
theorem toy_add_zero (n : Nat) : n + 0 = n := by simp

@[stacks 00DJ "demo"]
lemma toy_zero_add (n : Nat) : 0 + n = n := by simp

def toyDouble (n : Nat) : Nat := n + n
"""


def _tree(tmp_path: Path) -> Path:
    source = tmp_path / "src"
    (source / "Archive").mkdir(parents=True)
    (source / "Counterexamples").mkdir()
    (source / "Archive" / "Toy.lean").write_text(_SOURCE)
    (source / "Counterexamples" / "Other.lean").write_text("theorem other : True := trivial\n")
    return source


def _rows(path: Path) -> list[dict]:  # type: ignore[type-arg]
    with gzip.open(path, "rt") as handle:
        return [json.loads(line) for line in handle.read().splitlines()]


def _manifest():  # noqa: ANN202
    return next(m for m in MANIFESTS if m.name == "mathlib-archive")


def test_index_rows_carry_name_kind_statement_module_path_line_and_generic_trust(
    tmp_path: Path,
) -> None:
    result = build(
        _manifest(), _tree(tmp_path), tmp_path / "out", verify_commit=False,
        library_commit=_manifest().commit,
    )
    assert result["declarations"] == 4
    assert result["by_trust"] == {"kernel-checked-unreviewed": 4}
    assert result["by_layer"] == {"Archive": 3, "Counterexamples": 1}
    assert result["license"] == "Apache-2.0" and result["commit"] == _manifest().commit
    rows = _rows(tmp_path / "out" / "decls.jsonl.gz")
    by_name = {r["name"]: r for r in rows}
    first = by_name["toy_add_zero"]
    assert (first["module"], first["path"], first["kind"]) == (
        "Archive.Toy", "Archive/Toy.lean", "theorem",
    )
    assert first["line"] == 4 and "n + 0 = n" in first["statement"] and first["has_doc"]
    with sqlite3.connect(tmp_path / "out" / "index.sqlite") as db:
        hit = db.execute(
            "SELECT name FROM decl_fts WHERE decl_fts MATCH 'toy_add_zero'"
        ).fetchall()
    assert hit == [("toy_add_zero",)]


def test_the_index_is_deterministic(tmp_path: Path) -> None:
    source = _tree(tmp_path)
    kwargs = {"verify_commit": False, "library_commit": _manifest().commit}
    a = build(_manifest(), source, tmp_path / "a", **kwargs)
    b = build(_manifest(), source, tmp_path / "b", **kwargs)
    assert a["decls_jsonl_gz_sha256"] == b["decls_jsonl_gz_sha256"]


def test_stacks_tags_are_an_optional_plugin(tmp_path: Path) -> None:
    source = _tree(tmp_path)
    kwargs = {"verify_commit": False, "library_commit": _manifest().commit}
    build(_manifest(), source, tmp_path / "plain", **kwargs)
    build(_manifest(), source, tmp_path / "tags", plugin="stacks-tags", **kwargs)

    def tags(out: str) -> dict[str, list[str]]:
        return {r["name"]: r["tags"] for r in _rows(tmp_path / out / "decls.jsonl.gz")}

    assert tags("plain")["toy_zero_add"] == []
    assert tags("tags")["toy_zero_add"] == ["00DJ"]


def test_a_source_at_another_commit_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        build(_manifest(), _tree(tmp_path), tmp_path / "out")  # not a git checkout


def test_the_committed_archive_index_matches_its_manifest_digest() -> None:
    import hashlib

    manifest = _manifest()
    root = Path(__file__).resolve().parents[1]
    assert manifest.index_path is not None and manifest.index_sha256 is not None
    data = (root / manifest.index_path).read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest.index_sha256
    written = json.loads((root / "lean-indexes/mathlib-archive/manifest.json").read_text())
    assert written["decls_jsonl_gz_sha256"] == manifest.index_sha256
    assert written["commit"] == manifest.commit and written["license"] == manifest.license_spdx
    assert {r["trust"] for r in _rows(root / manifest.index_path)} == {"kernel-checked-unreviewed"}
