"""Choose the library profile a request needs, from its text alone.

Measured (docs/algebraic-geometry-e2e-part3): nothing in the worker picked a verification
environment for a question. ``ProofPipeline.run_statement`` takes ``library_profile`` but its
callers never pass one, and the production worker verifies through the API (``api_reconcile``),
which serves one profile. This module is the missing decision, as a pure function:

* sheaf cohomology, derived functors and higher direct images are not in Mathlib; a proof can only
  use unreviewed Stacks Frontier lemmas → ``stacks-frontier-4.35`` (lemmas in proofs only);
* Picard groups, ample line bundles and similar objects have no Mathlib definition at all, so the
  statement itself needs Frontier definitions → ``stacks-frontier-defs-4.35``;
* every other request keeps the default profile (``None``).

The result is a request, not a grant: the profile must still be served by the verifier that
checks the proof, and its flag must be open (``LibraryProfileNotEnabled`` otherwise; never a silent
fallback to the default library). Local verification only; the production worker is unchanged.
"""

from __future__ import annotations

import re
from typing import Final

FRONTIER_PROOF_PROFILE: Final = "stacks-frontier-4.35"
FRONTIER_DEFS_PROFILE: Final = "stacks-frontier-defs-4.35"

# Words that only mean something here in the setting of schemes and sheaves; anywhere else
# ("line bundle on a manifold", "cohomology of groups", "acyclic graph") they must not select a
# Frontier profile, so the setting is required in addition to the term.
_SCHEME_SETTING: Final = re.compile(
    r"\b(?:schemes?|sheaf|sheaves|quasi-?coherent|structure\s+sheaf|Spec|Proj|"
    r"affine\s+morphisms?|morphisms?\s+of\s+schemes)\b|スキーム|構造層|準連接|アフィン射",
)
_NEEDS_DEFINITIONS: Final = re.compile(
    r"\b(?:picard\s+group|ample|very\s+ample|invertible\s+(?:sheaf|sheaves)|line\s+bundles?|"
    r"cartier\s+divisors?|blow-?ups?|algebraic\s+(?:space|stack)s?)\b|豊富|ピカール|可逆層|"
    r"ブローアップ|代数的空間|代数的スタック",
    re.IGNORECASE,
)
_NEEDS_LEMMAS: Final = re.compile(
    r"\b(?:sheaf\s+cohomology|cohomology\s+(?:of|on|with)|derived\s+(?:functors?|pushforward)|"
    r"higher\s+direct\s+images?|right\s+derived|ext\s+groups?|"
    r"cech\s+cohomology|čech\s+cohomology|flasque|acyclic)\b|"
    r"\bR\s*\^?\s*[A-Za-z0-9]+\s*f_\*|層(?:の)?コホモロジー|高次順像|導来関手|チェックコホモロジー",
    re.IGNORECASE,
)
_NUMERICAL: Final = re.compile(
    r"\b(?:numerical|finite[- ]difference|hash)\b|数値|差分", re.IGNORECASE
)


def select_library_profile(request_text: str) -> str | None:
    """The non-default profile this request needs, or ``None`` for the default library."""
    if not request_text or _NUMERICAL.search(request_text):
        return None
    if not _SCHEME_SETTING.search(request_text):
        return None
    if _NEEDS_DEFINITIONS.search(request_text):
        return FRONTIER_DEFS_PROFILE
    if _NEEDS_LEMMAS.search(request_text):
        return FRONTIER_PROOF_PROFILE
    return None
