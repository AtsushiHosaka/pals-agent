"""Pure corpus guard tests; actual Lean replay is a separate recorded command."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "catalog_expansion_under_test", Path(__file__).with_name("catalog.py")
)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def test_audit_changes_names_only_and_retains_original_proof_bytes():
    source = (
        "import Mathlib\n\n-- example : False := by sorry\n"
        "example (p : Prop) (h : p) : p := by\n  exact h\n"
    )
    audit, names = M.audit_source(source)
    assert names == ["pals_catalog_audit_0000"]
    assert audit == source.replace("\nexample (", "\ntheorem pals_catalog_audit_0000 (") + (
        "\n#print axioms pals_catalog_audit_0000\n"
    )


@pytest.mark.parametrize(
    "source",
    [
        "example : True := by sorry",
        "axiom hidden : False\nexample : False := hidden",
        "unsafe def hidden : Nat := 1",
        "example : True := by admit",
        "#eval IO.println 1\nexample : True := by trivial",
        "namespace Hidden\nexample : True := by trivial\nend Hidden",
    ],
)
def test_unchecked_constructs_cannot_be_replayed(source):
    with pytest.raises(ValueError):
        M.audit_source(source)


@pytest.mark.parametrize(
    "output",
    [
        "'pals_catalog_audit_0000' depends on axioms: [sorryAx]",
        "'pals_catalog_audit_0000' depends on axioms: [untrusted]",
        "",
        "'different' depends on axioms: [propext]",
        "'pals_catalog_audit_0000' depends on axioms: [propext]\n"
        "'pals_catalog_audit_0000' depends on axioms: [propext]",
    ],
)
def test_missing_extra_or_untrusted_axiom_evidence_is_rejected(output):
    with pytest.raises(ValueError):
        M.axioms(output, ["pals_catalog_audit_0000"])


def test_complete_axiom_observation_accepts_only_the_declared_foundations():
    names = ["a", "b"]
    observed = M.axioms(
        "'a' depends on axioms: [propext, Classical.choice, Quot.sound]\n"
        "'b' does not depend on any axioms",
        names,
    )
    assert observed == {"a": ["Classical.choice", "Quot.sound", "propext"], "b": []}


def test_localization_retains_original_arbitrary_section_parameter():
    context = "variable (S : Type*) [CommRing S] [Algebra R S] [IsLocalization M S]"
    source = "import Mathlib\n" + context + "\nexample : True := by trivial\n"
    audit, names = M.audit_source(source)
    assert context + "\ninclude M\n" in audit
    assert " : True := by trivial\n" in audit
    assert len(names) == 1


def test_exact_card_marker_binds_the_actual_source_example_with_outer_premises():
    source = (
        "import Mathlib\n-- manifest card: meaningful\n"
        "example (p : Prop) (h : p) : p := by\n  exact h\n"
    )
    assert M.example_index(source, {"id": "meaningful"}) == 0
    with pytest.raises(ValueError):
        M.example_index(source + "example : True := by trivial\n", {"id": "meaningful"})


def test_full_witness_mapping_is_unique_when_source_has_no_markers():
    row = {"id": "case", "lean_target": "example : True", "lean_witness": "by trivial"}
    source = "import Mathlib\nexample : True := by trivial\n"
    assert M.example_index(source, row) == 0
    with pytest.raises(ValueError):
        M.example_index(source + source, row)


def test_source_read_refuses_traversal_symlinks_and_drift(tmp_path):
    path = tmp_path / "source.lean"
    path.write_text("example : True := by trivial\n")
    digest = M.sha(path.read_bytes())
    assert M.read(tmp_path, path.name, digest) == path.read_bytes()
    for relative in ("../source.lean", str(path)):
        with pytest.raises(ValueError):
            M.read(tmp_path, relative)
    link = tmp_path / "link.lean"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        M.read(tmp_path, link.name)
    path.write_text("changed")
    with pytest.raises(ValueError):
        M.read(tmp_path, path.name, digest)


def test_output_is_exclusive_private_and_has_no_overwrite(tmp_path):
    path = tmp_path / "report.json"
    M.save(path, {"published": False})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        M.save(path, {"published": True})
    assert json.loads(path.read_bytes()) == {"published": False}


def test_actual_pinned_inventory_has_no_identity_padding_or_publication_claim():
    data = M.inventory()
    assert data["exact_record_count"] == 744
    assert len(data["cards"]) == len({row["id"] for row in data["cards"]}) == 744
    assert data["structural_pattern_count"] == 736
    assert sum(row["api_profile_registered"] for row in data["cards"]) >= 286
    assert data["excluded"] == [
        {
            "source_id": "typed.plane-geometry",
            "reason": "owning_manifest_validation_failed",
            "card_ids": [
                "typed_plane_distance_self_zero",
                "typed_plane_line_through_two_points",
                "typed_plane_circle_through_three_points",
                "typed_plane_perpendicular_symmetric",
                "typed_plane_parallel_symmetric",
            ],
        }
    ]
    assert data["usable_runtime_records_added"] == 0
    for row in data["cards"]:
        assert not row["compiled_in_this_run"] and not row["admitted"] and not row["published"]
        assert row["lean_target"] and row["lean_witness"] and row["imports"]
        assert 0 <= row["source_example_index"] < 128


def test_pinned_manifest_drift_fails_before_calling_owning_loader(monkeypatch):
    original = json.loads(M.SOURCES.read_bytes())
    altered = copy.deepcopy(original)
    altered["sources"][0]["manifest_sha256"] = "0" * 64
    monkeypatch.setattr(
        M.Path,
        "read_bytes",
        lambda self: json.dumps(altered).encode() if self == M.SOURCES else original_read(self),
    )
    with pytest.raises(ValueError, match="source bytes changed"):
        M.inventory()


def test_concurrent_runtime_registration_cannot_hide_mathematical_drift():
    before = {"cards": [{"id": "same", "lean_target": "target", "api_profile_registered": False}]}
    after = copy.deepcopy(before)
    after["cards"][0]["api_profile_registered"] = True
    assert M.mathematical_identity(before) == M.mathematical_identity(after)
    after["cards"][0]["lean_target"] = "changed"
    assert M.mathematical_identity(before) != M.mathematical_identity(after)


original_read = Path.read_bytes
