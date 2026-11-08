from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from tools.stacks_index.build_index import build
from tools.stacks_index.extract import (
    Declaration,
    extract_file,
    extract_text,
    mask_source,
    relevant_context,
    split_binders,
)
from tools.stacks_index.probe import run as probe_run
from tools.stacks_index.search import (
    StacksIndex,
    lean_query_terms,
    natural_query_terms,
    reciprocal_rank_fusion,
)
from tools.stacks_index.shape import query_shape, statement_shape

FIXTURE = Path(__file__).parent / "fixtures" / "stacks_index"


@pytest.fixture(scope="module")
def demo() -> dict[str, Declaration]:
    result = extract_file(FIXTURE / "StacksCore/Demo/Flat.lean", FIXTURE)
    return {d.name: d for d in result.declarations}


def test_mask_hides_comments_and_strings_but_keeps_offsets() -> None:
    text = (
        'theorem a : True := by -- theorem b\n  /- theorem c /- nested -/ theorem d -/\n  "x:=y"\n'
    )
    masked, comments = mask_source(text)
    assert len(masked) == len(text)
    assert "theorem b" not in masked and "theorem c" not in masked and "theorem d" not in masked
    assert "x:=y" not in masked and masked.count("\n") == text.count("\n")
    assert {c.kind for c in comments} == {"line", "block"}


def test_declarations_names_kinds_and_scopes(demo: dict[str, Declaration]) -> None:
    assert {n: d.kind for n, d in demo.items()} == {
        "Demo.FlatLike": "def",
        "Demo.flat_tensor_injective": "theorem",
        "Demo.universe_demo": "theorem",
        "Demo.flat_of_free": "theorem",
        "Demo.instNamed": "instance",
        "Demo.Presentation": "structure",
        "Demo.inner_thing": "theorem",
        "Demo.after_section": "theorem",
        "Demo.uses_open_in": "theorem",
        "Elsewhere.root_named": "theorem",  # `_root_.` ignores the surrounding namespace
        "Demo.matched": "def",
    }
    assert "line_comment_decoy" not in "".join(demo) and "fake" not in "".join(demo)


def test_private_and_anonymous_instances_are_counted_not_indexed() -> None:
    result = extract_file(FIXTURE / "StacksCore/Demo/Flat.lean", FIXTURE)
    assert result.skipped == {"private": 1, "anonymous_instance": 1}


def test_signature_stops_at_assignment_and_ignores_default_arguments(
    demo: dict[str, Declaration],
) -> None:
    assert demo["Demo.universe_demo"].signature == "(n : ℕ := 3) {α : Type v} (a : α) : a = a"
    assert demo["Demo.matched"].signature == ": ℕ → ℕ"
    assert demo["Demo.uses_open_in"].signature.endswith(": Injective f")
    assert demo["Demo.flat_of_free"].signature == "(hM : Module.Free R M) : Module.Flat R M"


def test_context_keeps_only_variables_the_statement_depends_on(
    demo: dict[str, Declaration],
) -> None:
    assert demo["Demo.flat_of_free"].context == (
        "{R : Type u} [CommRing R] (M : Type*) [AddCommGroup M] [Module R M]"
    )
    # section-local `S` is visible inside the section only; `N` is not mentioned there.
    assert demo["Demo.inner_thing"].context == "{R : Type u} [CommRing R] (S : Type*) [CommRing S]"
    assert demo["Demo.after_section"].context == "{N : Type*} [AddCommGroup N]"
    # a binder in the signature shadows the variable of the same name
    assert demo["Demo.Presentation"].context == ""
    assert demo["Demo.FlatLike"].context == ""


def test_relevant_context_instance_binders_need_all_their_variables() -> None:
    variables = split_binders("{R : Type*} [CommRing R] {ι : Type*} [Fintype ι] [Module R ι]")
    assert relevant_context(variables, ": R = R") == "{R : Type*} [CommRing R]"


def test_attribute_tags_survive_commas_in_comment_strings(demo: dict[str, Declaration]) -> None:
    tags = {(t.tag, t.comment, t.source) for t in demo["Demo.flat_tensor_injective"].tags}
    assert tags == {
        ("00DM", "3, a part of the correctness", "attribute"),
        ("00DN", "", "attribute"),
    }
    assert demo["Demo.flat_tensor_injective"].attrs == []
    assert demo["Demo.FlatLike"].attrs == ["simp"]
    assert [(t.tag, t.comment) for t in demo["Demo.FlatLike"].tags] == [("00DH", "definition")]


def test_attributes_on_their_own_line_and_docstrings_attach(demo: dict[str, Declaration]) -> None:
    assert demo["Demo.flat_of_free"].attrs == ["simp"]
    assert demo["Demo.FlatLike"].doc.startswith("A module is *flat*")
    assert demo["Demo.flat_of_free"].doc == ""


def test_docstring_mentions_are_recorded_separately_from_attributes() -> None:
    text = (
        "/-- See Stacks Tag 01U2 for details, Tag ABCD is not a tag. -/\n"
        "theorem t : True := trivial\n"
    )
    (declaration,) = extract_text(text, module="M", path="M.lean").declarations
    assert [(t.tag, t.source) for t in declaration.tags] == [("01U2", "docstring")]


def test_structure_body_keeps_field_docs(demo: dict[str, Declaration]) -> None:
    body = demo["Demo.Presentation"].body
    assert "Number of generators." in body and "gens : ℕ" in body
    assert demo["Demo.Presentation"].signature == (
        "(R : Type u) [CommRing R] extends Inhabited (Fin 1)"
    )


def test_line_numbers_point_at_the_declaration_keyword(demo: dict[str, Declaration]) -> None:
    lines = (FIXTURE / "StacksCore/Demo/Flat.lean").read_text().splitlines()
    for name in ("Demo.FlatLike", "Demo.flat_of_free", "Demo.Presentation"):
        declaration = demo[name]
        assert declaration.name.rsplit(".", 1)[-1] in lines[declaration.line - 1]


def test_upstream_links_and_module_info() -> None:
    result = extract_file(FIXTURE / "StacksCore/Demo/Flat.lean", FIXTURE)
    targets = {(u.target, u.tag.tag) for u in result.upstream if u.tag.tag}
    assert targets == {
        ("Module.Flat", "00DJ"),
        ("Demo.flat_tensor_injective", "00DJ"),
        ("Helper.thing", "0ZZZ"),
    }
    assert result.module.title == "Flat modules and a decoy"
    assert {"00DH", "00DJ", "00DK"} <= set(result.module.tags)
    assert any(u.tag.source.startswith("add_to_ega") for u in result.upstream)


def test_statement_shape_separates_conclusion_and_hypotheses() -> None:
    shape = statement_shape(
        "{R S : Type*} [CommRing R] (f : R →+* S) (h : Function.Injective f) : Module.Flat R S"
    )
    assert shape["conclusion_constants"] == ["Module.Flat"]
    assert "Function.Injective" in shape["hypothesis_constants"]
    assert "R" not in shape["hypothesis_constants"] and "f" not in shape["hypothesis_constants"]
    quantified = statement_shape(": ∀ x : Set ℕ, IsOpen x")
    assert quantified["conclusion_constants"] == ["Set", "IsOpen"]
    projection = query_shape("theorem t (p : Polynomial R) : p.degree = 0 := by simp")
    assert "degree" in projection["conclusion_constants"]


@pytest.fixture(scope="module")
def indexes(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict[str, Any]]:
    base = tmp_path_factory.mktemp("stacks_index")
    core_manifest = build(FIXTURE, base / "core", workers=1)
    build(FIXTURE, base / "all", include_frontier=True, workers=1)
    return base / "core", base / "all", core_manifest


def test_default_build_excludes_frontier_and_records_provenance(
    indexes: tuple[Path, Path, dict[str, Any]],
) -> None:
    core, _, manifest = indexes
    assert manifest["include_frontier"] is False
    assert set(manifest["trust_levels"]) == {"core"}
    assert manifest["lean_toolchain"] == "leanprover/lean4:v4.35.0"
    assert manifest["mathlib"] == "v4.35.0 (abc123)"
    core_stats = manifest["trust_levels"]["core"]
    assert core_stats["declarations"] == 11
    assert core_stats["tagged_by_attribute_or_add_to_stacks"] == 3
    assert core_stats["tagged_share"] == round(3 / 11, 4)
    index = StacksIndex(core / "index.sqlite")
    assert index.describe(["Scheme.Hom.flat_iff_stalkMap_flat"]) == []
    assert index.text_search(["scheme"], scope="all") == []


def test_frontier_is_opt_in_and_marked_untrusted(
    indexes: tuple[Path, Path, dict[str, Any]],
) -> None:
    _, everything, _ = indexes
    index = StacksIndex(everything / "index.sqlite")
    name = "AlgebraicGeometry.Scheme.Hom.flat_iff_stalkMap_flat"
    assert [c.name for c in index.text_search(["flat", "morphism", "scheme"], scope="all")][
        0
    ] == name
    assert index.text_search(["flat", "morphism", "scheme"], scope="core")[0].name != name
    (row,) = index.describe([name])
    assert row["trust"] == "frontier"
    assert index.by_tag("01U2", scope="core") == []
    assert [r["name"] for r in index.by_tag("01U2", scope="all")] == [name, "Module.Flat"]


def test_add_to_stacks_resolves_to_local_declaration_or_becomes_upstream(
    indexes: tuple[Path, Path, dict[str, Any]],
) -> None:
    core, _, manifest = indexes
    index = StacksIndex(core / "index.sqlite")
    (local,) = index.describe(["Demo.flat_tensor_injective"])
    assert {(t["tag"], t["source"]) for t in local["tags"]} == {
        ("00DM", "attribute"),
        ("00DN", "attribute"),
        ("00DJ", "add_to_stacks"),
    }
    (upstream,) = index.describe(["Module.Flat"])
    assert upstream["kind"] == "upstream" and upstream["type"] is None
    assert manifest["upstream"]["tag_links_resolved_to_stacks_declarations"] == 1
    assert manifest["upstream"]["ega_sga_links_not_indexed"] == 1
    assert {r["name"] for r in index.by_tag("00dj")} == {
        "Module.Flat",
        "Demo.flat_tensor_injective",
    }


def test_text_and_symbol_search(indexes: tuple[Path, Path, dict[str, Any]]) -> None:
    core, _, _ = indexes
    index = StacksIndex(core / "index.sqlite")
    hits = index.text_search(
        natural_query_terms("a module is flat if tensoring preserves injections")
    )
    assert {"Demo.FlatLike", "Module.Flat"} <= {c.name for c in hits[:4]}
    assert index.text_search(natural_query_terms("flat"), include_upstream=False)[0].name != (
        "Module.Flat"
    )
    by_symbol = index.symbol_search_lean(
        "theorem q (R M : Type*) (h : Module.Free R M) : Module.Flat R M"
    )
    assert by_symbol[0].name == "Demo.flat_of_free"
    fused = reciprocal_rank_fusion(
        [by_symbol, index.text_search(lean_query_terms("Module.Flat"))], k=3
    )
    assert fused[0].name == "Demo.flat_of_free"
    with pytest.raises(ValueError):
        index.text_search(["flat"], scope="trusted")


def test_build_is_deterministic_and_exports_every_row(
    indexes: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    core, _, manifest = indexes
    again = build(FIXTURE, tmp_path / "again", workers=1)
    assert again["decls_sha256"] == manifest["decls_sha256"]
    with gzip.open(core / "decls.jsonl.gz", "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 11 + manifest["upstream"]["entries"]
    assert all(row["schema_version"] == 1 for row in rows)


def test_unreviewed_layer_cannot_tag_reviewed_declarations(
    indexes: tuple[Path, Path, dict[str, Any]],
) -> None:
    core, everything, _ = indexes
    full = StacksIndex(everything / "index.sqlite")
    (flat_like,) = full.describe(["Demo.FlatLike"])
    assert {t["tag"] for t in flat_like["tags"]} == {"00DH"}
    (upstream,) = full.describe(["Module.Flat"])
    assert {(t["tag"], t["trust"]) for t in upstream["tags"]} == {
        ("00DJ", "core"),
        ("01U2", "frontier"),
    }
    assert [r["name"] for r in full.by_tag("01U2", scope="core")] == []
    assert {r["name"] for r in full.by_tag("01U2", scope="all")} >= {"Module.Flat"}
    assert full.manifest()["upstream"]["tag_links_from_a_less_trusted_layer_ignored"] == 1
    # the core-only index never saw the frontier tag
    (core_upstream,) = StacksIndex(core / "index.sqlite").describe(["Module.Flat"])
    assert {t["trust"] for t in core_upstream["tags"]} == {"core"}


def test_probe_reports_frontier_only_topics_as_misses_in_core_scope(
    indexes: tuple[Path, Path, dict[str, Any]],
) -> None:
    core, everything, _ = indexes
    by_query = {
        probe.query: rank
        for probe, rank, _ in probe_run(StacksIndex(core / "index.sqlite"), scope="core", k=5)
    }
    assert by_query["properties of a flat morphism of schemes"] is None
    with_frontier = {
        probe.query: rank
        for probe, rank, _ in probe_run(StacksIndex(everything / "index.sqlite"), scope="all", k=5)
    }
    assert with_frontier["properties of a flat morphism of schemes"] == 1
