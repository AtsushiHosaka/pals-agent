"""Real-Lean checks of the statement/proof split of ``stacks-frontier-4.35``.

Opt-in: set ``PALS_FRONTIER_TEST_WORKSPACE`` to a ``lean-workspaces/stacks-4.35`` copy on which
``lake exe cache get`` has run and these modules are built (needs the pinned toolchain, not PATH's):

    lake build StacksFrontier.AlgebraicGeometry.Scheme.AffineOpenNeighborhood \
               StacksFrontier.AlgebraicGeometry.Morphisms.Fibres.SourcePoint
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_profiles import resolve_profile

_WORKSPACE = os.environ.get("PALS_FRONTIER_TEST_WORKSPACE")
pytestmark = pytest.mark.skipif(not _WORKSPACE, reason="PALS_FRONTIER_TEST_WORKSPACE is not set")

_AON = "import StacksFrontier.AlgebraicGeometry.Scheme.AffineOpenNeighborhood\n"
_SOURCE_POINT = "import StacksFrontier.AlgebraicGeometry.Morphisms.Fibres.SourcePoint\n"
_HEAD = "open AlgebraicGeometry CategoryTheory\nuniverse u\n"
_NEIGHBOURHOOD = """
theorem t {X : Scheme.{u}} (x : X) (U : X.Opens) (hx : x ∈ U) :
    ∃ V : X.affineOpens, x ∈ V.1 ∧ V.1 ≤ U :=
  exists_affineOpen_mem_le x U hx
"""


@pytest.fixture(scope="module")
def verifier(tmp_path_factory: pytest.TempPathFactory) -> Iterator[LeanVerifier]:
    assert _WORKSPACE is not None
    profile = resolve_profile("stacks-frontier-4.35")
    workspace = Path(_WORKSPACE)
    profile.validate_workspace(workspace)
    yield LeanVerifier(
        project_dir=workspace,
        library_profile=profile,
        timeout_seconds=300,
        child_path=f"{Path.home()}/.elan/bin:/usr/bin:/bin",
        elan_home=f"{Path.home()}/.elan",
        scratch_dir=tmp_path_factory.mktemp("frontier-scratch"),
    )


def _codes(verifier: LeanVerifier, source: str) -> tuple[bool, list[str]]:
    result = verifier.verify(source)
    return result.success, [diagnostic.code for diagnostic in result.diagnostics]


def test_a_mathlib_statement_may_be_proved_with_a_frontier_lemma(verifier: LeanVerifier) -> None:
    assert _codes(verifier, _AON + _HEAD + _NEIGHBOURHOOD) == (True, ["lean.verified"])


def test_a_statement_that_mentions_a_frontier_definition_is_rejected(
    verifier: LeanVerifier,
) -> None:
    source = _SOURCE_POINT + _HEAD + """
theorem t {X Y : Scheme.{u}} (f : X ⟶ Y) (x : X) (y : Y) (h : f x = y) :
    Scheme.Hom.asFiberAt f x y h = Scheme.Hom.asFiberAt f x y h := rfl
"""
    assert _codes(verifier, source) == (False, ["lean.statement_uses_untrusted_library"])


def test_a_statement_reaching_a_frontier_definition_through_a_local_def_is_rejected(
    verifier: LeanVerifier,
) -> None:
    source = _SOURCE_POINT + _HEAD + """
noncomputable def pt {X Y : Scheme.{u}} (f : X ⟶ Y) (x : X) (y : Y) (h : f x = y) : f.fiber y :=
  Scheme.Hom.asFiberAt f x y h
theorem t {X Y : Scheme.{u}} (f : X ⟶ Y) (x : X) (y : Y) (h : f x = y) :
    pt f x y h = pt f x y h := rfl
"""
    assert _codes(verifier, source) == (False, ["lean.statement_uses_untrusted_library"])


def test_sorry_and_extra_axioms_stay_forbidden(verifier: LeanVerifier) -> None:
    assert _codes(verifier, _AON + "theorem t : 1 = 1 := by sorry\n") == (
        False,
        ["lean.disallowed_placeholder"],
    )
    assert _codes(verifier, _AON + "axiom bad : False\ntheorem t : False := bad\n") == (
        False,
        ["lean.disallowed_trusted_declaration"],
    )


def test_a_frontier_module_that_was_not_built_cannot_be_imported(verifier: LeanVerifier) -> None:
    source = "import StacksFrontier.NoSuchModule\nexample : True := trivial\n"
    assert _codes(verifier, source)[0] is False


def test_a_wrong_proof_is_still_rejected(verifier: LeanVerifier) -> None:
    source = _AON + _HEAD + """
example {X : Scheme.{u}} (x : X) : False := exists_affineOpen_mem_le x ⊤ trivial
"""
    assert _codes(verifier, source)[0] is False
