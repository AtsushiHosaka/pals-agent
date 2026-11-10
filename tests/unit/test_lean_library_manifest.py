"""Library manifests drive every profile; the profiles they yield equal the ones issued before."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from pals_agent import lean_profiles
from pals_agent.lean_audit import ALLOWED_AXIOMS
from pals_agent.lean_library_manifest import (
    MANIFEST_DIR,
    TRUST_REVIEWED,
    TRUST_UNREVIEWED,
    LibraryManifestError,
    canonical_trust,
    load_manifests,
    parse_manifest,
)

_ROOT = Path(__file__).resolve().parents[2]
# Produced from `_PROFILES`/`_LIBRARY_ROOTS` of pals-agent 8a75810 (origin/main) before they
# were deleted: every field of every profile plus the SHA-256 of its audit program.
_GOLDEN = json.loads((_ROOT / "tests/fixtures/lean_profiles_golden.json").read_text())


def _described(name: str) -> dict[str, Any]:
    profile = lean_profiles.resolve_profile(name)
    described = json.loads(json.dumps(dataclasses.asdict(profile)))
    described["audit_source_sha256"] = hashlib.sha256(profile.audit_source.encode()).hexdigest()
    return described


@pytest.mark.parametrize("name", [n for n in _GOLDEN if not n.startswith("_")])
def test_manifest_derived_profiles_equal_the_retired_constants(name: str) -> None:
    assert _described(name) == _GOLDEN[name]


def test_no_profile_was_added_or_dropped_and_order_is_kept() -> None:
    expected = [n for n in _GOLDEN if not n.startswith("_")]
    assert list(lean_profiles.known_profile_names()) == expected


def test_statement_trusted_roots_keep_the_retired_library_root_order() -> None:
    for name in ("stacks-frontier-4.35", "stacks-frontier-defs-4.35"):
        assert list(lean_profiles.resolve_profile(name).statement_trusted_roots or ()) == _GOLDEN[
            "_LIBRARY_ROOTS"
        ]


def test_enabling_flags_come_from_the_manifest() -> None:
    assert lean_profiles.FRONTIER_FLAG == "PALS_LEAN_ALLOW_FRONTIER_PROOFS"
    assert lean_profiles.FRONTIER_STATEMENTS_FLAG == "PALS_LEAN_ALLOW_FRONTIER_STATEMENTS"


def test_every_manifest_records_source_commit_licence_and_attribution() -> None:
    manifests = lean_profiles.MANIFESTS
    assert {m.name for m in manifests} == {"mathlib", "mathlib-archive", "stacks"}
    for manifest in manifests:
        assert manifest.repo.startswith("https://") and len(manifest.commit) == 40
        assert manifest.license_spdx and manifest.attribution
        assert set(manifest.allowed_axioms) <= ALLOWED_AXIOMS


def test_manifest_pins_match_the_workspace_lake_manifest() -> None:
    for manifest in lean_profiles.MANIFESTS:
        if manifest.host_profile is not None:
            continue
        workspace = _ROOT / manifest.workspace
        packages = json.loads((workspace / "lake-manifest.json").read_text())["packages"]
        revs = {p["name"].lower(): p.get("rev") for p in packages}
        for name, revision in manifest.pins:
            assert revs[name] == revision, (manifest.name, name)
        assert (workspace / "lean-toolchain").read_text().strip() == manifest.lean_version


def test_trust_words_use_the_generic_vocabulary_and_old_words_stay_readable() -> None:
    assert canonical_trust("core") == TRUST_REVIEWED == "kernel-checked-reviewed"
    assert canonical_trust("frontier") == TRUST_UNREVIEWED == "kernel-checked-unreviewed"
    assert canonical_trust("statement-only") == "statement-only"
    with pytest.raises(LibraryManifestError):
        canonical_trust("trusted")
    stacks = next(m for m in lean_profiles.MANIFESTS if m.name == "stacks")
    assert stacks.trust_of("StacksCore") == TRUST_REVIEWED
    assert stacks.trust_of("StacksFrontier") == TRUST_UNREVIEWED
    assert stacks.trust_of("Nope") is None


def _raw(name: str = "mathlib") -> dict[str, Any]:
    return tomllib.loads((MANIFEST_DIR / f"{name}.toml").read_text())


def _parse(data: dict[str, Any]):  # noqa: ANN202
    return parse_manifest(data, standard_axioms=ALLOWED_AXIOMS)


def test_the_loader_accepts_the_shipped_manifests() -> None:
    assert len(load_manifests(standard_axioms=ALLOWED_AXIOMS)) >= 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["audit"].update(allowed_axioms=["propext", "Classical.choice", "sorryAx"]),
        lambda d: d["library"].update(commit="main"),
        lambda d: d["library"].update(license="all rights reserved!"),
        lambda d: d["library"].update(repo="http://example.com/x"),
        lambda d: d["toolchain"].update(workspace="../elsewhere"),
        lambda d: d["toolchain"].update(workspace="/abs/path"),
        lambda d: d["toolchain"].update(lean="v4.32.0"),
        lambda d: d.update(schema="other"),
        lambda d: d["profiles"][0].update(imports=["NoSuchRoot"]),
        lambda d: d["profiles"][0].update(statements="whatever"),
        lambda d: d["profiles"][0].update(requires_flag="lowercase"),
        lambda d: d["layers"][0].update(trust="trusted"),
        lambda d: d["pins"].update(mathlib="abc"),
        lambda d: d.pop("profiles"),
    ],
)
def test_a_malformed_or_widening_manifest_is_refused(mutate: Any) -> None:
    data = copy.deepcopy(_raw())
    mutate(data)
    with pytest.raises(LibraryManifestError):
        _parse(data)


def test_a_statement_only_layer_can_never_be_imported() -> None:
    data = copy.deepcopy(_raw("stacks"))
    data["layers"].append({"root": "Conjectures", "trust": "statement-only"})
    data["profiles"][0]["imports"] = ["Mathlib", "Conjectures"]
    with pytest.raises(LibraryManifestError):
        _parse(data)


def test_recording_unreviewed_statements_needs_an_unreviewed_layer() -> None:
    data = copy.deepcopy(_raw("stacks"))
    data["layers"] = [layer for layer in data["layers"] if layer["trust"] == TRUST_REVIEWED]
    data["profiles"] = [p for p in data["profiles"] if p["name"] == "stacks-frontier-defs-4.35"]
    data["profiles"][0]["imports"] = ["Mathlib", "StacksCore"]
    manifest = _parse(data)
    with pytest.raises(LibraryManifestError):
        manifest.statement_roots("record-unreviewed")


def test_a_manifest_file_must_be_named_after_its_library(tmp_path: Path) -> None:
    (tmp_path / "renamed.toml").write_bytes((MANIFEST_DIR / "mathlib.toml").read_bytes())
    with pytest.raises(LibraryManifestError):
        load_manifests(tmp_path, standard_axioms=ALLOWED_AXIOMS)


def test_a_duplicate_profile_name_across_manifests_is_refused(tmp_path: Path) -> None:
    (tmp_path / "mathlib.toml").write_bytes((MANIFEST_DIR / "mathlib.toml").read_bytes())
    data = (MANIFEST_DIR / "mathlib.toml").read_text().replace('name = "mathlib"', 'name = "copy"')
    (tmp_path / "copy.toml").write_text(data)
    with pytest.raises(LibraryManifestError):
        load_manifests(tmp_path, standard_axioms=ALLOWED_AXIOMS)


def test_one_manifest_is_enough_to_add_a_library(tmp_path: Path) -> None:
    """A new library with its own layer and profile needs a file, not code."""
    (tmp_path / "mathlib.toml").write_bytes((MANIFEST_DIR / "mathlib.toml").read_bytes())
    stacks = (MANIFEST_DIR / "stacks.toml").read_text()
    other = (
        stacks.replace('name = "stacks"', 'name = "toy"')
        .replace("StacksCore", "ToyCore")
        .replace("StacksFrontier", "ToyFrontier")
        .replace("stacks-4.35", "toy-4.35")
        .replace("stacks-frontier-4.35", "toy-frontier-4.35")
        .replace("stacks-frontier-defs-4.35", "toy-frontier-defs-4.35")
        .replace("PALS_LEAN_ALLOW_FRONTIER_PROOFS", "PALS_LEAN_ALLOW_TOY_PROOFS")
        .replace("PALS_LEAN_ALLOW_FRONTIER_STATEMENTS", "PALS_LEAN_ALLOW_TOY_STATEMENTS")
    )
    (tmp_path / "toy.toml").write_text(other)
    manifests = load_manifests(tmp_path, standard_axioms=ALLOWED_AXIOMS)
    profiles = lean_profiles._build_profiles(manifests)
    assert list(profiles) == [
        "mathlib-4.32", "toy-4.35", "toy-frontier-4.35", "toy-frontier-defs-4.35",
    ]
    toy = profiles["toy-frontier-defs-4.35"]
    assert toy.statement_recorded_roots == ("ToyFrontier",)
    assert toy.requires_flag == "PALS_LEAN_ALLOW_TOY_STATEMENTS"
    assert toy.import_violation("import StacksCore\n") is not None
