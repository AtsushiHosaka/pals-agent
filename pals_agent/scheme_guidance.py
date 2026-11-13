"""Scheme-theory requests: Mathlib API guidance and a statement-vocabulary check.

Measured failure (docs/algebraic-geometry-e2e-2026-11-14.md): on a scheme-theory question the model
often proved a weaker algebraic or topological lemma instead (``PrimeSpectrum`` compactness for
"Spec R is quasi-compact", a ring-homomorphism lemma for "the stalk is a localization") and
Lean reported ``verified``. Two cheap, deterministic measures, both silent for every other request:

* ``scheme_guidance`` adds the Mathlib names (checked against the pinned Mathlib) the model keeps
  missing, and the rule that the statement must be about ``AlgebraicGeometry.Scheme``.
* ``scheme_statement_diagnostics`` fails a candidate whose theorem statements mention no scheme
  vocabulary at all although the request does, so the repair loop gets a concrete reason.

Both are cue-gated by the request text. The check never accepts anything on its own: a candidate
that passes it is still compiled, audited and reviewed as before.
"""

from __future__ import annotations

import re
from typing import Final

from pals_agent.models import Diagnostic

SCHEME_STATEMENT_CODE: Final = "pals.scheme_statement_weakened"
SCHEME_INCOMPLETE_CODE: Final = "pals.scheme_candidate_incomplete"

# Request cues. Strong cues drive the check; weak cues only add guidance.
_STRONG_CUE: Final = re.compile(
    r"\b(?:(?:affine|projective|noetherian|integral|reduced|separated|quasi-?compact)\s+"
    r"schemes?|morphisms?\s+(?:\w+\s+){0,3}?(?:of|between)\s+schemes|(?:sheaf|sheaves|"
    r"cohomology)\s+on\s+(?:a\s+|an\s+)?schemes?|structure\s+sheaf|quasi-?coherent|"
    r"affine\s+morphisms?|closed\s+immersions?|open\s+immersions?|scheme\s+morphisms?)\b"
    r"|構造層|準連接|アフィン射|閉埋め込み|開埋め込み|固有射",
    re.IGNORECASE,
)
# "Spec" with a capital S only: the spectrum functor, not "specific" or "spec".
_SPEC_CUE: Final = re.compile(r"\bSpec(?:\s+|\s*\()[^\W\d_]|\bSpec(?:\s+|\s*\()[ℤℚℝℂ𝔸𝔽]")
# Japanese "スキーム" also means a numerical or cryptographic scheme: it counts only beside a
# word from algebraic geometry or commutative algebra.
_JA_SCHEME: Final = re.compile(r"スキーム")
_JA_GEOMETRY: Final = re.compile(
    r"(?<![循])環(?!境)|Spec|アフィン|射|(?<![階])層|代数幾何|準コンパクト|可換(?!図式)"
)
# Requests about numerical analysis or cryptography are never scheme-theory requests.
_NOT_SCHEME_THEORY: Final = re.compile(
    r"\b(?:numerical|finite[- ]difference|difference\s+scheme|euler\s+(?:method|scheme|step)|"
    r"runge|heat\s+equation|hash|signature\s+scheme|encryption)\b"
    r"|数値(?:解|計算|積分|スキーム)|差分|ハッシュ|認証|暗号|離散化",
    re.IGNORECASE,
)
_WEAK_CUE: Final = re.compile(
    r"\b(?:sheaf|sheaves|stalk|quasi-?compact|separated\s+morphism|base\s+change)\b|茎|層",
    re.IGNORECASE,
)
# A statement header that talks about schemes uses at least one of these constants or notations.
# Bare ring-level or topological words (``IsIntegral``, ``IsReduced``, ``Opens``, ``stalk``) are
# left out: they also occur in statements about rings and topological spaces.
_STATEMENT_VOCABULARY: Final = re.compile(
    r"\b(?:Scheme|Spec|Proj|AlgebraicGeometry|IsAffine|IsAffineHom|IsAffineOpen|QuasiCompact|"
    r"QuasiSeparated|IsSeparated|IsProper|UniversallyClosed|IsClosedImmersion|IsOpenImmersion|"
    r"IsImmersion|LocallyOfFiniteType|LocallyOfFinitePresentation|StructureSheaf|"
    r"SheafOfModules|LocallyRingedSpace)\b|Γ\(|Spec\.",
)
# A request that itself speaks of the topological space may be answered about ``PrimeSpectrum``.
_TOPOLOGICAL_REQUEST: Final = re.compile(r"topolog|位相", re.IGNORECASE)
_TOPOLOGICAL_VOCABULARY: Final = re.compile(r"\bPrimeSpectrum\b")

_GUIDANCE: Final = """\
Scheme theory (AlgebraicGeometry). The theorem MUST be stated about schemes, not about a ring,
`PrimeSpectrum` or a topological space standing in for them: do not replace the request by an
algebraic or topological lemma, and do not prove only a helper lemma. Prove the whole claim.
Mathlib names, checked against this library version (use them; do not invent others):
- `import Mathlib`; `open AlgebraicGeometry CategoryTheory`.
- For `[CommRing R]` write the scheme as `Spec (CommRingCat.of R)`; for `R : CommRingCat` write
  `Spec R`. Schemes are `Scheme`; morphisms are `X ⟶ Y`.
- Global sections: `Γ(X, ⊤)`; `Scheme.ΓSpecIso R : Γ(Spec R, ⊤) ≅ R`.
- Stalks: `Spec.stalkIso`, `(Spec R).presheaf.stalk x`; `StructureSheaf.stalkIso` for the sheaf.
- Properties are classes: `IsAffine X`, `IsAffineHom f`, `QuasiCompact f`, `IsSeparated f`,
  `IsProper f`, `IsClosedImmersion f`, `IsIntegral X`, `IsReduced X`
  (for a ring: `_root_.IsReduced`).
- Facts to look for first: `affine_isIntegral_iff (R) : IsIntegral (Spec R) ↔ IsDomain R`,
  `quasiCompact_comp`, `quasiCompact_iff_forall_isAffineOpen`,
  `isSeparated_of_mono`, `MorphismProperty.IsStableUnderBaseChange @IsProper`,
  the instance `CompactSpace (Spec R)`.
- Prefer `inferInstance` for a property that is a registered instance; use `exact?` to find a
  lemma. Do not guess a name that is not listed here.
Cohomology of sheaves on schemes (derived pushforward, higher direct images) is not in this
library: if the request needs it, say so in the Draft rather than formalizing a weaker claim.
"""

_EQUIVALENCE_CUE: Final = re.compile(
    r"\b(?:if\s+and\s+only\s+if|iff|equivalent|equivalence)\b|同値|必要十分|⇔|↔", re.IGNORECASE
)
_EQUIVALENCE_GUIDANCE: Final = """\
The request is an equivalence between a property of a scheme (or of `Spec R`, or of its
topological space) and a property of a ring. State ONE theorem `A ↔ B` whose two sides are
exactly the two properties named in the request, and prove BOTH directions. Do not state a
conjunction of separate facts, one direction only, or a lemma about only the ring or only the
space. To pass between the scheme and the ring, state the bridge explicitly as a `have`:
- Topology of the spectrum: `PrimeSpectrum R` is the topological space of `Spec R`; clopen subsets
  correspond to idempotents: `PrimeSpectrum.isIdempotentElemEquivClopens`.
- Connectedness: `connectedSpace_iff_clopen`, `isClopen_iff` (clopen sets of a preconnected
  space are `∅` or `univ`), `isPreconnected_iff_subset_of_disjoint`.
- Irreducible vs the nilradical: `PrimeSpectrum.irreducibleSpace_iff_isPrime_nilradical`.
- Integral / reduced: `affine_isIntegral_iff`, `affine_isReduced_iff`.
- A nontriviality hypothesis (`[Nontrivial R]`) belongs in the statement exactly when the request
  has it (the empty space is not connected).
"""


def _cue_text(*parts: str | None) -> str:
    return "\n".join(part for part in parts if part)


def is_scheme_request(*parts: str | None) -> bool:
    """True when the request text names schemes (strong cue)."""
    text = _cue_text(*parts)
    if _NOT_SCHEME_THEORY.search(text):
        return False
    return bool(
        _STRONG_CUE.search(text)
        or _SPEC_CUE.search(text)
        or (_JA_SCHEME.search(text) and _JA_GEOMETRY.search(text))
    )


def scheme_guidance(*parts: str | None) -> str:
    """The guidance block for a scheme-theory request, else the empty string."""
    text = _cue_text(*parts)
    if is_scheme_request(text) or (
        _WEAK_CUE.search(text)
        and "AlgebraicGeometry" in text
        and not _NOT_SCHEME_THEORY.search(text)
    ):
        if _EQUIVALENCE_CUE.search(text):
            return _GUIDANCE + _EQUIVALENCE_GUIDANCE
        return _GUIDANCE
    return ""


def scheme_statement_diagnostics(
    request_text: str, declaration_count: int, headers: list[str], preamble: str = ""
) -> list[Diagnostic]:
    """Error diagnostics when a scheme request got a candidate with no scheme vocabulary.

    ``headers`` are the full headers (binders, hypotheses and proposition) of the candidate's
    top-level theorem declarations, ``declaration_count`` how many there are and ``preamble`` the
    text before the first one (``variable``, ``def`` lines). A candidate with
    no theorem at all (only comments or definitions) is rejected, since such a file compiles and
    would otherwise count as verified. A declaration whose header cannot be delimited is not
    judged: the check holds back rather than guess.
    """
    if not is_scheme_request(request_text):
        return []
    if declaration_count > 0 and not headers:
        return []
    if declaration_count > len(headers):
        return []
    if _STATEMENT_VOCABULARY.search(preamble) or any(
        _STATEMENT_VOCABULARY.search(header) for header in headers
    ):
        return []
    if _TOPOLOGICAL_REQUEST.search(request_text) and any(
        _TOPOLOGICAL_VOCABULARY.search(header) for header in headers
    ):
        return []
    message = (
        "The request is about schemes, but the candidate has no theorem."
        if declaration_count == 0
        else "The request is about schemes, but no theorem statement mentions a scheme, "
        "`Spec`, a morphism property or another AlgebraicGeometry object: the candidate "
        "proves a weaker algebraic or topological statement."
    )
    return [
        Diagnostic(
            severity="error",
            code=SCHEME_STATEMENT_CODE,
            message=(
                f"{message} State and prove the requested claim itself about "
                "`AlgebraicGeometry.Scheme` (for a ring `R` use `Spec (CommRingCat.of R)`). "
                "Do not replace it by a lemma about rings, `PrimeSpectrum` or topological spaces."
            ),
        )
    ]


_COMMENT: Final = re.compile(r"--[^\n]*|/-.*?-/", re.DOTALL)
# What a model writes when it proves only a part and says so. Measured: every weakened scheme
# candidate that was not rejected by the vocabulary check carried such a comment.
_SELF_DECLARED_INCOMPLETE: Final = re.compile(
    r"\bpartial\s+(?:work|result|results|statement|proof|claim|version|formali[sz]ation|progress)\b|"
    r"\bremains?\s+(?:open|unproved|unproven|to\s+be\s+proved)\b|"
    r"\bnot\s+(?:yet\s+)?(?:proved|proven|established|formali[sz]ed)\s+(?:here|in\s+this)\b|"
    r"\bunproved\b|\bunproven\b|\bno\s+lean\s+theorem\s+is\s+claimed\b|"
    r"\bleft\s+(?:open|unproved)\b|\bcannot\s+verify\b",
    re.IGNORECASE,
)
# A theorem named like a partial result (``foo_partial``); ``partialOrder`` or ``partial_map`` are
# ordinary mathematical names and do not count.
_PARTIAL_NAME: Final = re.compile(r"\b(?:theorem|lemma)\s+[\w.]*_partial\b")


def scheme_incomplete_diagnostics(request_text: str, lean_code: str) -> list[Diagnostic]:
    """Error diagnostics when a scheme request got a candidate that says it is incomplete.

    A candidate whose own comments (or theorem name) declare that the requested claim is only
    partly proved compiles and would otherwise count as verified. The check reads comments only,
    so a proof is never judged by its tactics.
    """
    if not is_scheme_request(request_text):
        return []
    comments = " ".join(match.group(0) for match in _COMMENT.finditer(lean_code))
    if not _SELF_DECLARED_INCOMPLETE.search(comments) and not _PARTIAL_NAME.search(lean_code):
        return []
    return [
        Diagnostic(
            severity="error",
            code=SCHEME_INCOMPLETE_CODE,
            message=(
                "The candidate says in a comment or a name that it proves only part of the "
                "request. Prove the complete requested claim in one theorem, with no `sorry`. If "
                "a needed lemma is missing from Mathlib, prove it inside the theorem with `have`."
            ),
        )
    ]
