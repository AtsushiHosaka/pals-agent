from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.stacks_index.build_import_index import (
    Source,
    build,
    compute_source_digest,
    diff_indexes,
)
from tools.stacks_index.build_index import build as build_declaration_index
from tools.stacks_index.header import parse_header
from tools.stacks_index.import_index import ImportIndex, plan_summary

FIXTURE = Path(__file__).parent / "fixtures" / "import_index"


def _sources(frontier: bool = True) -> list[Source]:
    sources = [Source("core", FIXTURE / "stacks", ("StacksCore",))]
    if frontier:
        sources.append(Source("frontier", FIXTURE / "stacks", ("StacksFrontier",)))
    sources.append(Source("mathlib", FIXTURE / "mathlib", ("Mathlib",)))
    sources.append(Source("lean", FIXTURE / "lean", ("Init",)))
    return sources


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object]]:
    out = tmp_path_factory.mktemp("import-index")
    manifest = build(_sources(), out, workers=1)
    return out / "import_index.sqlite", manifest


@pytest.fixture(scope="module")
def index(built: tuple[Path, dict[str, object]]) -> ImportIndex:
    return ImportIndex(built[0])


def test_header_flags_and_comments() -> None:
    header = parse_header(
        "/- license -/\nmodule\n\npublic import A.B\nimport C\npublic meta import D\n"
        "import all E\n-- import Fake\n/- import AlsoFake -/\n\ndef x := 1\nimport Late\n"
    )
    assert header.module_system
    edges = {e.imported: (e.public, e.meta, e.all) for e in header.imports}
    assert edges == {
        "A.B": (True, False, False),
        "C": (False, False, False),
        "D": (True, True, False),
        "E": (False, False, True),
    }


def test_legacy_file_imports_are_all_public() -> None:
    header = parse_header("import A\nimport B\n\ntheorem t : True := trivial\n")
    assert not header.module_system
    assert all(edge.public for edge in header.imports)
    assert parse_header("prelude\nimport Init.Core\n").prelude


def test_build_counts_layers_and_edges(built: tuple[Path, dict[str, object]]) -> None:
    _, manifest = built
    layers = manifest["layers"]
    assert isinstance(layers, dict)
    assert layers["core"]["modules"] == 1
    assert layers["frontier"]["modules"] == 4
    assert layers["mathlib"]["modules"] == 4  # Mathlib.lean, Order, Hidden, Algebra.Ring
    assert layers["lean"]["modules"] == 3
    assert manifest["unscanned_modules"] == 0


def test_every_non_prelude_module_imports_init_and_prelude_does_not(index: ImportIndex) -> None:
    assert ("Init", True) in index.direct_imports("Mathlib.Order")
    assert ("Init", True) in index.direct_imports("StacksFrontier.Legacy")
    assert all(name != "Init" for name, _ in index.direct_imports("Init.Core"))


def test_visible_and_loaded_closures_differ_by_private_imports(index: ImportIndex) -> None:
    # Thing publicly imports StacksCore.Basic but privately imports Mathlib.Hidden.
    visible = index.closure_of(["StacksFrontier.Thing"], "public")
    loaded = index.closure_of(["StacksFrontier.Thing"], "all")
    assert "Mathlib.Hidden" in loaded and "Mathlib.Hidden" not in visible
    assert "Mathlib.Algebra.Ring" in visible  # re-exported through Core
    assert visible <= loaded


def test_module_flags_are_stored_per_edge(index: ImportIndex) -> None:
    edges = dict(index.direct_imports("StacksFrontier.Use"))
    assert edges["StacksFrontier.Thing"] is True
    assert edges["Mathlib.Order"] is True  # `public meta import`
    assert edges["Mathlib.Algebra.Ring"] is False  # `import all` is not a re-export


def test_locate_gives_defining_module_and_layer(index: ImportIndex) -> None:
    [place] = index.locate("Core.ring_lemma")
    assert (place.module, place.layer, place.kind) == (
        "StacksCore.Basic",
        "core",
        "theorem",
    )
    [place] = index.locate("Frontier.Thing")
    assert place.kind == "structure"


def test_minimal_import_set_drops_modules_reached_through_others(index: ImportIndex) -> None:
    plan = index.plan(["Core.ring_lemma", "Ring.double", "Order.le_self"])
    # Ring.double and Order.le_self are already imported by the Core module
    assert plan.imports == ["StacksCore.Basic"]
    assert plan.trust_level == "core"
    assert "Mathlib.Order" in plan.closure and "Init" in plan.loaded


def test_plan_asks_only_for_what_is_named(index: ImportIndex) -> None:
    plan = index.plan(["Order.le_self"])
    assert plan.imports == ["Mathlib.Order"]
    assert plan.loaded_size < index.plan(["Frontier.flatThing"]).loaded_size
    assert plan.trust_level == "mathlib"


def test_open_namespaces_and_current_namespace_resolve(index: ImportIndex) -> None:
    hits, prefix = index.resolve("Thing", opens=["Frontier"])
    assert [h.name for h in hits] == ["Frontier.Thing"] and prefix is None
    hits, _ = index.resolve("flatThing", namespaces=["Frontier.Sub"])
    assert [h.name for h in hits] == ["Frontier.flatThing"]


def test_structure_field_resolves_to_its_structure(index: ImportIndex) -> None:
    hits, prefix = index.resolve("Frontier.Thing.level")
    assert prefix == "Frontier.Thing" and hits[0].module == "StacksFrontier.Thing"
    # a missing theorem name must not be attributed to a namespace-like definition
    assert index.resolve("Frontier.flatThing.nope")[0] == []


def test_export_alias_makes_bare_name_resolve(index: ImportIndex) -> None:
    [place] = index.locate("basicMap")
    assert (place.module, place.kind) == ("Mathlib.Algebra.Ring", "alias")


def test_dot_notation_tail_is_a_weak_candidate_only(index: ImportIndex) -> None:
    plan = index.plan(["level_pos_iff"])
    assert plan.unresolved == [] and "level_pos_iff" in plan.weak
    strict = index.plan(["level_pos_iff"], include_weak=False)
    assert strict.imports == []


def test_unknown_names_are_reported_not_guessed(index: ImportIndex) -> None:
    plan = index.plan(["Nothing.here", "Order.le_self"])
    assert plan.unresolved == ["Nothing.here"]
    assert plan.imports == ["Mathlib.Order"]


def test_open_of_an_undeclared_namespace_adds_a_module_that_declares_it(
    index: ImportIndex,
) -> None:
    plan = index.plan(["Order.le_self"], opens=["Ring"])
    assert plan.namespace_added == {"Ring": "Mathlib.Algebra.Ring"}
    assert "Mathlib.Algebra.Ring" in plan.imports or "Mathlib.Algebra.Ring" in plan.closure
    # already declared by the imports: nothing is added
    assert index.plan(["Ring.double"], opens=["Ring"]).namespace_added == {}


def test_namespace_prefers_reviewed_layers_over_frontier(index: ImportIndex) -> None:
    # `Order` is declared by Mathlib.Order and by the Frontier duplicate; the reviewed one wins.
    plan = index.plan(["Hidden.secret"], opens=["Order"])
    assert plan.namespace_added["Order"] == "Mathlib.Order"


def test_same_name_in_two_layers_is_recorded_as_a_conflict(index: ImportIndex) -> None:
    rows = index.db.execute("SELECT name, layers FROM conflict").fetchall()
    assert rows == [("Order.le_self", "frontier,mathlib")]
    plan = index.plan(["Order.le_self"], visibility="public")
    # both modules are never loaded together here, so the plan itself has no conflict
    assert plan.conflicts == []
    both = index.plan([], extra_modules=["Mathlib.Order", "StacksFrontier.Dup"])
    assert [name for name, _ in both.conflicts] == ["Order.le_self"]


def test_identical_statements_across_layers_are_linked(index: ImportIndex) -> None:
    names = {loc.name for loc in index.equivalents("Order.le_self")}
    assert "Order.le_self_dup" in names


def test_plan_for_source_reads_open_lines_and_ignores_own_imports(index: ImportIndex) -> None:
    source = (
        "import Mathlib\nopen Frontier\n\n"
        "theorem t (T : Thing) : flatThing T = T.level := by\n  sorry\n"
    )
    plan = index.plan_for_source(source)
    assert plan.imports == ["StacksFrontier.Thing"]
    assert plan.trust_level == "frontier"
    summary = plan_summary(plan)
    assert "T.level" not in json.dumps(summary)  # no statement text in the summary
    assert summary["stacks_modules_loaded"] == 2  # Thing and Core.Basic
    assert index.own_imports_closure(source) == index.closure_of(["Mathlib"])


def test_build_is_deterministic_across_worker_counts(
    built: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    again = build(_sources(), tmp_path, workers=2)
    assert again["content_digest"] == built[1]["content_digest"]
    assert again["source_digest"] == built[1]["source_digest"]


def test_source_digest_changes_with_a_file_and_verify_matches(
    built: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    assert compute_source_digest(_sources()) == built[1]["source_digest"]
    assert compute_source_digest(_sources(frontier=False)) != built[1]["source_digest"]


def test_diff_reports_added_modules_and_moved_declarations(
    built: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    build(_sources(frontier=False), tmp_path, workers=1)
    change = diff_indexes(tmp_path / "import_index.sqlite", built[0])
    assert change["modules_added"] == 4 and change["modules_removed"] == 0
    assert change["declarations_added"] > 0 and change["declarations_moved"] == 0
    assert diff_indexes(built[0], built[0])["edges_added"] == 0


def test_core_only_build_leaves_frontier_names_unresolved(tmp_path: Path) -> None:
    build(_sources(frontier=False), tmp_path, workers=1)
    core_only = ImportIndex(tmp_path / "import_index.sqlite")
    assert core_only.locate("Frontier.Thing") == []
    assert core_only.plan(["Frontier.Thing"]).unresolved == ["Frontier.Thing"]


def test_reusing_the_declaration_index_gives_the_same_rows(tmp_path: Path) -> None:
    stacks = FIXTURE / "stacks"
    declaration_dir = tmp_path / "decl"
    build_declaration_index(stacks, declaration_dir, include_frontier=True, workers=1)
    direct = tmp_path / "direct"
    reused = tmp_path / "reused"
    build(_sources(), direct, workers=1)
    build(_sources(), reused, workers=1, stacks_index=declaration_dir / "index.sqlite")

    def stacks_rows(path: Path) -> set[tuple[str, str]]:
        connection = sqlite3.connect(path / "import_index.sqlite")
        return set(
            connection.execute(
                "SELECT d.name, m.name FROM decl d JOIN module m ON m.id = d.module"
                " WHERE m.layer IN ('core', 'frontier') AND d.kind != 'alias'"
            )
        )

    # the declaration index drops a repeated name, the import index keeps every definition
    assert stacks_rows(reused) <= stacks_rows(direct)
    assert stacks_rows(direct) - stacks_rows(reused) <= {("Order.le_self", "StacksFrontier.Dup")}
