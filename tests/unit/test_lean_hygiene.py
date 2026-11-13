"""Source hygiene: redundant Mathlib submodule imports and a missing ``open`` for a notation."""

from pathlib import Path

import pytest

from pals_agent import t2_lane
from pals_agent.lean_hygiene import normalise_source_header
from tests.unit.test_t2_api_reconcile import _api_pipeline, _run
from tests.unit.test_t2_pipeline import GOOD, STATEMENT, Generator, _flags


def test_a_stale_submodule_import_next_to_the_full_import_is_dropped() -> None:
    src = "import Mathlib\nimport Mathlib.Tactic.Omega\n\ntheorem t : True := by\n  trivial\n"
    assert normalise_source_header(src) == "import Mathlib\n\ntheorem t : True := by\n  trivial\n"


def test_a_partial_import_becomes_the_full_import() -> None:
    src = "import Mathlib.Data.Set.Basic\n\ntheorem t : True := trivial\n"
    assert normalise_source_header(src) == "import Mathlib\n\ntheorem t : True := trivial\n"


def test_the_missing_open_for_a_notation_is_added_once() -> None:
    src = "import Mathlib\n\ntheorem t : 𝓝 (0 : ℝ) = 𝓝 0 := rfl\n"
    out = normalise_source_header(src)
    assert out == "import Mathlib\nopen Topology\n\ntheorem t : 𝓝 (0 : ℝ) = 𝓝 0 := rfl\n"
    assert normalise_source_header(out) == out


@pytest.mark.parametrize(
    "src",
    [
        "import Mathlib\nopen Topology\n\ntheorem t : 𝓝 (0 : ℝ) = 𝓝 0 := rfl\n",
        "import Mathlib\nopen Filter Topology in\ntheorem t : 𝓝 (0 : ℝ) = 𝓝 0 := rfl\n",
        "import Mathlib\n\ntheorem t : True := trivial\n",
        "theorem t : True := trivial\n",
        "import Mathlib\nimport Aesop\n\ntheorem t : True := trivial\n",
    ],
)
def test_sources_that_need_nothing_are_untouched(src: str) -> None:
    assert normalise_source_header(src) == src


def test_an_open_of_another_namespace_does_not_count() -> None:
    src = "import Mathlib\nopen Filter\n\ntheorem t : 𝓝 (0 : ℝ) = 𝓝 0 := rfl\n"
    assert "open Topology\nopen Filter" in normalise_source_header(src)


def test_the_pipeline_submits_the_fixed_header_only_with_the_switch_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = GOOD.replace("import Mathlib", "import Mathlib\nimport Mathlib.Tactic.Omega", 1)
    assert stale != GOOD
    _flags(monkeypatch)
    monkeypatch.delenv(t2_lane.SOURCE_HYGIENE_ENV, raising=False)
    off, _ = _run(_api_pipeline(tmp_path / "off", Generator([stale])))
    assert off.generated.lean_code == stale
    monkeypatch.setenv(t2_lane.SOURCE_HYGIENE_ENV, "true")
    on, _ = _run(_api_pipeline(tmp_path / "on", Generator([stale])))
    assert on.generated.lean_code == GOOD


def test_the_switch_is_validated_with_the_other_t2_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(t2_lane.SOURCE_HYGIENE_ENV, "maybe")
    with pytest.raises(ValueError):
        t2_lane.validate_flags()


def test_ennreal_does_not_ask_for_nnreal() -> None:
    src = "import Mathlib\nopen ENNReal\n\ntheorem t (x : ℝ≥0∞) : x ≤ x := le_rfl\n"
    assert normalise_source_header(src) == src
    mixed = "import Mathlib\n\ntheorem t (x : ℝ≥0) (y : ℝ≥0∞) : True := trivial\n"
    both = normalise_source_header(mixed)
    assert "open NNReal" in both and "open ENNReal" in both


def test_a_request_with_its_own_header_is_never_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harness check needs the request's header verbatim in the output."""
    _flags(monkeypatch)
    monkeypatch.setenv(t2_lane.SOURCE_HYGIENE_ENV, "true")
    code = GOOD.replace("import Mathlib", "import Mathlib\nimport Mathlib.Tactic.Omega", 1)
    result = _api_pipeline(tmp_path, Generator([code])).run_statement(
        statement=STATEMENT, formal_statement=code.split(":= by")[0].rstrip() + " := by\n  simp\n",
        proof_job_id="job-1", on_status=lambda *_a: None,
    )
    assert "import Mathlib.Tactic.Omega" in result.generated.lean_code
