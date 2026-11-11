"""General Recipe -> concrete request, decided by Lean's unifier and zero model calls.

A Recipe proves a universal theorem ``G : forall params, Body``.  A request whose formal
statement ``P`` is a specialisation of ``Body`` (exponents, functions, sets, rings, ... replaced by
concrete terms) is answered by compiling

    <Recipe source, unchanged>
    theorem pals_recipe_instance : P := by first | exact G .. | (intros; apply G <;> closers)

with the real Lean.  The elaborator finds every argument by (higher-order) unification; the
declared type of the instance is ``P`` itself, so the kernel can only accept a proof of exactly the
request.  The deterministic back-check on top of that is:

  1. the declared statement in the compiled source is the request's statement (re-derived here
     from the Recipe bytes and the request, never taken from the compiler's output);
  2. Lean reports no error and no ``sorry``;
  3. the instance's proof term really uses the general theorem (a closer such as ``simp`` cannot
     prove the request on its own and masquerade as an instance);
  4. ``#print axioms`` lists only the standard three.

No model decides anything on the success path.  The module is inert unless
``PALS_GENERAL_RECIPE_LANE`` is on (see ``lane_enabled``).  It never edits
``recipe_instantiation`` (the API carries a byte-identical copy of that module).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pals_agent import sandbox
from pals_agent.recipe_instantiation import (
    GENERAL_NAME,
    INSTANCE_NAME,
    InstantiationRejected,
    _parse,
    render_answer,
)
from pals_agent.statement_grammar import refuse_exotic_characters, validate_proposition

SCHEMA_VERSION: Final = "pals.general-recipe-lane.v1"
DEFAULT_CANDIDATES: Final = 4
ALLOWED_AXIOMS: Final = frozenset({"propext", "Classical.choice", "Quot.sound"})
# Closed vocabulary for side goals that remain after the Recipe's conclusion was unified with the
# request.  They only discharge the Recipe's hypotheses; they cannot change the declared statement.
# The standalone file must not silently generalise a free variable (`x + 0 = x` as `∀ x`).
AUTO_OPTIONS: Final = "set_option autoImplicit false\nset_option relaxedAutoImplicit false\n"
REF_NAME: Final = "_pals_ref"  # leading underscore: hidden from exact?/library search


def reference_probe(proposition: str) -> str:
    """Elaborate the request's statement ALONE, then check it is a closed proposition.

    ``PALS_REF_OK=true`` means the statement elaborated (with ``autoImplicit`` off), has no
    metavariables or free variables, and is a ``Prop``.  The reference declaration is never an
    answer (it uses ``sorry``); it is what each instance's type is compared with.
    """
    return (
        f"set_option maxHeartbeats 100000 in\ntheorem {REF_NAME} : {proposition} := by\n  sorry\n"
        "open Lean Elab Command in\n"
        "#eval show CommandElabM Unit from do\n"
        f"  let info ← getConstInfo ``{REF_NAME}\n"
        "  let t := info.type\n"
        "  let isProp ← liftTermElabM do\n"
        "    let s ← Meta.inferType t\n"
        "    return (← Meta.whnf s).isProp\n"
        '  logInfo m!"PALS_REF_OK={!t.hasMVar && !t.hasFVar && isProp}"\n'
    )


def same_probe(instance: str) -> str:
    """Compare the instance's declared type with the reference elaboration of the request."""
    return (
        "open Lean Elab Command in\n"
        "#eval show CommandElabM Unit from do\n"
        f"  let a ← getConstInfo ``{REF_NAME}\n"
        f"  let b ← getConstInfo ``{instance}\n"
        f'  logInfo m!"PALS_SAME_{instance}={{a.type == b.type}}"\n'
    )


# Each closer either closes its goal or fails: `norm_num`/`simp` can succeed while leaving a goal,
# which would stop `first` from backtracking, so they carry `done`.
CLOSERS: Final = (
    "assumption",
    "fun_prop",
    "positivity",
    "(norm_num; done)",
    "linarith",
    "(simp; done)",
)


def lane_enabled(environ: dict[str, str] | None = None) -> bool:
    """Default OFF.  Independent of PALS_RECIPE_INSTANTIATION (it does not use that route)."""
    value = (environ if environ is not None else os.environ).get("PALS_GENERAL_RECIPE_LANE", "")
    return value.strip().lower() in {"on", "true", "1"}


# --- request statement -------------------------------------------------------------------------
def closed_proposition(formal: str) -> str:
    """``example (x : T) : C`` -> ``forall (x : T), C``; a bare proposition is unchanged."""
    refuse_exotic_characters(formal)  # before the whitespace normalisation hides them
    text = " ".join(formal.split())
    if not text.startswith("example"):
        return text
    rest = text[len("example") :].strip()
    depth, colon = 0, None
    for index, character in enumerate(rest):
        if character in "([{⟨⦃":
            depth += 1
        elif character in ")]}⟩⦄":
            depth -= 1
        elif depth == 0 and character == ":" and not rest.startswith(":=", index):
            colon = index
            break
    if colon is None:
        raise InstantiationRejected("request header has no statement")
    binders, body = rest[:colon].strip(), rest[colon + 1 :].strip()
    return f"∀ {binders}, {body}" if binders else body


# --- Recipe pool -------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PoolRecipe:
    recipe_id: str
    lean_code: str
    target_source: str
    answer: str | None = None
    answer_language: str = "ja"
    origin: str = "fixture"

    @property
    def lean_sha256(self) -> str:
        return hashlib.sha256(self.lean_code.encode()).hexdigest()


def load_fixture_recipes(testdata: Path) -> list[PoolRecipe]:
    """The hand-authored ``*-recipe-v1`` cards (statement, proof and stored answer)."""
    pool: list[PoolRecipe] = []
    for card_path in sorted(testdata.glob("*-recipe-v1/card.json")):
        card = json.loads(card_path.read_text())
        source = (card_path.parent / card["source_path"]).read_text()
        pool.append(
            PoolRecipe(
                card["id"], source, card["target_source"], card.get("answer"), "ja", "fixture"
            )
        )
    return pool


def load_recovered_recipes(testdata: Path) -> list[PoolRecipe]:
    """Closed authoring manifests recovered from calculus/linear-algebra cards (no answer)."""
    pool: list[PoolRecipe] = []
    for path in sorted((testdata / "recovered-recipes-v1/manifests").glob("*.json")):
        m = json.loads(path.read_text())
        if m.get("imports") != ["Mathlib"] or m["environment"].get("opens"):
            continue
        name = re.sub(r"\W", "_", m["recipe_id"])
        source = f"import Mathlib\n\ntheorem {name} : {m['target_source']} := {m['proof_body']}\n"
        pool.append(PoolRecipe(m["recipe_id"], source, m["target_source"], None, "ja", "recovered"))
    return pool


def load_test_fixtures(directory: Path) -> list[PoolRecipe]:
    """Test-only general Recipes (``<name>.lean`` with a ``-- target:`` free first theorem)."""
    pool = []
    for path in sorted(directory.glob("*.lean")):
        source = path.read_text()
        target = " ".join(_parse(source, allow_implicit=True)[0].body.split())
        declaration = _parse(source, allow_implicit=True)[0]
        names = "".join(f"({p.name} : {p.type_text}) " for p in declaration.parameters)
        pool.append(
            PoolRecipe(
                f"testfixture.{path.stem}",
                source,
                f"∀ {names.strip()}, {target}" if names else target,
                None,
                "en",
                "test-fixture",
            )
        )
    return pool


# --- deterministic, language-independent candidate ranking --------------------------------------
_TOKEN = re.compile(r"[^\W\d][\w'.]*|[∀∃↔∧∨¬≤≠∈⊆∪∩∫∑∣≡]")
_NOISE = {
    "fun",
    "Type",
    "Prop",
    "Sort",
    "ℝ",
    "ℕ",
    "ℤ",
    "ℚ",
    "x",
    "y",
    "z",
    "n",
    "m",
    "a",
    "b",
    "c",
    "f",
    "g",
    "h",
    "u",
    "v",
    "k",
    "i",
    "j",
    "p",
    "q",
    "r",
    "s",
    "t",
    "e",
    "d",
}


_BINDER_NAMES = re.compile(r"([(\[{⦃])\s*[^\s:()\[\]{}][^:()\[\]{}]*?\s*:")


def features(proposition: str) -> Counter[str]:
    """Constants and operators, not bound names: what the statement is *about*."""
    out: Counter[str] = Counter()
    for token in _TOKEN.findall(_BINDER_NAMES.sub(r"\1 :", proposition)):
        if token in _NOISE or len(token) == 1 and token.isalpha():
            continue
        out[token.rsplit(".", 1)[-1] if token[0].isalpha() else token] += 1
        if "." in token:
            out[token] += 1
    return out


_OPERATOR = re.compile(r"[+\-*/^=<>≤≥]")


def _cosine(query: Counter[str], docs: list[Counter[str]]) -> list[float]:
    df = Counter(token for doc in docs for token in doc)
    total = len(docs) or 1

    def weight(token: str) -> float:
        return math.log(1 + total / (1 + df[token]))

    qn = math.sqrt(sum((c * weight(t)) ** 2 for t, c in query.items())) or 1.0
    scores = []
    for doc in docs:
        dn = math.sqrt(sum((c * weight(t)) ** 2 for t, c in doc.items())) or 1.0
        dot = sum(query[t] * c * weight(t) ** 2 for t, c in doc.items() if t in query)
        scores.append(dot / (qn * dn))
    return scores


def rank_candidates(request: str, pool: list[PoolRecipe]) -> list[tuple[float, PoolRecipe]]:
    """Cosine over IDF-weighted constants, operators as a weak tie-breaker.

    No language filter, no batch limit, no model.  A prefilter only: Lean decides.
    """
    strong = _cosine(features(request), [features(r.target_source) for r in pool])
    weak = _cosine(
        Counter(_OPERATOR.findall(request)),
        [Counter(_OPERATOR.findall(r.target_source)) for r in pool],
    )
    scored = [(s + 0.5 * w, r) for s, w, r in zip(strong, weak, pool, strict=True) if s + w > 0]
    scored.sort(key=lambda item: (-item[0], item[1].recipe_id))
    return scored


# --- the Lean template -------------------------------------------------------------------------
_IMPORT_LINE = re.compile(r"(?m)^import\s+\S+\s*$")
_COMMENT_LINE = re.compile(r"(?m)^\s*--.*$")


@dataclass(frozen=True, slots=True)
class Attempt:
    """One candidate Recipe's part of the combined compile unit."""

    recipe: PoolRecipe
    general_name: str
    instance_name: str
    proposition: str
    text: str  # the Recipe declaration (imports removed) plus its instance theorem


@dataclass(frozen=True, slots=True)
class LaneSource:
    source: str
    proposition: str
    attempts: tuple[Attempt, ...]
    source_sha256: str
    body: str = ""  # the attempts only (no import, options or reference probe)


MAX_BOUND_ALTERNATIVES: Final = 120
_CLOSE_GOALS: Final = "assumption | fun_prop | (norm_num; done)"
_NUMERAL = re.compile(r"(?<![\w.])\d+(?![\w.])")


def bound_alternatives(general: str, parameters: tuple[Any, ...], proposition: str) -> list[str]:
    """Closers for statements that are not syntactic instances (``x * x`` for ``x ^ n``).

    Numeric parameters are tried with the numerals that occur in the statement (and 0, 1, -1);
    other explicit parameters (hypotheses) become ``?_`` goals closed by fixed closers.  Every
    alternative applies ``general`` and leaves the declared type untouched (``convert`` only adds
    equality goals), so it can prove the statement only through the Recipe; a bare ``simp`` is
    deliberately not among them (it can close the goal without the Recipe).
    """
    numeric = [i for i, p in enumerate(parameters) if getattr(p, "kind", None)]
    if not numeric or len(numeric) > 3 or len(parameters) > 6:
        return []
    found = sorted({int(m) for m in _NUMERAL.findall(proposition) if len(m) < 4})[:5]
    derived = {d for m in found for d in (m - 1, (m - 1) // 2, m // 2) if d >= 0}
    ordered: list[str] = []
    for n in [*found, *sorted(derived), 0, 1, 2, 3]:
        if str(n) not in ordered:
            ordered.append(str(n))
    values = [*ordered[:7], "(-1)", "(1 / 2)"]
    alternatives: list[str] = []
    for combo in itertools.product(values, repeat=len(numeric)):
        chosen = dict(zip(numeric, combo, strict=True))
        args = " ".join(chosen.get(i, "?_") for i in range(len(parameters)))
        alternatives.append(f"(refine {general} {args} <;> first | {_CLOSE_GOALS}; done)")
        alternatives.append(
            f"(convert {general} {args} using 1 <;> "
            f"first | (funext x; ring1) | {_CLOSE_GOALS}; done)"
        )
        if len(numeric) == len(parameters):
            # pointwise corollaries of a global Recipe (fixed glue lemmas, G still in the term)
            alternatives.append(f"(exact ({general} {args}).continuousAt)")
            alternatives.append(f"(exact ({general} {args}).differentiableAt)")
        if len(alternatives) >= MAX_BOUND_ALTERNATIVES:
            break
    return alternatives


def _attempt(recipe: PoolRecipe, request: str, index: int, with_bound: bool = False) -> Attempt:
    declaration, masked = _parse(recipe.lean_code, allow_implicit=True)
    proposition = validate_proposition(closed_proposition(request))
    if re.search(rf"(?<![\w'.])({INSTANCE_NAME}|{GENERAL_NAME})(?![\w'.])", masked):
        raise InstantiationRejected("reserved declaration name already used")
    general = declaration.name or GENERAL_NAME
    start, end = declaration.keyword_span
    renamed = recipe.lean_code[start:end] if declaration.name else f"theorem {GENERAL_NAME}"
    recipe_text = recipe.lean_code[:start] + renamed + recipe.lean_code[end:]
    recipe_text = _IMPORT_LINE.sub("", recipe_text).strip("\n")
    leftover = _COMMENT_LINE.sub("", _IMPORT_LINE.sub("", masked)).strip()
    if not leftover.startswith(("theorem", "lemma", "example")):
        raise InstantiationRejected("Recipe has commands before its declaration")
    instance = f"_{INSTANCE_NAME}_{index}"
    arity = len(declaration.parameters)
    closers = " | ".join(CLOSERS)
    alternatives = [f"exact {general}"]
    alternatives += ["exact " + " ".join([general] + ["_"] * k) for k in range(1, arity + 1)]
    if with_bound:
        alternatives += bound_alternatives(general, declaration.parameters, proposition)
    alternatives.append(f"(intros; apply {general} <;> first | {closers})")
    body = "\n".join(f"  | {alternative}" for alternative in alternatives)
    text = (
        f"{recipe_text}\n\n#print axioms {general}\n\n"
        f"set_option maxHeartbeats 100000 in\n"
        f"theorem {instance} : {proposition} := by\n  first\n{body}\n\n"
        f"{same_probe(instance)}"
        f"set_option pp.proofs true in\nset_option pp.fieldNotation false in\n#print {instance}\n"
        f"#print axioms {instance}\n"  # last: a streaming reader sees the term before the verdict
    )
    return Attempt(recipe, general, instance, proposition, text)


BOUND_CANDIDATES: Final = 8
BOUND_MIN_SCORE: Final = 0.5  # the many-alternative stage only for a close structural match


def build_source(
    recipes: list[PoolRecipe], request: str, *, with_bound: bool = False
) -> tuple[LaneSource, list[dict[str, str]]]:
    """One compile unit for several candidates: Mathlib is imported (and mapped) once.

    ``with_bound`` adds the bound-argument closers (many alternatives, so a second stage that
    only runs when the plain alternatives found nothing).
    """
    attempts: list[Attempt] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    imports: list[str] = []
    for recipe in recipes:
        try:
            attempt = _attempt(recipe, request, len(attempts), with_bound)
            if attempt.general_name in seen:
                raise InstantiationRejected("two candidates declare the same name")
        except InstantiationRejected as error:
            rejected.append({"recipe": recipe.recipe_id, "rejected": error.code})
            continue
        seen.add(attempt.general_name)
        attempts.append(attempt)
        for line in _IMPORT_LINE.findall(recipe.lean_code):
            if line.strip() not in imports:
                imports.append(line.strip())
    proposition = validate_proposition(closed_proposition(request))
    attempts_text = "\n".join(a.text for a in attempts)
    source = (
        "\n".join(imports)
        + "\n\n"
        + AUTO_OPTIONS
        + reference_probe(proposition)
        + "\n"
        + attempts_text
    )
    return (
        LaneSource(
            source,
            proposition,
            tuple(attempts),
            hashlib.sha256(source.encode()).hexdigest(),
            attempts_text,
        ),
        rejected,
    )


# --- real Lean ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LeanRunner:
    lean_binary: str
    lean_path: str
    timeout_seconds: float = 120.0
    cwd: str | None = None

    def isolation(self) -> sandbox.Isolation:
        return sandbox.Isolation(self.lean_binary, self.lean_path)

    def run(self, source: str) -> tuple[int, str, float]:
        """One Lean process in the local sandbox; a timeout kills the whole process group."""
        started = time.monotonic()
        with sandbox.new_scratch("pals-lane-") as directory:
            path = Path(directory) / "Instance.lean"
            path.write_text(source)
            isolation = self.isolation()
            proc = subprocess.Popen(
                sandbox.command([self.lean_binary, str(path)], isolation, directory),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **sandbox.popen_kwargs(
                    isolation, directory, cpu_seconds=int(self.timeout_seconds) + 5
                ),
            )
            dog = sandbox.Watchdog(
                proc,
                rss_bytes=sandbox.default_rss_bytes(),
                cpu_seconds=self.timeout_seconds + 5,
            )
            try:
                out, _ = proc.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                sandbox.kill_group(proc)
                return 124, "timeout", time.monotonic() - started
            finally:
                dog.stop()
            if dog.reason:
                return 137, f"killed:{dog.reason}", time.monotonic() - started
            return proc.returncode, out, time.monotonic() - started

    @staticmethod
    def from_workspace(workspace: Path, lake: str = "lake") -> LeanRunner:
        """Resolve the toolchain once (outside any request): lean binary and LEAN_PATH."""

        def lake_out(*cmd: str) -> str:
            return subprocess.run(
                [lake, "env", *cmd], cwd=workspace, capture_output=True, text=True, check=True
            ).stdout.strip()

        return LeanRunner(lake_out("which", "lean"), lake_out("printenv", "LEAN_PATH"))


_VERDICT_LINE = re.compile(
    r"'(\w+)' (?:depends on axioms: \[[^\]]*\]|does not depend on any axioms)"
)
_ERROR_LINE = re.compile(r"\.lean:\d+:\d+: error")


def errored_declarations(output: str) -> set[str]:
    """Names whose elaboration logged an error.

    A deterministic timeout (``maxHeartbeats``) logs an error yet can leave the declaration in the
    environment with no ``sorryAx`` in its axioms, so ``#print axioms`` alone is not a verdict.
    Lean prints each declaration's messages before the next command's output, so the errors
    logged since the previous ``#print axioms`` line belong to the declaration printed next.
    """
    errored: set[str] = set()
    pending = False
    for line in output.splitlines():
        if _ERROR_LINE.search(line):
            pending = True
        match = _VERDICT_LINE.search(line)
        if match:
            if pending:
                errored.add(match.group(1))
            pending = False
    return errored


def _axioms(output: str, name: str) -> set[str] | None:
    match = re.search(rf"'{re.escape(name)}' depends on axioms: \[([^\]]*)\]", output)
    if match:
        return {a.strip() for a in match.group(1).split(",")}
    if f"'{name}' does not depend on any axioms" in output:
        return set()
    return None


def back_check(source: LaneSource, attempt: Attempt, output: str) -> str | None:
    """None when every deterministic check passes for this candidate, else a rejection code.

    The verdict is read per candidate, not from the process exit code: a failing candidate cannot
    veto a succeeding one, and a ``sorry`` or an error inside the instance shows as ``sorryAx``.
    """
    # statement: the declared theorem in the compile unit is exactly the derived proposition
    declared = f"theorem {attempt.instance_name} : {attempt.proposition} := by"
    if declared not in source.source or attempt.proposition != source.proposition:
        return "statement_mismatch"
    if "PALS_REF_OK=true" not in output:
        return "statement_not_elaborated"  # the request's statement alone is not a closed Prop
    if f"PALS_SAME_{attempt.instance_name}=true" not in output:
        return "statement_changed"  # instance type differs from the reference elaboration
    errored = errored_declarations(output)
    if attempt.instance_name in errored:
        return "lean_rejected"  # an error was logged for this declaration (e.g. a timeout)
    if attempt.general_name in errored:
        return "recipe_not_clean"
    instance_axioms = _axioms(output, attempt.instance_name)
    if instance_axioms is None:
        return "lean_rejected"  # unknown constant: the declaration did not elaborate
    if "sorryAx" in instance_axioms:
        return "lean_rejected"  # an erroring declaration is added with sorry
    if not instance_axioms <= ALLOWED_AXIOMS:
        return "nonstandard_axiom"
    recipe_axioms = _axioms(output, attempt.general_name)
    if recipe_axioms is None or not recipe_axioms <= ALLOWED_AXIOMS:
        return "recipe_not_clean"
    printed = re.split(
        rf"theorem {re.escape(attempt.instance_name)}(?:\.\{{[^}}]*\}})? :", output, maxsplit=1
    )
    if (
        len(printed) < 2
        or re.search(rf"(?<![\w'.]){re.escape(attempt.general_name)}(?![\w'.])", printed[1]) is None
    ):
        return "does_not_use_general_theorem"
    return None


# --- orchestration ------------------------------------------------------------------------------
@dataclass(slots=True)
class LaneResult:
    outcome: str  # "answered" | "miss"
    code: str | None = None
    recipe_id: str | None = None
    recipe_origin: str | None = None
    proposition: str | None = None
    instance_source_sha256: str | None = None
    answer_text: str | None = None
    model_calls: int = 0
    timings_ms: dict[str, float] = field(default_factory=dict)
    tried: list[dict[str, Any]] = field(default_factory=list)


def answer(
    request_formal: str,
    pool: list[PoolRecipe],
    runner: LeanRunner,
    *,
    language: str = "ja",
    candidates: int = DEFAULT_CANDIDATES,
) -> LaneResult:
    """Rank, compile the top candidates in ONE Lean process, accept the first that passes."""
    t0 = time.monotonic()
    try:
        proposition = validate_proposition(closed_proposition(request_formal))
    except InstantiationRejected as error:
        return LaneResult("miss", "request_not_a_plain_proposition", tried=[{"reason": str(error)}])
    ranked_all = rank_candidates(proposition, pool)
    ranked = ranked_all[:candidates]
    result = LaneResult("miss", "no_candidate" if not ranked else "no_instance")
    t_match = time.monotonic()
    result.timings_ms["match"] = round((t_match - t0) * 1000, 1)
    if not ranked:
        return result
    scores = {recipe.recipe_id: score for score, recipe in ranked_all}
    for with_bound in (False, True):
        stage = ranked_all[:BOUND_CANDIDATES] if with_bound else ranked
        source, rejected = build_source(
            [recipe for _, recipe in stage], request_formal, with_bound=with_bound
        )
        result.tried.extend(rejected)
        t_build = time.monotonic()
        result.timings_ms["build"] = round((t_build - t_match) * 1000, 1)
        if not source.attempts:
            result.code = "no_buildable_candidate"
            return result
        code, output, seconds = runner.run(source.source)
        result.timings_ms["lean"] = round(result.timings_ms.get("lean", 0.0) + seconds * 1000, 1)
        for attempt in source.attempts:
            verdict = back_check(source, attempt, output)
            result.tried.append(
                {
                    "recipe": attempt.recipe.recipe_id,
                    "score": round(scores[attempt.recipe.recipe_id], 3),
                    "verdict": verdict or "accepted",
                    "stage": "bound" if with_bound else "plain",
                }
            )
            if verdict is None and result.outcome != "answered":
                recipe = attempt.recipe
                result.outcome, result.code = "answered", None
                result.recipe_id, result.recipe_origin = recipe.recipe_id, recipe.origin
                result.proposition = attempt.proposition
                result.instance_source_sha256 = source.source_sha256
                if recipe.answer is not None:
                    result.answer_text = render_answer(
                        language, recipe.target_source, (), recipe.answer
                    )
        if result.outcome == "answered":
            break
    result.timings_ms["total"] = round((time.monotonic() - t0) * 1000, 1)
    if result.outcome == "miss":
        verdicts = {t.get("verdict") for t in result.tried if "verdict" in t}
        result.code = "lean_rejected_all" if verdicts <= {"lean_rejected"} else "backcheck_failed"
    return result
