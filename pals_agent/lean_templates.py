"""Deterministic Lean proof templates with checked variable substitution.

A template is a Lean proof that was verified once with fixed placeholder names.  Rendering it
substitutes the learner-facing names (function variable, fixed point, epsilon, delta, theorem
name) and nothing else.  The substitution is the only code path that edits the proof text, and it
is closed: every binding must be a plain Lean identifier, the bindings must be pairwise distinct,
and none may collide with a name the template itself uses (a local hypothesis, a Mathlib lemma
or a Lean keyword).  A colliding binding is refused instead of renamed, so the rendered text is
always the verified template up to a bijective renaming of binders.

Nothing here is trusted as proof: the rendered source goes through the same preflight and the
same Lean compile as a model-written candidate, and a compile failure falls back to the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from pals_agent.lean_target import extract_single_target_declaration, matches_x_squared_continuity
from pals_agent.models import ProofRequest
from pals_agent.request_proposition import parse_request

PROVER_ID: Final = "pals.template.x-squared-epsilon-delta.v1"

# Placeholder sentinels: ASCII, upper case, impossible to mistake for a Lean name used below.
_PLACEHOLDER = re.compile(r"(?<![\w'.])PALS_[A-Z]+(?![\w'])")

# Local names and global identifiers the template spells itself.  A binding equal to one of
# these would capture or shadow it.
_TEMPLATE_NAMES: Final = frozenset(
    {
        "Real", "Metric", "continuous_iff", "min", "abs", "dist", "dsimp", "simp", "simpa",
        "ring", "ring_nf", "field_simp", "linarith", "positivity", "refine", "intro", "exact",
        "calc", "rw", "have", "let", "lt_min", "div_pos", "lt_of_lt_of_le", "lt_of_le_of_lt",
        "abs_add_le", "abs_mul", "abs_nonneg", "mul_le_mul_of_nonneg_left",
        "mul_lt_mul_of_pos_right", "Topology", "Mathlib",
        # hypothesis names
        "hε", "hden", "hy", "hy1", "hyabs", "hyplus", "htri", "hfactor", "hpoly", "hbound",
        "hδle", "hposden", "hmul", "hltδ", "hlt",
    }
)

_RESERVED: Final = frozenset(
    {
        "fun", "by", "at", "in", "do", "if", "then", "else", "let", "have", "show", "from",
        "with", "match", "where", "end", "open", "import", "theorem", "lemma", "example",
        "def", "namespace", "section", "variable", "universe", "instance", "structure",
        "class", "inductive", "abbrev", "set_option", "attribute", "macro", "syntax",
        "notation", "infix", "prefix", "postfix", "deriving", "mutual", "private", "protected",
        "noncomputable", "partial", "unsafe", "calc", "suffices", "this", "Type", "Prop",
        "Sort", "forall", "exists", "sorry", "rec", "mut", "return", "for", "unless", "try",
        "catch", "finally", "λ", "Π", "Σ", "π",
    }
)

# Latin or Greek letter followed by up to seven letters, digits, primes or underscores.
_LEAN_NAME = re.compile(r"[A-Za-zα-ωΑ-Ω][A-Za-z0-9α-ωΑ-Ω_']{0,7}\Z")
_THEOREM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_']{0,63}\Z")


class TemplateBindingError(ValueError):
    """The requested names cannot be substituted safely."""


@dataclass(frozen=True, slots=True)
class XSquaredBindings:
    """Learner-facing names for the epsilon-delta proof of continuity of ``x ↦ x ^ 2``.

    ``variable`` is the function variable of the statement, ``point`` the fixed point of the
    proof and ``moving`` the point written as ``x`` with ``|x - a| < δ`` in the argument.  The
    statement ``Continuous (fun variable : ℝ => variable ^ 2)`` itself is fixed.
    """

    theorem: str = "x2_continuous"
    variable: str = "x"
    point: str = "a"
    moving: str = "x"
    epsilon: str = "ε"
    delta: str = "δ"

    def as_mapping(self) -> dict[str, str]:
        return {
            "THEOREM": self.theorem,
            "VAR": self.variable,
            "POINT": self.point,
            "MOVING": self.moving,
            "EPS": self.epsilon,
            "DELTA": self.delta,
        }


# The placeholders stand for exactly the names bound in XSquaredBindings.  PALS_VAR and
# PALS_MOVING may be the same name because they live in disjoint scopes (the statement's lambda
# and the ``intro`` after ``Metric.continuous_iff``).
_X_SQUARED_TEMPLATE: Final = """\
import Mathlib

open scoped Topology

theorem PALS_THEOREM : Continuous (fun PALS_VAR : ℝ => PALS_VAR ^ 2) := by
  rw [Metric.continuous_iff]
  intro PALS_POINT PALS_EPS hε
  let PALS_DELTA : ℝ := min 1 (PALS_EPS / (2 * |PALS_POINT| + 1))
  refine ⟨PALS_DELTA, ?_, ?_⟩
  · dsimp [PALS_DELTA]
    have hden : 0 < (2 * |PALS_POINT| + 1 : ℝ) := by
      positivity
    exact lt_min (by positivity) (div_pos hε hden)
  · intro PALS_MOVING hy
    have hy1 : |PALS_MOVING - PALS_POINT| < 1 := by
      exact lt_of_lt_of_le hy (by simp [PALS_DELTA])
    have hyabs : |PALS_MOVING| ≤ |PALS_POINT| + 1 := by
      have htri : |PALS_MOVING| ≤ |PALS_MOVING - PALS_POINT| + |PALS_POINT| := by
        calc
          |PALS_MOVING| = |(PALS_MOVING - PALS_POINT) + PALS_POINT| := by ring_nf
          _ ≤ |PALS_MOVING - PALS_POINT| + |PALS_POINT| := abs_add_le _ _
      linarith
    have hyplus : |PALS_MOVING + PALS_POINT| ≤ 2 * |PALS_POINT| + 1 := by
      have htri : |PALS_MOVING + PALS_POINT| ≤ |PALS_MOVING| + |PALS_POINT| := abs_add_le _ _
      linarith
    have hfactor :
        |PALS_MOVING ^ 2 - PALS_POINT ^ 2|
          = |PALS_MOVING - PALS_POINT| * |PALS_MOVING + PALS_POINT| := by
      have hpoly :
          PALS_MOVING ^ 2 - PALS_POINT ^ 2
            = (PALS_MOVING - PALS_POINT) * (PALS_MOVING + PALS_POINT) := by
        ring
      rw [hpoly, abs_mul]
    have hbound :
        |PALS_MOVING ^ 2 - PALS_POINT ^ 2|
          ≤ |PALS_MOVING - PALS_POINT| * (2 * |PALS_POINT| + 1) := by
      rw [hfactor]
      exact mul_le_mul_of_nonneg_left hyplus (abs_nonneg (PALS_MOVING - PALS_POINT))
    have hδle : PALS_DELTA ≤ PALS_EPS / (2 * |PALS_POINT| + 1) := by
      simp [PALS_DELTA]
    have hposden : 0 < (2 * |PALS_POINT| + 1 : ℝ) := by
      positivity
    have hmul : |PALS_MOVING - PALS_POINT| * (2 * |PALS_POINT| + 1) < PALS_EPS := by
      have hltδ : |PALS_MOVING - PALS_POINT| < PALS_EPS / (2 * |PALS_POINT| + 1) :=
        lt_of_lt_of_le hy hδle
      calc
        |PALS_MOVING - PALS_POINT| * (2 * |PALS_POINT| + 1) <
            (PALS_EPS / (2 * |PALS_POINT| + 1)) * (2 * |PALS_POINT| + 1) :=
          mul_lt_mul_of_pos_right hltδ hposden
        _ = PALS_EPS := by field_simp
    have hlt : |PALS_MOVING ^ 2 - PALS_POINT ^ 2| < PALS_EPS := lt_of_le_of_lt hbound hmul
    simpa [Real.dist_eq] using hlt
"""


def validate_name(name: str, *, theorem: bool = False) -> str:
    pattern = _THEOREM_NAME if theorem else _LEAN_NAME
    if not isinstance(name, str) or pattern.match(name) is None:
        raise TemplateBindingError("a binding must be a short Lean identifier")
    if name in _RESERVED or name in _TEMPLATE_NAMES:
        raise TemplateBindingError("a binding collides with a keyword or a template name")
    return name


def render_x_squared_epsilon_delta(bindings: XSquaredBindings | None = None) -> str:
    """Return the epsilon-delta proof of ``Continuous (fun x : ℝ => x ^ 2)``.

    The function variable and the moving point may share a name (they live in disjoint scopes);
    the theorem, point, epsilon and delta names must be pairwise distinct from each other and
    from both of those.
    """
    mapping = (bindings or XSquaredBindings()).as_mapping()
    for key, name in mapping.items():
        validate_name(name, theorem=key == "THEOREM")
    keys = sorted(mapping)
    for index, first in enumerate(keys):
        for second in keys[index + 1 :]:
            if {first, second} == {"VAR", "MOVING"}:
                continue
            if mapping[first] == mapping[second]:
                raise TemplateBindingError("bindings must be pairwise distinct")

    def replace(match: re.Match[str]) -> str:
        key = match.group(0).removeprefix("PALS_")
        try:
            return mapping[key]
        except KeyError as error:
            raise TemplateBindingError("template placeholder has no binding") from error

    rendered = _PLACEHOLDER.sub(replace, _X_SQUARED_TEMPLATE)
    if "PALS_" in rendered:
        raise TemplateBindingError("template placeholder was not substituted")
    return rendered


# --- Request recognition -------------------------------------------------------------------

_X_SQUARED_DRAFT_ID: Final = "continuous_square"
_SQUARED_VARIABLE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z])(?:²|\^2(?![0-9])|\^\{2\})")
_POINT_CANDIDATES: Final = ("a", "c", "p", "q")


@dataclass(frozen=True, slots=True)
class TemplateProof:
    lean_code: str
    prover_id: str
    bindings: XSquaredBindings


def template_proof_for_request(request: ProofRequest) -> TemplateProof | None:
    """Return a verified-template proof when the request is exactly the continuity of x².

    Recognised: the retrieval marked the request as an exact equivalent of the seed Draft
    ``continuous_square``, or the vocabulary grammar reads the whole request as exactly
    ``Continuous (fun v : ℝ => v ^ 2)``: the structure (function, property, domain) decides, in
    any language the table lists, and any word the table does not consume (a negation, another
    property, a restricted domain, an extra instruction) makes it a miss.  The older Japanese
    wording check is not used here: it did not see a negation (連続でない, 不連続).
    A learner-supplied formal statement is never replaced.  Anything else returns ``None`` and
    stays with the model.
    """
    if request.formal_statement is not None:
        return None
    grammar_variable = _grammar_square_variable(request.prompt)
    if not (_exact_square_draft(request) or grammar_variable is not None):
        return None
    bindings = _bindings_for_prompt(request.prompt, grammar_variable)
    try:
        lean_code = render_x_squared_epsilon_delta(bindings)
    except TemplateBindingError:
        return None
    return TemplateProof(lean_code=lean_code, prover_id=PROVER_ID, bindings=bindings)


def template_proof_for_sketch(request: ProofRequest, sketch_lean_code: str) -> TemplateProof | None:
    """The template when the Sketch's own Lean statement is exactly the continuity of x².

    A safety net behind the wording grammar: the Sketch model has already turned whatever the
    learner wrote (any language or phrasing the grammar does not list) into a Lean statement, and
    :func:`matches_x_squared_continuity` reads that statement, not the words.  The prove stage is
    then replaced by the verified template; nothing else about the request changes.
    """
    if request.formal_statement is not None:
        return None
    target = extract_single_target_declaration(sketch_lean_code)
    if target is None or not matches_x_squared_continuity(target.proposition):
        return None
    bindings = XSquaredBindings()
    try:
        lean_code = render_x_squared_epsilon_delta(bindings)
    except TemplateBindingError:
        return None
    return TemplateProof(lean_code=lean_code, prover_id=PROVER_ID, bindings=bindings)


def _exact_square_draft(request: ProofRequest) -> bool:
    if (
        request.exact_equivalence
        and request.draft is not None
        and request.draft.id == _X_SQUARED_DRAFT_ID
    ):
        return True
    return any(
        context.exact_equivalence and context.source_draft_id == _X_SQUARED_DRAFT_ID
        for context in request.related_draft_contexts
    )


def _grammar_square_variable(prompt: str) -> str | None:
    """The variable when the vocabulary grammar reads the request as exactly continuity of v².

    The grammar covers every wording its table lists (English included), and any leftover word
    is a miss, so this is as conservative as the Japanese-only wording check above.
    """
    parsed = parse_request(prompt)
    if (
        parsed is None
        or parsed.function_id != "power"
        or parsed.property_id != "continuous"
        or dict(parsed.slots).get("k") != "2"
    ):
        return None
    return parsed.variable


def _bindings_for_prompt(prompt: str, grammar_variable: str | None = None) -> XSquaredBindings:
    """Use the learner's single squared variable (``t²``), else ``x``; keep ε and δ fixed.

    The names ε and δ stay as they are because the epsilon-delta preflight looks for them.
    """
    compact = re.sub(r"\s+", "", prompt)
    letters = {match.group(1) for match in _SQUARED_VARIABLE.finditer(compact)}
    variable = "x"
    if grammar_variable is not None:
        letters = {grammar_variable}
    if len(letters) == 1:
        (candidate,) = letters
        try:
            validate_name(candidate)
        except TemplateBindingError:
            candidate = "x"
        variable = candidate
    point = next(name for name in _POINT_CANDIDATES if name != variable)
    return XSquaredBindings(variable=variable, point=point, moving=variable)
