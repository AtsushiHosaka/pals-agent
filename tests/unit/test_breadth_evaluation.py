"""Input and evidence-boundary checks; these tests do not claim Lean compilation."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pals_agent.breadth_evaluation import (
    CORPUS_SCHEMA,
    environment_binding,
    evaluate,
    load_corpus,
)

SOURCE = """import Mathlib

theorem composite_injective {A B C : Type} (f : A → B) (g : B → C)
    (h : Function.Injective (g ∘ f)) : Function.Injective f := by
  intro x y hxy
  apply h
  change g (f x) = g (f y)
  rw [hxy]
"""


@pytest.fixture
def payload(tmp_path: Path) -> dict[str, Any]:
    (tmp_path / "proof.lean").write_text(SOURCE)
    return {
        "schema_version": CORPUS_SCHEMA,
        "toolchain": {
            "lean_toolchain": "leanprover/lean4:v4.32.0-rc1",
            "mathlib_revision": "a" * 40,
        },
        "cases": [
            {
                "id": "linear-composition",
                "family_id": "linear-algebra",
                "theorem_name": "composite_injective",
                "source_path": "proof.lean",
                "statement": "Injectivity of a composite forces injectivity of its first map.",
                "assumptions": ["f:A→B and g:B→C are maps; g∘f is injective."],
                "proof_outline": ["Apply composite injectivity to equality after applying g."],
                "hard_negative": {
                    "statement": (
                        "Injectivity of a composite forces its second map to be injective."
                    ),
                    "counterexample": ("Include a singleton into two points; g is constant."),
                },
                "provenance": {"kind": "original", "license": "Apache-2.0"},
            }
        ],
    }


def save(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload))
    return path


def test_load_binds_exact_corpus_and_source(tmp_path: Path, payload: dict[str, Any]) -> None:
    corpus = load_corpus(save(tmp_path, payload))
    assert corpus.cases[0].source == SOURCE
    assert len(corpus.sha256) == 64 and len(corpus.cases[0].source_sha256 or "") == 64
    (tmp_path / "proof.lean").write_text(SOURCE + "\n")
    changed = load_corpus(corpus.path)
    assert changed.sha256 == corpus.sha256
    assert changed.cases[0].source_sha256 != corpus.cases[0].source_sha256


@pytest.mark.parametrize(
    "field", ["id", "family_id", "statement", "theorem_name", "assumptions", "proof_outline"]
)
def test_missing_metadata_rejected(tmp_path: Path, payload: dict[str, Any], field: str) -> None:
    del payload["cases"][0][field]
    with pytest.raises(ValueError):
        load_corpus(save(tmp_path, payload))


@pytest.mark.parametrize("field", ["statement", "counterexample"])
def test_missing_negative_rejected(tmp_path: Path, payload: dict[str, Any], field: str) -> None:
    payload["cases"][0]["hard_negative"][field] = " "
    with pytest.raises(ValueError):
        load_corpus(save(tmp_path, payload))


@pytest.mark.parametrize("field", ["kind", "license"])
def test_missing_provenance_rejected(tmp_path: Path, payload: dict[str, Any], field: str) -> None:
    payload["cases"][0]["provenance"][field] = ""
    with pytest.raises(ValueError):
        load_corpus(save(tmp_path, payload))


def test_duplicate_id_rejected(tmp_path: Path, payload: dict[str, Any]) -> None:
    payload["cases"].append(copy.deepcopy(payload["cases"][0]))
    with pytest.raises(ValueError, match="duplicate case"):
        load_corpus(save(tmp_path, payload))


def test_duplicate_json_key_rejected(tmp_path: Path) -> None:
    path = tmp_path / "corpus.json"
    path.write_text('{"schema_version":"one","schema_version":"two"}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        load_corpus(path)


@pytest.mark.parametrize("name", ["../outside.lean", "/tmp/outside.lean", "proof.txt"])
def test_escaping_or_wrong_source_rejected(
    tmp_path: Path, payload: dict[str, Any], name: str
) -> None:
    payload["cases"][0]["source_path"] = name
    with pytest.raises(ValueError, match="relative .lean"):
        load_corpus(save(tmp_path, payload))


def test_symlink_source_rejected(tmp_path: Path, payload: dict[str, Any]) -> None:
    (tmp_path / "alias.lean").symlink_to(tmp_path / "proof.lean")
    payload["cases"][0]["source_path"] = "alias.lean"
    with pytest.raises(ValueError, match="symlinks"):
        load_corpus(save(tmp_path, payload))


@pytest.mark.parametrize(
    "source", ["", "-- theorem composite_injective : True := by trivial\n", "import Mathlib\n"]
)
def test_empty_or_unrelated_source_rejected(
    tmp_path: Path, payload: dict[str, Any], source: str
) -> None:
    (tmp_path / "proof.lean").write_text(source)
    with pytest.raises(ValueError):
        load_corpus(save(tmp_path, payload))


def test_pending_requires_explicit_status(tmp_path: Path, payload: dict[str, Any]) -> None:
    payload["cases"][0]["source_path"] = None
    with pytest.raises(ValueError, match="explicitly authored_not_compiled"):
        load_corpus(save(tmp_path, payload))
    payload["cases"][0]["status"] = "authored_not_compiled"
    assert load_corpus(save(tmp_path, payload)).cases[0].source is None


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def project_fixture(tmp_path: Path, payload: dict[str, Any]) -> Path:
    """A Git pin-validation fixture, not a real Mathlib/compiler environment."""
    project = tmp_path / "project"
    mathlib = project / ".lake/packages/mathlib"
    mathlib.mkdir(parents=True)
    git(mathlib, "init", "--quiet")
    (mathlib / "Tracked.lean").write_text("-- validation fixture\n")
    git(mathlib, "add", "Tracked.lean")
    git(
        mathlib,
        "-c",
        "user.name=Unit Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    payload["toolchain"]["mathlib_revision"] = git(mathlib, "rev-parse", "HEAD")
    (project / "lean-toolchain").write_text(payload["toolchain"]["lean_toolchain"] + "\n")
    (project / "lakefile.lean").write_text("-- Lake configuration validation fixture\n")
    (project / "lake-manifest.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "name": "mathlib",
                        "type": "git",
                        "rev": payload["toolchain"]["mathlib_revision"],
                    }
                ]
            }
        )
    )
    return project


def test_manifest_and_actual_git_pins_checked(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    corpus = load_corpus(save(tmp_path, payload))
    binding = environment_binding(corpus, project)
    assert binding["mathlib_revision"] == payload["toolchain"]["mathlib_revision"]
    (project / "lean-toolchain").write_text("wrong\n")
    with pytest.raises(ValueError, match="Lean toolchain"):
        environment_binding(corpus, project)


def test_dirty_dependency_rejected(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    corpus = load_corpus(save(tmp_path, payload))
    (project / ".lake/packages/mathlib/Tracked.lean").write_text("-- changed\n")
    with pytest.raises(ValueError, match="dirty"):
        environment_binding(corpus, project)


def test_actual_dependency_revision_checked(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    payload["toolchain"]["mathlib_revision"] = "b" * 40
    (project / "lake-manifest.json").write_text(
        json.dumps({"packages": [{"name": "mathlib", "type": "git", "rev": "b" * 40}]})
    )
    corpus = load_corpus(save(tmp_path, payload))
    with pytest.raises(ValueError, match="actual Mathlib HEAD"):
        environment_binding(corpus, project)


def test_pending_case_never_reports_complete(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    payload["cases"][0].update(source_path=None, status="authored_not_compiled")
    report = evaluate(
        load_corpus(save(tmp_path, payload)),
        project,
        elan_home=tmp_path,
        child_path="/usr/bin:/bin",
    )
    assert report["all_compiled"] is False
    assert report["cases"][0]["status"] == "authored_not_compiled"


def test_actual_verifier_rejects_placeholder_without_compilation(
    tmp_path: Path, payload: dict[str, Any]
) -> None:
    project = project_fixture(tmp_path, payload)
    (tmp_path / "proof.lean").write_text("theorem composite_injective : False := by sorry\n")
    report = evaluate(
        load_corpus(save(tmp_path, payload)),
        project,
        elan_home=tmp_path,
        child_path="/usr/bin:/bin",
    )
    assert report["all_compiled"] is False
    assert report["cases"][0]["status"] == "verification_failed"
    assert report["cases"][0]["diagnostics"][0]["code"] == "lean.disallowed_placeholder"


def test_lakefile_bytes_are_bound(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    corpus = load_corpus(save(tmp_path, payload))
    original = environment_binding(corpus, project)
    (project / "lakefile.lean").write_text("-- changed config\n")
    changed = environment_binding(corpus, project)
    assert changed["lakefile_sha256"] != original["lakefile_sha256"]
    assert changed["lake_manifest_sha256"] == original["lake_manifest_sha256"]
    (project / "lakefile.lean").rename(project / "lakefile.toml")
    assert environment_binding(corpus, project)["lakefile"] == "lakefile.toml"


def auxiliary_dependency(project: Path) -> Path:
    auxiliary = project / ".lake/packages/auxiliary"
    # Clone a tiny local Git pin-validation fixture, not a compiler dependency.
    subprocess.run(
        ["git", "clone", "--quiet", str(project / ".lake/packages/mathlib"), str(auxiliary)],
        check=True,
    )
    path = project / "lake-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["packages"].append(
        {
            "name": "auxiliary",
            "type": "git",
            "rev": git(auxiliary, "rev-parse", "HEAD"),
        }
    )
    path.write_text(json.dumps(manifest))
    return auxiliary


def test_stale_auxiliary_dependency_rejected(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    auxiliary = auxiliary_dependency(project)
    corpus = load_corpus(save(tmp_path, payload))
    assert len(environment_binding(corpus, project)["dependencies"]) == 2
    (auxiliary / "Tracked.lean").write_text("-- changed auxiliary\n")
    git(auxiliary, "add", "Tracked.lean")
    git(
        auxiliary,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "new auxiliary revision",
    )
    with pytest.raises(ValueError, match="actual auxiliary HEAD"):
        environment_binding(corpus, project)


def test_dirty_auxiliary_dependency_rejected(tmp_path: Path, payload: dict[str, Any]) -> None:
    project = project_fixture(tmp_path, payload)
    auxiliary = auxiliary_dependency(project)
    corpus = load_corpus(save(tmp_path, payload))
    (auxiliary / "Tracked.lean").write_text("-- changed auxiliary\n")
    with pytest.raises(ValueError, match="auxiliary tracked source is dirty"):
        environment_binding(corpus, project)


@pytest.mark.parametrize("mutation", ["duplicate", "floating", "missing", "non_git"])
def test_invalid_dependency_manifest_rejected(
    tmp_path: Path,
    payload: dict[str, Any],
    mutation: str,
) -> None:
    project = project_fixture(tmp_path, payload)
    auxiliary_dependency(project)
    path = project / "lake-manifest.json"
    manifest = json.loads(path.read_text())
    row = manifest["packages"][1]
    if mutation == "duplicate":
        manifest["packages"].append(copy.deepcopy(row))
    elif mutation == "floating":
        row["rev"] = "main"
    elif mutation == "missing":
        del row["rev"]
    else:
        row["type"] = "path"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        environment_binding(load_corpus(save(tmp_path, payload)), project)
