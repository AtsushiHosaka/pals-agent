"""Stage 0, fidelity gate and explanation templates (no Lean, no network)."""

import json
from pathlib import Path

import pytest

from pals_agent import automation_portfolio as ap
from pals_agent import fidelity_gate as gate
from pals_agent import portfolio_explanation as expl
from pals_agent import stage0

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2] / "testdata/fidelity-adversarial-v1/cases.json"
    ).read_text()
)["cases"]


class FakeWorker:
    """Stands in for WarmWorker: answers by looking at the Lean text it is given."""

    startup_s = 0.0

    def __init__(self, *, proves=True, agree=True):
        self.proves, self.agreed, self.texts = proves, agree, []

    def alive(self):
        return True

    def restart(self):
        pass

    def check(self, source, *, timeout_s=60.0):
        self.texts.append(source)
        if "pals_agree" in source:
            if not self.agreed:
                return "unknown constant 'pals_agree'", 0.01
            return (
                "theorem pals_agree : A ↔ B := Iff.rfl\n"
                "'pals_agree' does not depend on any axioms\n",
                0.01,
            )
        if "PALS_DOC" in source:
            return "Foo.bar : a = a\nPALS_DOC:The doc.\n", 0.01
        for line in source.splitlines():
            if line.startswith("theorem pals_portfolio_"):
                name = line.split()[1]
                if self.proves and "positivity" in source:
                    return f"'{name}' does not depend on any axioms\n", 0.01
                return f"/t.lean:1:0: error: failed\n'{name}' depends on axioms: [sorryAx]\n", 0.01
        return "", 0.01


def model_factory(formal_a, formal_b, faithful=True):
    calls = []

    def model(prompt, schema):
        calls.append(prompt[:20])
        if "formal" in schema["properties"]:
            return {"formal": formal_b if "most faithful form" in prompt else formal_a}
        return {"faithful": faithful, "issue": "" if faithful else "weaker"}

    model.calls = calls
    return model


def test_flag_default_off():
    assert not stage0.stage0_enabled({})
    assert stage0.stage0_enabled({"PALS_STAGE0_PORTFOLIO": "on"})


def test_model_written_statement_needs_agreement_and_review():
    s = "∀ x : ℝ, 0 ≤ x ^ 2"
    ok = stage0.Stage0(FakeWorker(), [], model_factory(s, s)).run("x^2 >= 0", "en")
    assert ok.outcome == "answered" and ok.gate and ok.gate.passed and ok.model_calls == 3
    # Lean proves it, but the review rejects: never released on Lean success alone
    bad = stage0.Stage0(FakeWorker(), [], model_factory(s, s, faithful=False)).run("x", "en")
    assert bad.outcome == "fallthrough" and bad.reason == "fidelity_gate_failed"
    assert "review_rejected" in bad.gate.reasons
    # Lean proves it, review approves, but the two formalisations disagree
    split = stage0.Stage0(FakeWorker(agree=False), [], model_factory(s, "∀ x : ℕ, 0 ≤ x")).run(
        "x", "en"
    )
    assert split.outcome == "fallthrough" and "formalisations_disagree" in split.gate.reasons


def test_given_statement_needs_no_gate_and_no_model():
    result = stage0.Stage0(FakeWorker(), [], None).run(
        "x^2 >= 0", "ja", formal="∀ x : ℝ, 0 ≤ x ^ 2"
    )
    assert result.outcome == "answered" and result.model_calls == 0 and result.gate is None
    assert "positivity" not in (result.answer_text or "") and "非負" in result.answer_text


def test_unproved_statement_falls_through_with_a_reason():
    result = stage0.Stage0(FakeWorker(proves=False), [], None).run(
        "x", "en", formal="∀ x : ℝ, 0 ≤ x ^ 2"
    )
    assert result.outcome == "fallthrough" and result.answer_text is None


def test_no_model_for_a_request_without_formal_statement():
    result = stage0.Stage0(FakeWorker(), [], None).run("x^2 >= 0", "en")
    assert result.outcome == "fallthrough" and result.reason == "no_model_for_formalisation"


def test_stage0_never_raises():
    class Boom(FakeWorker):
        def check(self, *a, **k):
            raise RuntimeError("worker died")

    result = stage0.Stage0(Boom(), [], None).run("x", "en", formal="∀ x : ℝ, 0 ≤ x ^ 2")
    assert result.outcome == "fallthrough" and result.reason.startswith("stage0_error")


@pytest.mark.parametrize(
    "tactic",
    [
        "simp",
        "simp_all",
        "aesop",
        "grind",
        "bound",
        "gcongr",
        "constructor_simp",
        "induction_simp_all",
    ],
)
def test_no_template_for_closers_without_a_single_citable_fact(tactic):
    assert expl.render("en", "∀ x : ℝ, 0 ≤ x ^ 2", tactic) is None


def test_templates_follow_the_request_language_and_state_their_limit():
    ja = expl.render("ja", "∀ x y : ℝ, (x + y) * (x - y) = x ^ 2 - y ^ 2", "ring")
    en = expl.render("en", "∀ x y : ℝ, (x + y) * (x - y) = x ^ 2 - y ^ 2", "ring")
    assert "正規形" in ja and "normal form" in en
    assert (
        "証明方法の指定には対応していません" in ja
        and "does not follow a specific proof method" in en
    )


def test_positivity_template_only_for_sign_statements_and_norm_num_only_for_ground_numerals():
    assert expl.render("en", "∀ x y : ℝ, x * y = y * x", "positivity") is None
    assert expl.render("en", "∀ n : ℕ, ¬ n < 0", "norm_num") is None
    assert expl.render("en", "(2 : ℝ) + 2 = 4", "norm_num")
    assert expl.render("en", "Continuous (fun x : ℝ => x ^ 3)", "fun_prop")
    assert expl.render("en", "∀ x : ℝ, 0 ≤ x ^ 2", "fun_prop") is None


def test_exact_search_template_cites_the_lemma_with_type_doc_and_call():
    info = expl.parse_lemma_probe(
        "Foo.bar", "Foo.bar : ∀ (a : ℕ), a = a\nPALS_DOC:Reflexivity of equality.\n", "Foo.bar 3"
    )
    text = expl.render("ja", "∀ a : ℕ, a = a", "exact?", info)
    assert "Foo.bar" in text and "Reflexivity" in text and "`Foo.bar 3`" in text
    assert expl.render("ja", "∀ a : ℕ, a = a", "exact?", None) is None


def test_lemma_probe_rejects_unsafe_names():
    with pytest.raises(ValueError):
        expl.lemma_probe_source("x\n#eval 1")


def test_numerals_check_is_a_signal_and_never_decides():
    assert gate.numerals_signal("x^2 と 3", "x ^ 2") is False
    s = "∀ x : ℝ, 0 ≤ x ^ 2"
    result = stage0.Stage0(FakeWorker(), [], model_factory(s, s)).run("n=7 のとき x^2", "en")
    assert result.gate.numerals_signal is False and result.outcome == "answered"


def test_equivalence_verdict_requires_error_free_and_used_hypothesis():
    tail = "'pals_agree' does not depend on any axioms\n"
    used = "theorem pals_agree : A ↔ B :=\n  ⟨fun pals_h => pals_h, fun pals_h => pals_h⟩\n" + tail
    assert gate.equivalence_verdict(used)
    assert gate.equivalence_verdict("theorem pals_agree : A ↔ B := Iff.rfl\n" + tail)
    unused = "theorem pals_agree : A ↔ B :=\n  ⟨fun pals_h => foo, fun pals_h => bar⟩\n" + tail
    assert not gate.equivalence_verdict(unused)
    assert not gate.equivalence_verdict("/t.lean:3:0: error: timeout\n" + used)


def test_adversarial_cases_are_well_formed_and_cover_the_required_kinds():
    assert len(CASES) >= 6
    kinds = " ".join(c["kind"] for c in CASES)
    for needle in ("hypothesis", "structure", "∃", "domain", "off-by-one"):
        assert needle in kinds
    for c in CASES:
        assert c["bad"] != c["faithful"]
        ap.check_formal_statement(c["bad"])
        ap.check_formal_statement(c["faithful"])


def test_structure_words_in_the_request_must_appear_in_the_statement():
    ja = "斜体$K$上の加群$V$について"
    assert gate.structure_check(ja, "∀ (K : Type*) [Field K] (V : Type*) [Module K V], True") == [
        "division ring"
    ]
    assert gate.structure_check(ja, "∀ (K : Type*) [DivisionRing K], True") == []
    group = "Let G be a group. For all a, b, (ab)^{-1} = b^{-1}a^{-1}."
    assert gate.structure_check(group, "∀ (G : Type*) [CommGroup G] (a b : G), a = a") == [
        "group, not abelian"
    ]
    assert gate.structure_check(group, "∀ (G : Type*) [Group G] (a b : G), a = a") == []
    # a module request is not a group request, and a negated assumption is not enforced
    assert gate.structure_check("加群 V", "∀ V : Type*, True") == []


def test_stage0_blocks_a_structure_mismatch_even_when_lean_and_the_review_agree():
    s = "∀ (K : Type*) [Field K], True"
    result = stage0.Stage0(FakeWorker(), [], model_factory(s, s)).run("斜体 K について", "ja")
    assert result.outcome == "fallthrough" and "structure_mismatch" in result.gate.reasons
