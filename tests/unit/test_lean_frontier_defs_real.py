"""Real-Lean checks of ``stacks-frontier-defs-4.35`` (statements may use Frontier definitions).

Opt-in: set ``PALS_FRONTIER_TEST_WORKSPACE`` to a ``lean-workspaces/stacks-4.35`` copy on which
``lake exe cache get`` has run and these modules are built (needs the pinned toolchain, not PATH's):

    lake build StacksFrontier.AlgebraicGeometry.Scheme.AffineOpenNeighborhood \
               StacksFrontier.AlgebraicGeometry.Etale.FiniteEtaleIrreducibleCover0551b
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_audit import FRONTIER_DUPLICATE_DIAGNOSTIC, TRUST_LEVEL_DIAGNOSTIC
from pals_agent.lean_profiles import resolve_profile
from pals_agent.models import VerificationResult
from pals_agent.pipeline import _validate_formal_harness

_WORKSPACE = os.environ.get("PALS_FRONTIER_TEST_WORKSPACE")
pytestmark = pytest.mark.skipif(not _WORKSPACE, reason="PALS_FRONTIER_TEST_WORKSPACE is not set")

_NAME = "stacks-frontier-defs-4.35"
_AON = "import StacksFrontier.AlgebraicGeometry.Scheme.AffineOpenNeighborhood\n"
_RESIDUE = "import StacksFrontier.AlgebraicGeometry.Etale.FiniteEtaleIrreducibleCover0551b\n"
_HEAD = "open AlgebraicGeometry CategoryTheory\nuniverse u\n"
_FRONTIER_DEF = "AlgebraicGeometry.IsAffineOpen.residueFieldIso"
# The statement uses `IsAffineOpen.residueFieldIso`, a Frontier definition that shares its last
# name component with the Mathlib definition `Scheme.Spec.residueFieldIso`.
_PINNED = """theorem t {X : Scheme.{u}} {U : X.Opens} (hU : IsAffineOpen U)
    (q : PrimeSpectrum Γ(X, U)) :
    (hU.residueFieldIso q).hom ≫ (hU.residueFieldIso q).inv = 𝟙 _"""
_RESIDUE_THEOREM = _RESIDUE + _HEAD + "\n" + _PINNED + " :=\n  (hU.residueFieldIso q).hom_inv_id\n"


def _options(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return {
        "timeout_seconds": 300,
        "child_path": f"{Path.home()}/.elan/bin:/usr/bin:/bin",
        "elan_home": f"{Path.home()}/.elan",
        "scratch_dir": tmp_path_factory.mktemp("frontier-defs-scratch"),
    }


@pytest.fixture(scope="module")
def options(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _options(tmp_path_factory)


@pytest.fixture(scope="module")
def verifier(options: dict[str, Any]) -> Iterator[LeanVerifier]:
    assert _WORKSPACE is not None
    profile = resolve_profile(_NAME)
    workspace = Path(_WORKSPACE)
    profile.validate_workspace(workspace)
    yield LeanVerifier(project_dir=workspace, library_profile=profile, **options)


def _codes(result: VerificationResult) -> list[str]:
    return [diagnostic.code or "" for diagnostic in result.diagnostics]


def _trust(result: VerificationResult) -> dict[str, Any]:
    diagnostic = next(d for d in result.diagnostics if d.code == TRUST_LEVEL_DIAGNOSTIC)
    assert diagnostic.metadata is not None
    return diagnostic.metadata


def test_a_mathlib_only_proof_is_recorded_as_mathlib(verifier: LeanVerifier) -> None:
    result = verifier.verify("import Mathlib\ntheorem t : (2 : ℝ) + 2 = 4 := by norm_num\n")

    assert result.success is True and _codes(result)[0] == "lean.verified"
    assert _trust(result)["trust_level"] == "mathlib"
    assert FRONTIER_DUPLICATE_DIAGNOSTIC not in _codes(result)


def test_a_frontier_lemma_in_the_proof_only_is_frontier_proof(verifier: LeanVerifier) -> None:
    source = _AON + _HEAD + """
theorem t {X : Scheme.{u}} (x : X) (U : X.Opens) (hx : x ∈ U) :
    ∃ V : X.affineOpens, x ∈ V.1 ∧ V.1 ≤ U :=
  exists_affineOpen_mem_le x U hx
"""
    result = verifier.verify(source)

    assert result.success is True
    metadata = _trust(result)
    assert metadata["trust_level"] == "frontier_proof"
    assert metadata["frontier_statement_constants"] == []
    assert "StacksFrontier" in metadata["proof_roots"]


def test_a_statement_with_a_frontier_definition_is_accepted_and_labelled(
    verifier: LeanVerifier,
) -> None:
    result = verifier.verify(_RESIDUE_THEOREM)

    assert result.success is True and _codes(result)[0] == "lean.verified"
    metadata = _trust(result)
    assert metadata["trust_level"] == "frontier_statement"
    assert metadata["frontier_statement_constants"] == [_FRONTIER_DEF]
    assert metadata["frontier_modules"] == [
        "StacksFrontier.AlgebraicGeometry.Etale.FiniteEtaleIrreducibleCover0551b"
    ]
    trust = next(d for d in result.diagnostics if d.code == TRUST_LEVEL_DIAGNOSTIC)
    assert trust.severity == "warning" and "Frontier (human-unreviewed)" in trust.message


def test_a_frontier_definition_resembling_a_mathlib_one_is_recorded_not_rejected(
    verifier: LeanVerifier,
) -> None:
    result = verifier.verify(_RESIDUE_THEOREM)

    assert result.success is True
    duplicate = next(d for d in result.diagnostics if d.code == FRONTIER_DUPLICATE_DIAGNOSTIC)
    assert duplicate.severity == "warning" and duplicate.metadata is not None
    assert {
        "frontier": _FRONTIER_DEF,
        "other": "AlgebraicGeometry.Scheme.Spec.residueFieldIso",
        "reason": "same_name",
    } in duplicate.metadata["duplicates"]


def test_a_frontier_definition_behind_a_local_definition_is_still_found(
    verifier: LeanVerifier,
) -> None:
    source = _RESIDUE + _HEAD + """
noncomputable def chart {X : Scheme.{u}} {U : X.Opens} (hU : IsAffineOpen U)
    (q : PrimeSpectrum Γ(X, U)) := hU.residueFieldIso q
theorem t {X : Scheme.{u}} {U : X.Opens} (hU : IsAffineOpen U)
    (q : PrimeSpectrum Γ(X, U)) : (chart hU q).hom ≫ (chart hU q).inv = 𝟙 _ :=
  (chart hU q).hom_inv_id
"""
    result = verifier.verify(source)

    assert result.success is True
    assert _trust(result)["trust_level"] == "frontier_statement"


def test_sorry_extra_axioms_and_native_evaluation_stay_forbidden(verifier: LeanVerifier) -> None:
    sorry = verifier.verify(_AON + "theorem t : 1 = 1 := by sorry\n")
    axiom = verifier.verify(_AON + "axiom bad : False\ntheorem t : False := bad\n")
    native = verifier.verify("import Mathlib\ntheorem t : 2 + 2 = 4 := by native_decide\n")
    reduce = verifier.verify(
        "import Mathlib\ntheorem t : 2 + 2 = 4 := by decide +native\n"
    )

    assert (sorry.success, _codes(sorry)) == (False, ["lean.disallowed_placeholder"])
    assert (axiom.success, _codes(axiom)) == (False, ["lean.disallowed_trusted_declaration"])
    assert not native.success and "lean.disallowed_native_evaluation" in _codes(native)
    assert not reduce.success and "lean.disallowed_native_evaluation" in _codes(reduce)
    for result in (sorry, axiom, native, reduce):
        assert TRUST_LEVEL_DIAGNOSTIC not in _codes(result)  # nothing is labelled on a failure


def test_a_wrong_proof_is_rejected_by_the_kernel_path(verifier: LeanVerifier) -> None:
    source = _AON + _HEAD + """
example {X : Scheme.{u}} (x : X) : False := exists_affineOpen_mem_le x ⊤ trivial
"""

    assert verifier.verify(source).success is False


def test_a_module_that_was_not_built_cannot_be_imported(verifier: LeanVerifier) -> None:
    result = verifier.verify("import StacksFrontier.NoSuchModule\nexample : True := trivial\n")

    assert result.success is False


def test_a_statement_reaching_an_unreviewed_non_frontier_root_is_still_rejected(
    options: dict[str, Any],
) -> None:
    assert _WORKSPACE is not None
    profile = resolve_profile(_NAME)
    assert profile.statement_trusted_roots is not None
    # A stand-in for "a library nobody reviewed that is not the Frontier": Mathlib is not trusted.
    stricter = dataclasses.replace(
        profile,
        name="stacks-test-defs-4.35",
        statement_trusted_roots=tuple(
            root for root in profile.statement_trusted_roots if root != "Mathlib"
        ),
    )
    verifier = LeanVerifier(project_dir=Path(_WORKSPACE), library_profile=stricter, **options)

    result = verifier.verify("import Mathlib\ntheorem t : (2 : ℝ) + 2 = 4 := by norm_num\n")

    assert result.success is False
    assert _codes(result) == ["lean.statement_uses_untrusted_library"]


def test_a_pinned_statement_is_kept_only_when_the_proof_proves_exactly_it(
    verifier: LeanVerifier,
) -> None:
    exact = verifier.verify(_RESIDUE_THEOREM)
    weaker = _RESIDUE + _HEAD + "\ntheorem t : True := trivial\n"
    weak_result = verifier.verify(weaker)

    # Lean and the profile both accept the weaker file: they do not know what was meant.
    assert exact.success is True and weak_result.success is True
    # The pinned `formal_statement` is what tells them apart.
    assert _validate_formal_harness(formal_statement=_PINNED, lean_code=_RESIDUE_THEOREM) == []
    mismatch = _validate_formal_harness(formal_statement=_PINNED, lean_code=weaker)
    assert [d.code for d in mismatch] == ["lean.formal_harness_mismatch"]
