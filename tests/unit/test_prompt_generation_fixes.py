"""Three default-off prompt flags: full Mathlib import, conditional guidance, Draft fields."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pals_agent import generator as g
from pals_agent.generator import HybridLeanGenerator, parse_draft_fields
from pals_agent.models import (
    DraftFields,
    GeneratedDraft,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
)
from tests.unit.prompt_static_prefix_cases import DRAFT, SKETCH, all_prompts
from tests.unit.test_generator import FakeTextClient

IMPORT = g.FULL_MATHLIB_IMPORT_ENV
COND = g.CONDITIONAL_GUIDANCE_ENV
FIELDS = g.DRAFT_STRUCTURED_FIELDS_ENV
STATIC = g.PROMPT_STATIC_PREFIX_ENV
GOLDEN = Path(__file__).parents[1] / "fixtures" / "generation_prompts_legacy.json"


@pytest.fixture(autouse=True)
def _flags_unset(monkeypatch):
    for name in (IMPORT, COND, FIELDS, STATIC):
        monkeypatch.delenv(name, raising=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- flag off: byte-identical to origin/main (hashes taken at 3010c8c) -------------------


@pytest.mark.parametrize("name", [IMPORT, COND, FIELDS])
def test_each_flag_set_false_is_byte_identical(monkeypatch, name):
    monkeypatch.setenv(name, "false")
    golden = json.loads(GOLDEN.read_text())
    current = {k: _sha(v) for k, v in all_prompts("current").items()}
    assert [k for k in golden if current[k] != golden[k]] == []


@pytest.mark.parametrize("name", [IMPORT, COND, FIELDS])
def test_flags_reject_non_boolean(monkeypatch, name):
    monkeypatch.setenv(name, "1")
    with pytest.raises(ValueError):
        all_prompts("current")


@pytest.mark.parametrize("name", [IMPORT, COND, FIELDS])
def test_flag_on_changes_the_prompts(monkeypatch, name):
    golden = json.loads(GOLDEN.read_text())
    monkeypatch.setenv(name, "true")
    current = {k: _sha(v) for k, v in all_prompts("current").items()}
    assert any(current[k] != golden[k] for k in golden)


# --- flag 1: full Mathlib import ---------------------------------------------------------

DROPPED = (
    "Prefer the specific modules",
    "Verify the owning modules",
    "try `import Mathlib` once",
    "owning module",
)


def test_full_import_prompts_drop_module_selection_and_demand_one_import(monkeypatch):
    monkeypatch.setenv(IMPORT, "true")
    from tests.unit.prompt_static_prefix_cases import FEEDBACKS, REQUESTS

    request = REQUESTS["plain"]
    for stage, prompt in {
        "sketch": g._sketch_prompt_for(request, DRAFT, FEEDBACKS["unknown"]),
        "prove": g._prove_prompt_for(request, DRAFT, SKETCH, FEEDBACKS["unknown"]),
        "sketch-nofb": g._sketch_prompt_for(request, DRAFT),
        "prove-nofb": g._prove_prompt_for(request, DRAFT, SKETCH),
    }.items():
        for phrase in DROPPED:
            assert phrase not in prompt, (stage, phrase)
        assert "exactly one import line, `import Mathlib`" in prompt, stage
    repair = g._sketch_prompt_for(request, DRAFT, FEEDBACKS["unknown"])
    assert "Do not change the import line" in repair
    assert "nonexistent and replace it with an actual declaration or an automation" in repair
    assert "First repair only the imports" not in repair


def test_full_import_leaves_non_import_unknown_identifier_free_prompts_alone(monkeypatch):
    from tests.unit.prompt_static_prefix_cases import FEEDBACKS, REQUESTS

    off = g._sketch_prompt_for(REQUESTS["plain"], DRAFT, FEEDBACKS["plain_error"])
    monkeypatch.setenv(IMPORT, "true")
    on = g._sketch_prompt_for(REQUESTS["plain"], DRAFT, FEEDBACKS["plain_error"])
    assert on.split("Use Lean 4 syntax.")[1] == off.split("Use Lean 4 syntax.")[1]


MODEL_CODE = (
    "import Mathlib.Data.Nat.Basic\nimport Mathlib.Tactic\n\ntheorem t : 1 = 1 := by\n  rfl"
)


def _sketch_with(monkeypatch, flag: str | None):
    if flag:
        monkeypatch.setenv(IMPORT, flag)
    client = FakeTextClient(f"```lean\n{MODEL_CODE}\n```")
    generator = HybridLeanGenerator(model="m", client=client)
    return generator.generate_sketch(ProofRequest(id="x", prompt="One equals one."), DRAFT)


def test_generated_header_is_normalized_only_when_flag_on(monkeypatch):
    assert _sketch_with(monkeypatch, None).lean_code == MODEL_CODE
    monkeypatch.undo()
    result = _sketch_with(monkeypatch, "true")
    assert result.lean_code.splitlines()[0] == "import Mathlib"
    assert result.lean_code.count("import ") == 1
    assert "theorem t : 1 = 1 := by\n  rfl" in result.lean_code


def test_generated_proof_header_is_normalized_when_flag_on(monkeypatch):
    monkeypatch.setenv(IMPORT, "true")
    client = FakeTextClient(f"```lean\n{MODEL_CODE}\n```")
    generator = HybridLeanGenerator(model="m", client=client)
    proof = generator.generate_proof(
        ProofRequest(id="x", prompt="One equals one."), DRAFT, SKETCH
    )
    assert proof.lean_code.splitlines()[0] == "import Mathlib"


# --- flag 2: conditional guidance --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "prove that for all real x, x^2 ≥ 0",
        "|x - 1| < 2 implies x < 3",
        "実数 x について不等式を示せ",
        "Show n - m ≤ n for natural numbers",
        "A polynomial identity: (a+b)(a-b) = a^2 - b^2",
        "",
    ],
)
def test_scalar_cues_fire(text):
    assert g.needs_scalar_guidance(text.lower())


@pytest.mark.parametrize(
    "text",
    [
        "show that every finite group of prime order is cyclic",
        "prove that the union of two open sets is open in a topological space",
    ],
)
def test_scalar_cues_do_not_fire_without_a_cue(text):
    assert not g.needs_scalar_guidance(text.lower())


@pytest.mark.parametrize(
    "text",
    [
        "expand the product",
        "a * b + c = c + b * a",
        "x^2 + 1 > 0",
        "多項式の恒等式",
        "",
    ],
)
def test_algebra_cues_fire(text):
    assert g.needs_algebra_guidance(text.lower())


def test_algebra_cue_absent_for_pure_set_theory():
    assert not g.needs_algebra_guidance("every open cover of a compact set has a subcover")


def test_conditional_guidance_is_omitted_without_cues_and_kept_with_them(monkeypatch):
    monkeypatch.setenv(COND, "true")
    plain = ProofRequest(id="p", prompt="Every finite group of prime order is cyclic.")
    real = ProofRequest(id="r", prompt="For real x, |x| ≥ 0.")
    draft = GeneratedDraft("Use the order of an element.", "m", "")
    scalar_marker = "Lean scalar formalization and case discipline"
    algebra_marker = "Learner-facing algebra proof structure"
    for builder in (
        lambda r: g._draft_prompt_for(r),
        lambda r: g._sketch_prompt_for(r, draft),
        lambda r: g._prove_prompt_for(r, draft, SKETCH),
    ):
        text = builder(plain)
        assert scalar_marker not in text and algebra_marker not in text
    assert scalar_marker in g._sketch_prompt_for(real, draft)
    assert scalar_marker in g._prove_prompt_for(real, draft, SKETCH)
    assert scalar_marker not in g._draft_prompt_for(real)  # Draft never had the scalar block
    algebraic = ProofRequest(id="a", prompt="Show that a^3 - 1 is divisible by a - 1.")
    assert algebra_marker in g._draft_prompt_for(algebraic)
    assert algebra_marker not in g._draft_prompt_for(real)


def test_conditional_guidance_uses_the_draft_text_as_a_cue(monkeypatch):
    monkeypatch.setenv(COND, "true")
    plain = ProofRequest(id="p", prompt="Every finite group of prime order is cyclic.")
    with_cue = GeneratedDraft("Bound the term by an inequality with |a|.", "m", "")
    assert "Lean scalar formalization" in g._sketch_prompt_for(plain, with_cue)


def test_conditional_guidance_with_static_prefix_keeps_a_shared_prefix(monkeypatch):
    monkeypatch.setenv(COND, "true")
    monkeypatch.setenv(STATIC, "true")
    first = ProofRequest(id="1", prompt="For real x, |x| ≥ 0.")
    second = ProofRequest(id="2", prompt="Every finite group of prime order is cyclic.")
    for builder in (
        lambda r: g._sketch_prompt_for(r, DRAFT),
        lambda r: g._prove_prompt_for(r, DRAFT, SKETCH),
    ):
        a, b = builder(first), builder(second)
        n = next(i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y)
        assert n > 1024 * 3  # divergence only after the static guidance
        assert "Lean scalar formalization" not in a[:n]


# --- flag 3: Draft structured fields -----------------------------------------------------

GOOD = "Step 1.\nStep 2.\n\nFINAL_ANSWER: x = 3\nHARD_STEPS:\n- step A\n- step B\n"


def test_parse_draft_fields_accepts_well_formed_tail():
    assert parse_draft_fields(GOOD) == DraftFields("x = 3", ("step A", "step B"))
    assert parse_draft_fields("d\nFINAL_ANSWER: ok\nHARD_STEPS: - none") == DraftFields("ok", ())
    assert parse_draft_fields("d\nFINAL_ANSWER: ok\nHARD_STEPS: one\n- two") == DraftFields(
        "ok", ("one", "two")
    )


@pytest.mark.parametrize(
    "text",
    [
        "no fields at all",
        "FINAL_ANSWER: 3",  # HARD_STEPS missing
        "HARD_STEPS:\n- a\nFINAL_ANSWER: 3",  # wrong order
        "FINAL_ANSWER:\nHARD_STEPS:\n- a",  # empty answer
        "FINAL_ANSWER: 3\nFINAL_ANSWER: 4\nHARD_STEPS:\n- a",  # duplicated
        "FINAL_ANSWER: 3\nsome prose\nHARD_STEPS:\n- a",  # junk between
        "FINAL_ANSWER: 3\nHARD_STEPS:\n- a\n- b\n- c\n- d",  # more than 3 steps
        "FINAL_ANSWER: 3\nHARD_STEPS:\n- a\n-\n",  # empty bullet
    ],
)
def test_parse_draft_fields_rejects_missing_or_broken(text):
    assert parse_draft_fields(text) is None


def test_draft_prompt_asks_for_the_fields_only_when_flag_on(monkeypatch):
    request = ProofRequest(id="p", prompt="Show that 2 + 2 = 4.")
    assert "FINAL_ANSWER:" not in g._draft_prompt_for(request)
    monkeypatch.setenv(FIELDS, "true")
    on = g._draft_prompt_for(request)
    assert on.count("FINAL_ANSWER:") == 1 and on.count("HARD_STEPS:") == 1
    assert on.rstrip().endswith('Write "- none" when there is none.')
    monkeypatch.setenv(STATIC, "true")  # in the static region instead of the tail
    static_on = g._draft_prompt_for(request)
    assert static_on.index("FINAL_ANSWER:") < static_on.index("Problem:")


def _draft_from(monkeypatch, flag: str | None, output: str) -> GeneratedDraft:
    if flag:
        monkeypatch.setenv(FIELDS, flag)
    generator = HybridLeanGenerator(model="m", client=FakeTextClient(output))
    return generator.generate_draft(ProofRequest(id="p", prompt="Show that 2 + 2 = 4."))


def test_generate_draft_attaches_fields_without_changing_the_text(monkeypatch):
    on = _draft_from(monkeypatch, "true", GOOD)
    assert on.text == GOOD.strip()
    assert on.fields == DraftFields("x = 3", ("step A", "step B"))
    monkeypatch.undo()
    off = _draft_from(monkeypatch, None, GOOD)
    assert off.text == on.text and off.fields is None


def test_generate_draft_with_broken_fields_is_treated_as_today(monkeypatch):
    broken = _draft_from(monkeypatch, "true", "Step 1.\nFINAL_ANSWER: 3")
    assert broken.text == "Step 1.\nFINAL_ANSWER: 3" and broken.fields is None


def test_sketch_prompt_still_receives_the_whole_draft_including_fields():
    request = ProofRequest(id="p", prompt="Show that 2 + 2 = 4.")
    prompt = g._sketch_prompt_for(request, GeneratedDraft(GOOD, "m", ""))
    assert "FINAL_ANSWER: x = 3" in prompt and prompt.count("FINAL_ANSWER:") == 1


def test_unused_imports_for_type_checkers():
    assert GenerationFeedback and GeneratedSketch
