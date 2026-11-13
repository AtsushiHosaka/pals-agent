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
