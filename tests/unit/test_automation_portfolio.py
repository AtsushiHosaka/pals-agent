"""Pure-Python parts of the automation portfolio (no Lean)."""

import pytest

from pals_agent import automation_portfolio as ap
from pals_agent import general_recipe_lane as lane
from pals_agent.recipe_instantiation import InstantiationRejected


def test_theorem_header_with_proof_placeholder_becomes_a_closed_statement():
    header = "theorem scheme_x {R : Type*} [CommRing R] (a : R) : a + 0 = a := by\n  sorry"
    assert ap.closed_statement(header) == "∀ {R : Type*} [CommRing R] (a : R), a + 0 = a"
    assert ap.check_formal_statement(
        "example (n : ℕ) : n + 0 = n := by\n  sorry", allow_header=True
    ) == ("∀ (n : ℕ), n + 0 = n")


def test_let_is_outside_the_grammar():
    for text in ("∀ n : ℕ, let m := n + 1; m > 0", "∀ n : ℕ, n = n; n = n"):
        with pytest.raises(InstantiationRejected):
            ap.check_formal_statement(text)


def test_full_file_card_keeps_only_open_and_universe_as_preamble():
    card = (
        "import Mathlib\nopen CategoryTheory Opposite\n\nuniverse u\n"
        "theorem t {X : Type u} (x : X) : x = x := by\n  sorry"
    )
    preamble, _ = ap.split_preamble(card)
    assert preamble == "open CategoryTheory Opposite\nuniverse u"
    assert ap.check_formal_statement(card, allow_header=True) == "∀ {X : Type u} (x : X), x = x"
    hostile = 'import Mathlib\nsyntax "x" : term\ntheorem t : True := by trivial'
    with pytest.raises(InstantiationRejected):
        ap.check_formal_statement(hostile, allow_header=True)


@pytest.mark.parametrize(
    "bad",
    [
        "True := by trivial",
        "∀ n : ℕ, sorry",
        "1 = 1\ntheorem t : True",
        "∀ x, x = x -- c",
        "(1 : ℕ) = 1 theorem foo : True",
        "∀ n : ℕ, (n",
        "#eval 1",
    ],
)
def test_statements_with_commands_comments_or_sorry_never_reach_lean(bad):
    with pytest.raises(InstantiationRejected):
        ap.check_formal_statement(bad)


def test_portfolio_is_fixed_cheap_first_and_exact_search_is_last_with_a_larger_cap():
    names = [t.name for t in ap.PORTFOLIO]
    assert names[-1] == "exact?" and names.index("fun_prop") < names.index("aesop")
    assert ap.PORTFOLIO[-1].heartbeats > ap.PORTFOLIO[0].heartbeats
    assert len(set(names)) == len(names)
    assert all("native_decide" not in t.text and "sorry" not in t.text for t in ap.PORTFOLIO)


def test_unified_source_has_one_import_one_declaration_per_attempt_and_the_requested_type():
    text, proposition, attempts, _ = ap.build_unified(
        "example (x : ℝ) : 0 ≤ x ^ 2", [], allow_header=True
    )
    assert text.count("import Mathlib") == 1 and proposition == "∀ (x : ℝ), 0 ≤ x ^ 2"
    assert len(attempts) == len(ap.PORTFOLIO)
    for attempt in attempts:
        assert f"theorem {attempt.decl} : ∀ (x : ℝ), 0 ≤ x ^ 2 := by" in text
        assert f"#print axioms {attempt.decl}" in text


def _fake_stream(verdicts):
    def run(runner, source, *, budget_s, stop=None):
        lines = ["'pals_probe' does not depend on any axioms"]
        for name, axioms in verdicts.items():
            lines.append(f"'{name}' depends on axioms: [{axioms}]")
        events = [(1.0 + i * 0.01, line) for i, line in enumerate(lines)]
        return ap.StreamResult("\n".join(lines), events, False, 2.0)

    return run


def test_solve_accepts_the_first_clean_attempt_and_treats_sorryax_as_failure(monkeypatch):
    clean = "propext, Classical.choice, Quot.sound"
    monkeypatch.setattr(
        ap,
        "run_stream",
        _fake_stream(
            {
                "_pals_portfolio_0": "propext, sorryAx",
                "_pals_portfolio_1": clean,
                "_pals_portfolio_2": clean,
            }
        ),
    )
    result = ap.solve("∀ x : ℝ, 0 ≤ x ^ 2", [], lane.LeanRunner("lean", ""), use_recipes=False)
    assert (result.outcome, result.route, result.by) == ("answered", "portfolio", "positivity")
    assert result.model_calls == 0 and result.startup_s == 1.0


def test_solve_misses_when_every_attempt_has_sorryax_or_a_nonstandard_axiom(monkeypatch):
    monkeypatch.setattr(
        ap,
        "run_stream",
        _fake_stream(
            {
                "_pals_portfolio_0": "propext, sorryAx",
                "_pals_portfolio_1": "myAxiom",
            }
        ),
    )
    result = ap.solve("∀ x : ℝ, 0 ≤ x ^ 2", [], lane.LeanRunner("lean", ""), use_recipes=False)
    assert result.outcome == "miss" and result.code == "no_attempt_succeeded"


def test_statement_with_syntax_is_a_miss_not_a_crash():
    result = ap.solve("True := by trivial", [], lane.LeanRunner("lean", ""))
    assert result.outcome == "miss" and result.code == "statement_not_plain"


def test_a_timeout_error_is_not_an_accepted_portfolio_attempt(monkeypatch):
    clean = "propext, Classical.choice, Quot.sound"
    lines = [
        "'pals_probe' does not depend on any axioms",
        "/t/P.lean:3:0: error: (deterministic) timeout at `whnf`, maximum number of heartbeats",
        "'_pals_portfolio_0' does not depend on any axioms",
        f"'_pals_portfolio_1' depends on axioms: [{clean}]",
    ]

    def run(runner, source, *, budget_s, stop=None):
        events = [(1.0 + i * 0.01, line) for i, line in enumerate(lines)]
        return ap.StreamResult("\n".join(lines), events, False, 2.0)

    monkeypatch.setattr(ap, "run_stream", run)
    result = ap.solve("∀ x : ℝ, 0 ≤ x ^ 2", [], lane.LeanRunner("lean", ""), use_recipes=False)
    assert result.by == "positivity" and result.attempts[0].verdict == "error_logged"
