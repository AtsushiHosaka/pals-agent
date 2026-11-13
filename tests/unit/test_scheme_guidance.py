from pals_agent.lean_target import target_propositions
from pals_agent.models import ProofRequest
from pals_agent.pipeline import validate_generated_lean
from pals_agent.scheme_guidance import (
    SCHEME_STATEMENT_CODE,
    is_scheme_request,
    scheme_guidance,
    scheme_statement_diagnostics,
)

SPEC_QC = "Show that for every commutative ring R, the scheme Spec R is quasi-compact."
WEAK = (
    "import Mathlib\ntheorem t (R : Type*) [CommRing R] :\n"
    "    IsCompact (Set.univ : Set (PrimeSpectrum R)) := by\n  exact isCompact_univ\n"
)
FAITHFUL = (
    "import Mathlib\nopen AlgebraicGeometry\n"
    "theorem t (R : CommRingCat) : CompactSpace (Spec R) := inferInstance\n"
)


def test_cues_fire_on_scheme_requests_only() -> None:
    assert is_scheme_request(SPEC_QC)
    assert is_scheme_request("閉埋め込みは分離的であることを示せ")
    for text in (
        "Show that a numerical scheme is stable.",
        "State the axiom scheme of induction.",
        "Prove that (x+1)^2 >= 0 for specific x.",
        "Show the derivative of x^3 is 3x^2.",
    ):
        assert not is_scheme_request(text)
        assert scheme_guidance(text) == ""


def test_guidance_is_present_for_schemes() -> None:
    assert "Spec (CommRingCat.of R)" in scheme_guidance(SPEC_QC)


def test_weakened_statement_is_rejected_and_faithful_one_is_not() -> None:
    weak = scheme_statement_diagnostics(SPEC_QC, target_propositions(WEAK))
    assert [d.code for d in weak] == [SCHEME_STATEMENT_CODE]
    assert scheme_statement_diagnostics(SPEC_QC, target_propositions(FAITHFUL)) == []


def test_other_requests_and_unparseable_code_are_not_judged() -> None:
    assert scheme_statement_diagnostics("Show 1+1=2.", target_propositions(WEAK)) == []
    assert scheme_statement_diagnostics("Show 1+1=2.", []) == []


def test_scheme_request_without_any_theorem_is_rejected() -> None:
    codes = [d.code for d in scheme_statement_diagnostics(SPEC_QC, [])]
    assert codes == [SCHEME_STATEMENT_CODE]


def test_pipeline_validation_reports_the_code() -> None:
    request = ProofRequest(id="p", prompt=SPEC_QC)
    codes = [d.code for d in validate_generated_lean(request, WEAK)]
    assert SCHEME_STATEMENT_CODE in codes
    assert SCHEME_STATEMENT_CODE not in [d.code for d in validate_generated_lean(request, FAITHFUL)]


def _verification(success: bool, *diagnostics):  # type: ignore[no-untyped-def]
    from pals_agent.models import VerificationResult

    return VerificationResult(success, list(diagnostics), "", "", 1)


def test_library_trust_is_reported_for_verified_results() -> None:
    from pals_agent.models import Diagnostic, library_trust_of

    assert library_trust_of(_verification(False)) is None
    default = library_trust_of(_verification(True))
    assert default is not None
    assert default["trust_level"] == "mathlib" and default["recorded"] is False
    frontier = Diagnostic(
        severity="warning",
        message="m",
        code="lean.library_trust",
        metadata={"trust_level": "frontier_statement", "frontier_modules": ["A.B"]},
    )
    core = Diagnostic(
        severity="info", message="m", code="lean.library_trust", metadata={"trust_level": "core"}
    )
    got = library_trust_of(_verification(True, core, frontier))
    assert got is not None
    assert got["trust_level"] == "frontier_statement" and got["human_unreviewed"] is True
    assert got["frontier_modules"] == ["A.B"]
