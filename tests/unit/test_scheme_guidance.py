from pals_agent.lean_target import target_headers
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


def _diagnose(request_text: str, source: str) -> list[str]:
    count, headers, preamble = target_headers(source)
    return [
        d.code for d in scheme_statement_diagnostics(request_text, count, headers, preamble)
    ]


def test_cues_fire_on_scheme_requests_only() -> None:
    assert is_scheme_request(SPEC_QC)
    assert is_scheme_request("閉埋め込みは分離的であることを示せ")
    assert is_scheme_request("可換環 R に対し、スキーム Spec R は準コンパクトであることを示せ")
    for text in (
        "Show that a numerical scheme is stable.",
        "State the axiom scheme of induction.",
        "Prove that (x+1)^2 >= 0 for specific x.",
        "Show the derivative of x^3 is 3x^2.",
        "Compare the stability of schemes for the heat equation.",
        "the difference between schemes: forward Euler and backward Euler",
        "Show an integral scheme of order 2 converges (numerical).",
        "Specs are unique.",
        "数値スキームの安定性を示せ",
        "差分スキームの収束を示せ",
        "認証スキームの安全性を示せ",
    ):
        assert not is_scheme_request(text), text
        assert scheme_guidance(text) == ""


def test_guidance_is_present_for_schemes() -> None:
    assert "Spec (CommRingCat.of R)" in scheme_guidance(SPEC_QC)


def test_weakened_statement_is_rejected_and_faithful_one_is_not() -> None:
    assert _diagnose(SPEC_QC, WEAK) == [SCHEME_STATEMENT_CODE]
    assert _diagnose(SPEC_QC, FAITHFUL) == []


def test_scheme_only_in_binders_or_hypotheses_is_accepted() -> None:
    for source in (
        "theorem t (X : Scheme) [IsAffine X] : CompactSpace X := inferInstance",
        "theorem t {X Y : Scheme} (f g : X ⟶ Y) [IsReduced X] (h : f.base = g.base) : f = g := "
        "sorry",
        "theorem t {X Y : Scheme} (f : X ⟶ Y) [IsOpenImmersion f] : Mono f := inferInstance",
    ):
        assert _diagnose("Show that a morphism of schemes is a monomorphism.", source) == []


def test_ring_and_topology_words_do_not_count_as_scheme_vocabulary() -> None:
    weak = (
        "theorem t (R : Type*) [CommRing R] (x : R) (h : IsIntegral ℤ x) :\n"
        "    IsCompact ((⊤ : TopologicalSpace.Opens (PrimeSpectrum R)) : Set _) := sorry"
    )
    assert _diagnose(SPEC_QC, weak) == [SCHEME_STATEMENT_CODE]


def test_topological_request_may_be_answered_with_prime_spectrum() -> None:
    request = (
        "Show that the topological space Spec R is connected iff R has no nontrivial "
        "idempotents."
    )
    assert _diagnose(request, WEAK) == []


def test_scheme_request_without_any_theorem_is_rejected() -> None:
    no_theorem = "import Mathlib\n/- no theorem here -/\n"
    assert _diagnose(SPEC_QC, no_theorem) == [SCHEME_STATEMENT_CODE]
    assert _diagnose("Show 1+1=2.", "import Mathlib\n") == []


def test_scheme_bound_by_variable_or_def_or_let_is_accepted() -> None:
    request = "Show that an affine scheme is quasi-compact."
    for source in (
        "variable (X : Scheme) [IsAffine X]\ntheorem t : CompactSpace X := inferInstance",
        "def Y : Scheme := Spec (CommRingCat.of ℤ)\ntheorem t : CompactSpace Y := sorry",
        "theorem t : let X := Spec (CommRingCat.of ℤ); QuasiCompact (𝟙 X) := by sorry",
    ):
        assert _diagnose(request, source) == [], source


def test_more_cue_forms() -> None:
    for text in (
        "Show closed immersions are separated.",
        "Show that a morphism of finite type between schemes is quasi-compact.",
        "Show that Spec ℤ is connected.",
        "Euler sequence on projective schemes",
        "the Euler characteristic of an affine scheme is 1",
        "可換環 R のスキーム Spec R は連結か",
    ):
        assert is_scheme_request(text), text
    for text in ("環境スキームの循環を示せ", "階層スキームの設計", "可換図式のスキーム"):
        assert not is_scheme_request(text), text


def test_unparseable_header_is_held_back_not_rejected() -> None:
    assert [d.code for d in scheme_statement_diagnostics(SPEC_QC, 1, [], "")] == []


def test_pipeline_validation_reports_the_code() -> None:
    request = ProofRequest(id="p", prompt=SPEC_QC)
    assert SCHEME_STATEMENT_CODE in [d.code for d in validate_generated_lean(request, WEAK)]
    assert SCHEME_STATEMENT_CODE not in [
        d.code for d in validate_generated_lean(request, FAITHFUL)
    ]


def test_pinned_formal_statement_skips_the_vocabulary_check() -> None:
    request = ProofRequest(id="p", prompt=SPEC_QC, formal_statement="theorem t : True")
    assert SCHEME_STATEMENT_CODE not in [d.code for d in validate_generated_lean(request, WEAK)]


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
