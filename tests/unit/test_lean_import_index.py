"""The import index as an import suggester, on the small fixture index (no Lean, no model)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pals_agent.lean_import_index import (
    ImportPlanConfigurationError,
    IndexImportSuggester,
    build_import_planning,
)
from pals_agent.lean_import_plan import ImportPlanning
from pals_agent.lean_profiles import resolve_profile
from tests.test_stacks_import_index import _sources
from tools.stacks_index.build_import_index import build
from tools.stacks_index.import_index import ImportIndex

_PROFILE = resolve_profile("stacks-frontier-defs-4.35")
_PINS = dict(_PROFILE.pins)


@pytest.fixture(scope="module")
def index_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("planning-index")
    build(
        _sources(),
        out,
        workers=1,
        provenance={"stacks_commit": _PINS["stacks"], "mathlib_commit": _PINS["mathlib"]},
    )
    return out / "import_index.sqlite"


@pytest.fixture(scope="module")
def suggester(index_path: Path) -> IndexImportSuggester:
    return IndexImportSuggester(ImportIndex(index_path, check_same_thread=False))


_HEADER = "import Mathlib\nimport StacksFrontier.Use\n\nopen Frontier\n\n"


def test_the_statement_names_the_modules(suggester: IndexImportSuggester) -> None:
    source = _HEADER + "theorem t (T : Thing) : flatThing T = T.level := by\n  simp [flatThing]\n"

    suggestion = suggester.suggest(source)

    assert suggestion.declined is None
    assert suggestion.imports == ("StacksFrontier.Thing",)
    assert suggestion.loaded_modules is not None and suggestion.loaded_modules > 1


def test_the_proof_is_not_read(suggester: IndexImportSuggester) -> None:
    # `Order.le_self` appears only in the proof, which the plan does not look at.
    source = (
        _HEADER + "theorem t (T : Thing) : flatThing T = T.level := by\n  exact Order.le_self\n"
    )

    assert suggester.suggest(source).imports == ("StacksFrontier.Thing",)


def test_every_theorem_of_the_source_counts(suggester: IndexImportSuggester) -> None:
    source = (
        _HEADER
        + "theorem a (T : Thing) : T.level = T.level := rfl\n"
        + "theorem b (T : Thing) : Core.ring_lemma T = T := sorry\n"
    )

    # `Core.ring_lemma` lives in StacksCore.Basic, which StacksFrontier.Thing already re-exports
    assert suggester.suggest(source).imports == ("StacksFrontier.Thing",)


def test_unknown_names_decline(suggester: IndexImportSuggester) -> None:
    source = _HEADER + "theorem t (T : Thing) : Nothing.here T = T.level := rfl\n"

    assert suggester.suggest(source).declined == "plan_unresolved"


def test_own_definitions_decline(suggester: IndexImportSuggester) -> None:
    source = (
        _HEADER
        + "def mine (n : Nat) : Nat := n\ntheorem t (T : Thing) : T.level = T.level := rfl\n"
    )

    assert suggester.suggest(source).declined == "local_definitions"


def test_a_source_without_a_readable_statement_declines(suggester: IndexImportSuggester) -> None:
    assert suggester.suggest(_HEADER + "def mine := 1\n").declined == "local_definitions"
    assert suggester.suggest(_HEADER + "theorem broken\n").declined == "statement_unreadable"


def test_a_statement_with_no_constant_has_no_plan(suggester: IndexImportSuggester) -> None:
    suggestion = suggester.suggest(_HEADER + "theorem t (x : Nat) : x = x := rfl\n")

    assert suggestion.declined is not None or suggestion.imports == ()


def test_the_planner_rewrites_the_header_over_the_fixture_index(
    suggester: IndexImportSuggester,
) -> None:
    source = _HEADER + "theorem t (T : Thing) : flatThing T = T.level := by\n  simp [flatThing]\n"

    planned = ImportPlanning(suggester).prepare(source, _PROFILE)

    assert planned.status is None
    assert planned.source is not None
    assert planned.source.startswith("import StacksFrontier.Thing\n")
    assert "Mathlib" not in planned.source.splitlines()[0]
    # the reviewed-only profile refuses the Frontier module the statement names
    refused = ImportPlanning(suggester).prepare(source, resolve_profile("stacks-4.35"))
    assert refused.status == "declined.plan_import_not_allowed"


def test_the_loader_binds_the_index_to_the_profile_pins(index_path: Path) -> None:
    planning = build_import_planning(index_path, _PROFILE, ["Mathlib.Order"])

    assert isinstance(planning.suggester, IndexImportSuggester)


def test_the_loader_refuses_an_index_from_other_revisions(
    tmp_path: Path, index_path: Path
) -> None:
    other = tmp_path / "other"
    provenance = {"stacks_commit": "0" * 40, "mathlib_commit": "1" * 40}
    build(_sources(), other, workers=1, provenance=provenance)

    with pytest.raises(ImportPlanConfigurationError, match="revisions pinned"):
        build_import_planning(other / "import_index.sqlite", _PROFILE)


def test_the_loader_refuses_what_it_cannot_serve(tmp_path: Path, index_path: Path) -> None:
    with pytest.raises(ImportPlanConfigurationError, match="pins the Stacks workspace"):
        build_import_planning(index_path, resolve_profile())
    with pytest.raises(ImportPlanConfigurationError, match="not found"):
        build_import_planning(tmp_path / "missing.sqlite", _PROFILE)
    (tmp_path / "broken.sqlite").write_bytes(b"not a database")
    with pytest.raises(ImportPlanConfigurationError, match="unreadable"):
        build_import_planning(tmp_path / "broken.sqlite", _PROFILE)
    with pytest.raises(ImportPlanConfigurationError, match="base module"):
        build_import_planning(index_path, _PROFILE, ["Mathlib.NoSuchModule"])
