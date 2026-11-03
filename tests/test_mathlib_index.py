from __future__ import annotations

import json
from typing import Any

from tools.mathlib_index.build_index import build, name_tokens
from tools.mathlib_index.exact_precheck import closed_source, parse_exact_output, split_sketch
from tools.mathlib_index.extract_premises import bundle_source
from tools.mathlib_index.search import (
    Candidate,
    MathlibIndex,
    lean_query_terms,
    natural_query_terms,
    reciprocal_rank_fusion,
)
from tools.mathlib_index.tiers import classify, shared_positions


def _record(name: str, **overrides: Any) -> dict[str, Any]:
    attrs = {
        "simp": False,
        "norm_cast": False,
        "push_cast": False,
        "ext": False,
        "instance": False,
        "to_dual_linked": False,
        "deprecated": False,
        "private": False,
        "completion_blocked": False,
        "internal": False,
    }
    attrs.update(overrides.pop("attrs", {}))
    record = {
        "name": name,
        "module": "Mathlib.Test",
        "line": overrides.pop("line", abs(hash(name)) % 100000 + 1),
        "column": 0,
        "type": "∀ (x : ℝ), x = x",
        "type_hash": "1",
        "doc": None,
        "attrs": attrs,
        "additive_source": None,
        "cross_refs": [],
        "proof_constants": [],
        "shape": {
            "explicit_args": 1,
            "implicit_args": 0,
            "inst_args": 0,
            "prop_args": 0,
            "conclusion_head": "Eq",
            "conclusion_constants": ["Eq", "Real"],
            "hypothesis_constants": [],
            "classes": [],
        },
    }
    record.update(overrides)
    return record


def _classify(record: dict[str, Any], *, modules: int = 0) -> tuple[str, tuple[str, ...]]:
    positions = shared_positions([record])
    return classify(
        record,
        proof_use_modules=modules,
        position_counts=positions,
        primary_at_position={(record["module"], record["line"], record["column"]): record["name"]},
    )


def _fillers() -> list[dict[str, Any]]:
    # Symbol search skips constants common to most declarations, so tests need a corpus.
    return [_record(f"filler{i}", line=i + 1) for i in range(20)]


def test_internal_deprecated_and_tooling_never_reach_search_tiers() -> None:
    assert _classify(_record("a", attrs={"internal": True}))[0] == "internal"
    assert _classify(_record("b", attrs={"deprecated": True}))[0] == "deprecated"
    assert _classify(_record("c", module="Aesop.Search"))[0] == "tooling"
    assert _classify(_record("d", attrs={"instance": True}))[0] == "instance"


def test_additive_copy_and_shared_position_are_generated() -> None:
    assert _classify(_record("add_foo", additive_source="mul_foo"))[0] == "generated_copy"
    first = _record("foo", line=5)
    second = _record("foo_apply", line=5)
    positions = shared_positions([first, second])
    primary = {("Mathlib.Test", 5, 0): "foo"}
    tier = classify(
        second, proof_use_modules=0, position_counts=positions, primary_at_position=primary
    )
    assert tier[0] == "generated_copy"
    tier = classify(
        first, proof_use_modules=0, position_counts=positions, primary_at_position=primary
    )
    assert tier[0] != "generated_copy"


def test_simp_lemma_is_api_unless_it_names_a_result() -> None:
    assert _classify(_record("foo", attrs={"simp": True}))[0] == "rewrite_api"
    named = _record("foo", attrs={"simp": True}, doc="**Binomial theorem**")
    assert _classify(named) == ("textbook", ("doc_names_result",))


def test_textbook_signals_ignore_wikidata_because_it_keys_the_heldout_yaml() -> None:
    assert _classify(_record("foo", cross_refs=["wikidata:Q1"]))[0] == "general"
    tier, signals = _classify(_record("foo", cross_refs=["stacks:00AB"]))
    assert tier == "textbook"
    assert signals == ("external_reference",)


def test_central_theorem_is_textbook_but_rarely_used_undocumented_one_is_general() -> None:
    assert _classify(_record("foo"), modules=50) == ("textbook", ("central_in_proofs",))
    assert _classify(_record("foo"), modules=49)[0] == "general"


def test_name_tokens_split_camel_case_and_expand_mathlib_conventions() -> None:
    tokens = name_tokens("Matrix.det_mul").split()
    assert {"matrix", "det", "determinant", "mul", "multiplication"} <= set(tokens)
    assert name_tokens("HasDerivAt") == "has deriv derivative at"


def test_query_terms_drop_stopwords_and_read_lean_notation() -> None:
    assert natural_query_terms("Show that the sum of a series") == ["sum", "series"]
    terms = lean_query_terms("example (f : ℝ → ℝ) : ∫ x in a..b, f x ≤ Continuous f")
    assert {"integral", "le", "real", "continuous"} <= set(terms)
    assert "example" not in terms


def test_rrf_prefers_candidates_found_by_both_rankings() -> None:
    fused = reciprocal_rank_fusion(
        [[Candidate("a", 1), Candidate("b", 1)], [Candidate("b", 1), Candidate("c", 1)]], k=2
    )
    assert fused[0].name == "b"


def test_bundle_source_names_examples_after_cards() -> None:
    source, names = bundle_source(
        "import Mathlib\n\n-- manifest card: one\nexample : True := trivial\n\n"
        "-- manifest card: two\nexample : 1 = 1 := rfl\n"
    )
    assert names == {"pals_eval_0": "one", "pals_eval_1": "two"}
    assert "theorem pals_eval_1 : 1 = 1" in source
    assert "example" not in source


def test_build_and_search_keep_tiers_apart(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    records = [
        _record(
            "Polynomial.exists_root",
            doc="**Fundamental theorem of algebra**: every polynomial has a root",
            shape={
                "explicit_args": 1,
                "implicit_args": 0,
                "inst_args": 0,
                "prop_args": 1,
                "conclusion_head": "Exists",
                "conclusion_constants": ["Exists", "Polynomial.IsRoot"],
                "hypothesis_constants": ["Polynomial.degree"],
                "classes": [],
            },
        ),
        _record("Polynomial.root_simp", attrs={"simp": True}),
        _record("hidden.root", attrs={"internal": True}),
        *_fillers(),
    ]
    (raw / "shard-0.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    manifest = build(raw, tmp_path / "out", mathlib_rev="rev", toolchain="tc")
    assert manifest["tiers"]["textbook"] == 1
    assert manifest["tiers"]["internal"] == 1
    index = MathlibIndex(tmp_path / "out" / "index.sqlite")
    core = index.text_search(natural_query_terms("fundamental theorem of algebra"), scope="core")
    assert [candidate.name for candidate in core] == ["Polynomial.exists_root"]
    full = index.text_search(["root"], scope="full")
    assert {candidate.name for candidate in full} == {
        "Polynomial.exists_root",
        "Polynomial.root_simp",
    }
    symbols = index.symbol_search(["Polynomial.IsRoot"], [], scope="core")
    assert symbols[0].name == "Polynomial.exists_root"


def _hint_builder(tmp_path) -> Any:
    from tools.mathlib_index.hint_ab import HintBuilder

    raw = tmp_path / "raw"
    raw.mkdir()
    record = _record(
        "Ideal.mul_le_left",
        doc="A product of ideals lies in the left ideal, a lemma on products.",
        shape={
            "explicit_args": 1,
            "implicit_args": 0,
            "inst_args": 0,
            "prop_args": 1,
            "conclusion_head": "LE.le",
            "conclusion_constants": ["LE.le", "Ideal"],
            "hypothesis_constants": [],
            "classes": [],
        },
    )
    (raw / "shard-0.jsonl").write_text(
        "\n".join(json.dumps(item) for item in [record, *_fillers()]) + "\n", encoding="utf-8"
    )
    build(raw, tmp_path / "out", mathlib_rev="rev", toolchain="tc")
    return HintBuilder(MathlibIndex(tmp_path / "out" / "index.sqlite"), lean="/nonexistent/lean")


def test_hints_never_touch_draft_or_route_prompts(tmp_path) -> None:
    builder = _hint_builder(tmp_path)
    assert builder.hints_for("Write an informal natural-language proof Draft") == ""
    assert builder.hints_for("Select the DSP repair route") == ""
    assert builder.log == []


def test_hints_say_they_are_unverified_and_answer_unknown_identifiers(
    tmp_path, monkeypatch
) -> None:
    from tools.mathlib_index import hint_ab

    monkeypatch.setattr(hint_ab, "elaborated_constants", lambda code, *, lean: (["Ideal"], []))
    prompt = (
        "Complete a Lean 4/mathlib proof from the supplied Draft and formal Sketch.\n"
        "Failed Lean code:\n```lean\ntheorem t : True := Ideal.le_left\n```\n"
        "Identifiers unresolved in the failed import environment:\n- `Ideal.le_left`\n"
    )
    hint = _hint_builder(tmp_path).hints_for(prompt)
    assert "Unverified" in hint
    assert "`Ideal.mul_le_left`" in hint
    lowered = hint.lower()
    assert "lean verification decides" in lowered
    assert "verified candidate" not in lowered


def test_spend_guard_refuses_calls_once_the_limit_is_reached() -> None:
    import pytest

    from pals_agent.openai import OpenAIError
    from tools.mathlib_index.hint_ab import GuardedClient, SpendGuard

    class Inner:
        calls = 0

        def generate(self, *, model: str, prompt: str) -> str:
            self.calls += 1
            return "ok"

    inner = Inner()
    guard = SpendGuard(limit_usd=0.01)
    client = GuardedClient(inner, guard)
    assert client.generate(model="gpt-6.1-terra", prompt="p") == "ok"
    guard.add({"model": "gpt-6.1-terra", "input_tokens": 4000, "output_tokens": 1000})
    with pytest.raises(OpenAIError):
        client.generate(model="gpt-6.1-terra", prompt="p")
    assert inner.calls == 1
    assert guard.stopped


def test_split_sketch_drops_sorry_helpers_and_finds_the_top_level_proof() -> None:
    code = """import Mathlib.Foo
import Mathlib.Bar

open Real

-- note := here
lemma helper (x : ℝ) : x = x := by
  sorry

noncomputable def g (x : ℝ) := x

theorem target {K : Type*} [Field K] (f : K → K := id) (h : ∀ x, f x = x) :
    f 0 = 0 := by
  have := h 0
  sorry
"""
    split = split_sketch(code)
    assert split is not None
    imports, statement = split
    assert imports == "import Mathlib.Foo\nimport Mathlib.Bar"
    assert "helper" not in statement
    assert "noncomputable def g" in statement
    assert statement.endswith("f 0 = 0")
    assert split_sketch("import Mathlib\n") is None


def test_parse_exact_output_requires_a_suggestion_and_no_error() -> None:
    def line(data: str, severity: str) -> str:
        return json.dumps({"data": data, "severity": severity})

    closed = parse_exact_output(line("Try this:\n  [apply] exact foo h", "information"))
    assert closed == {"outcome": "closed", "proof": "exact foo h", "error": None}
    assert parse_exact_output(
        line("`exact?` could not close the goal.", "error")
    )["outcome"] == "not_closed"
    assert parse_exact_output(
        line("(deterministic) timeout, maximum number of heartbeats", "error")
    )["outcome"] == "heartbeat_limit"
    assert parse_exact_output(line("unexpected token", "error"))["outcome"] == "statement_error"
    assert parse_exact_output(
        line("Try this:\n  [apply] exact foo", "information")
        + "\n"
        + line("unexpected token", "error")
    )["outcome"] == "statement_error"
    assert parse_exact_output("")["outcome"] == "no_result"


def test_closed_source_indents_every_proof_line() -> None:
    assert closed_source("import Mathlib", "theorem t : True", "exact\n  trivial") == (
        "import Mathlib\n\ntheorem t : True := by\n  exact\n    trivial\n"
    )
