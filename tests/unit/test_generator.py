from dataclasses import asdict

import pytest

from pals_agent.generator import (
    HybridLeanGenerator,
    RepairInstructionError,
    _draft_prompt_for,
    _prove_prompt_for,
    _repair_guidance,
    extract_lean_code,
    parse_repair_instruction,
    parse_repair_route_decision,
)
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofDraft,
    ProofRequest,
    RelatedDraftContext,
    RepairRoute,
    RepairRouteSelectionError,
)
from pals_agent.ollama import OllamaError

DRAFT = "First derive h : n + 0 = n from the natural-number identity, then conclude."
REVISED_DRAFT = "First establish h : n = n by reflexivity, then use h to conclude."
SKETCH = """```lean
import Mathlib

theorem test (n : Nat) : n + 0 = n := by
  have h : n + 0 = n := by
    sorry
  exact h
```"""
REVISED_SKETCH = """```lean
import Mathlib

theorem test (n : Nat) : n + 0 = n := by
  have h : n = n := by
    sorry
  simpa using h
```"""
PROOF = """```lean
import Mathlib

theorem test (n : Nat) : n + 0 = n := by
  have h : n + 0 = n := by
    exact Nat.add_zero n
  exact h
```"""
REVISED_PROOF = """```lean
import Mathlib

theorem test (n : Nat) : n + 0 = n := by
  have h : n = n := by
    rfl
  simpa using h
```"""


class FakeTextClient:
    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.models: list[str] = []

    def generate(self, *, model: str, prompt: str) -> str:
        self.models.append(model)
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def request() -> ProofRequest:
    return ProofRequest(
        id="test",
        prompt="Every natural number plus zero is itself.",
        formal_statement="theorem test (n : Nat) : n + 0 = n := by",
    )


def prior_stages() -> tuple[GeneratedDraft, GeneratedSketch]:
    return (
        GeneratedDraft(text=DRAFT, model="draft-model", raw_model_output=DRAFT),
        GeneratedSketch(
            lean_code=extract_lean_code(SKETCH) or "",
            model="draft-model",
            raw_model_output=SKETCH,
            has_gaps=True,
        ),
    )


def feedback(
    route: RepairRoute,
    *,
    draft: GeneratedDraft | None = None,
    sketch: GeneratedSketch | None = None,
) -> GenerationFeedback:
    return GenerationFeedback(
        attempt=1,
        previous_lean_code="theorem test : True := by\n  exact broken",
        diagnostics=(Diagnostic(severity="error", message="unknown identifier"),),
        repair_route=route,
        repair_rationale="Resume at the selected DSP stage.",
        previous_draft=draft,
        previous_sketch=sketch,
    )


def test_generated_proof_keeps_existing_constructor_compatible() -> None:
    generated = GeneratedProof("example : True := by trivial", "model", "raw")

    assert generated.draft is None
    assert generated.sketch is None


def test_repair_guidance_forbids_unknown_identifier_from_next_candidate() -> None:
    repair_feedback = GenerationFeedback(
        attempt=2,
        previous_lean_code="example : True := by exact abs_add",
        diagnostics=(
            Diagnostic(
                severity="error",
                code="lean.unknownIdentifier",
                message="Unknown identifier `abs_add`",
            ),
        ),
        repair_route="prove",
    )

    guidance = _repair_guidance(repair_feedback)

    assert "Every error diagnostic below is mandatory to fix" in guidance
    assert "Identifiers rejected by Lean and forbidden" in guidance
    assert "- `abs_add`" in guidance


def test_extracts_fenced_lean_code() -> None:
    output = """Here is code:
```lean
import Mathlib

theorem sample : 1 = 1 := by
  rfl
```
"""

    assert extract_lean_code(output) == "import Mathlib\n\ntheorem sample : 1 = 1 := by\n  rfl"


def test_rejects_prose_without_lean_code() -> None:
    assert extract_lean_code("This is only an informal proof.") is None


def test_parse_repair_route_decision_accepts_json() -> None:
    decision = parse_repair_route_decision(
        '{"route":"prove","rationale":"Only a theorem name failed."}'
    )

    assert decision.route == "prove"
    assert decision.rationale == "Only a theorem name failed."


def test_repair_role_requires_one_closed_typed_handoff() -> None:
    handoff = parse_repair_instruction(
        '{"instruction":"Replace the unresolved identifier with the Mathlib lemma."}'
    )

    assert handoff.instruction.startswith("Replace the unresolved identifier")

    with pytest.raises(RepairInstructionError):
        parse_repair_instruction('{"instruction":"ok","route":"prove"}')
    with pytest.raises(RepairInstructionError):
        parse_repair_instruction('explanation {"instruction":"ok"}')


@pytest.mark.parametrize(
    "output",
    [
        "I would resume from sketch.",
        "retry somehow",
        'explanation {"route":"prove","rationale":"local fix"}',
    ],
)
def test_parse_repair_route_decision_rejects_invalid_output(output: str) -> None:
    with pytest.raises(RepairRouteSelectionError):
        parse_repair_route_decision(output)


def test_hybrid_generator_uses_llm_client_to_select_repair_route() -> None:
    client = FakeTextClient(
        '{"route":"prove","rationale":"The statement and sketch look valid."}'
    )
    generator = HybridLeanGenerator(model="route-model", client=client)

    previous_draft, previous_sketch = prior_stages()
    decision = generator.select_repair_route(
        request(),
        feedback("draft", draft=previous_draft, sketch=previous_sketch),
    )

    assert decision.route == "prove"
    assert decision.rationale == "The statement and sketch look valid."
    assert client.models == ["route-model"]
    assert "`draft`, `sketch`, `prove`" in client.prompts[0]
    assert "unknown identifier" in client.prompts[0]
    assert previous_draft.text in client.prompts[0]
    assert previous_sketch.lean_code in client.prompts[0]
    assert decision.prompt == client.prompts[0]
    assert decision.model == "route-model"
    assert decision.provider == "ollama"
    assert decision.attempt_outputs == (decision.raw_model_output,)


def test_repair_route_selector_retries_invalid_json_once() -> None:
    client = FakeTextClient(
        "resume from sketch",
        '{"route":"sketch","rationale":"The decomposition must be regenerated."}',
    )
    generator = HybridLeanGenerator(model="route-model", client=client)

    decision = generator.select_repair_route(request(), feedback("draft"))

    assert decision.route == "sketch"
    assert len(client.prompts) == 2
    assert client.prompts[1] != client.prompts[0]
    assert "previous route response was invalid" in client.prompts[1].lower()
    assert "strict JSON" in client.prompts[1]
    assert decision.attempt_outputs[0] == "resume from sketch"
    assert len(decision.attempt_outputs) == 2


def test_pae_016_route_selector_retries_two_malformed_outputs_then_continues() -> None:
    client = FakeTextClient(
        "not json one",
        '{"route":"unknown","rationale":"not closed"}',
        '{"route":"prove","rationale":"Repair only the Lean proof."}',
    )
    generator = HybridLeanGenerator(model="route-model", client=client)

    decision = generator.select_repair_route(request(), feedback("draft"))

    assert decision.route == "prove"
    assert len(client.prompts) == 3
    assert all("strict JSON" in prompt for prompt in client.prompts[1:])
    assert decision.attempt_outputs == (
        "not json one",
        '{"route":"unknown","rationale":"not closed"}',
        '{"route":"prove","rationale":"Repair only the Lean proof."}',
    )
    assert [asdict(item) for item in decision.selector_attempts] == [
        {
            "attempt": 1,
            "outcome": "invalid_response",
            "diagnostic_code": "pals.repair_route_invalid_response",
            "route": None,
        },
        {
            "attempt": 2,
            "outcome": "invalid_response",
            "diagnostic_code": "pals.repair_route_invalid_response",
            "route": None,
        },
        {
            "attempt": 3,
            "outcome": "selected",
            "diagnostic_code": None,
            "route": "prove",
        },
    ]


def test_repair_route_selector_failure_preserves_structured_audit() -> None:
    client = FakeTextClient(
        "invalid route one",
        "invalid route two",
        "invalid route three",
    )
    generator = HybridLeanGenerator(model="route-model", client=client)

    with pytest.raises(RepairRouteSelectionError) as error_info:
        generator.select_repair_route(request(), feedback("draft"))

    error = error_info.value
    assert error.prompt == client.prompts[-1]
    assert client.prompts[-1] != client.prompts[0]
    assert error.model == "route-model"
    assert error.provider == "ollama"
    assert error.elapsed_ms >= 0
    assert error.attempt_outputs == (
        "invalid route one",
        "invalid route two",
        "invalid route three",
    )
    assert [asdict(item) for item in error.selector_attempts] == [
        {
            "attempt": attempt,
            "outcome": "invalid_response",
            "diagnostic_code": "pals.repair_route_invalid_response",
            "route": None,
        }
        for attempt in (1, 2, 3)
    ]


def test_pae_016_route_selector_retries_transport_without_fallback() -> None:
    client = FakeTextClient(
        OllamaError("first transport failure"),
        OllamaError("second transport failure"),
        OllamaError("third transport failure"),
    )
    generator = HybridLeanGenerator(model="route-model", client=client)

    with pytest.raises(RepairRouteSelectionError) as error_info:
        generator.select_repair_route(request(), feedback("draft"))

    error = error_info.value
    assert len(client.prompts) == 3
    assert [asdict(item) for item in error.selector_attempts] == [
        {
            "attempt": attempt,
            "outcome": "transport_error",
            "diagnostic_code": "pals.repair_route_transport_error",
            "route": None,
        }
        for attempt in (1, 2, 3)
    ]
    assert "first transport failure" not in repr(error.selector_attempts)


def test_generate_calls_draft_sketch_and_prove_with_endpoint_and_prompt_handoff() -> None:
    default_client = FakeTextClient(DRAFT, SKETCH)
    prove_client = FakeTextClient(PROOF)
    generator = HybridLeanGenerator(
        model="draft-model",
        provider="ollama",
        client=default_client,
        prove_model="prove-model",
        prove_provider="mlx",
        prove_client=prove_client,
    )

    generated = generator.generate(request())

    assert default_client.models == ["draft-model", "draft-model"]
    assert prove_client.models == ["prove-model"]
    assert generated.model == "prove-model"
    assert "Nat.add_zero" in generated.lean_code
    assert generated.draft is not None
    assert generated.draft.text == DRAFT
    assert generated.draft.model == "draft-model"
    assert generated.draft.provider == "ollama"
    assert generated.draft.prompt == default_client.prompts[0]
    assert generated.sketch is not None
    assert "sorry" in generated.sketch.lean_code
    assert generated.sketch.provider == "ollama"
    assert generated.sketch.prompt == default_client.prompts[1]
    assert generated.provider == "mlx"
    assert generated.prompt == prove_client.prompts[0]
    assert DRAFT in default_client.prompts[1]
    assert DRAFT in prove_client.prompts[0]
    assert generated.sketch.lean_code in prove_client.prompts[0]
    assert "intermediate `have` statements or local lemmas" in default_client.prompts[1]
    assert "shortcut tactic or proof term" in default_client.prompts[1]
    assert "Preserve the Sketch's theorem statement" in prove_client.prompts[0]
    assert "Do not use `sorry` or `admit`" in prove_client.prompts[0]


def test_public_stage_methods_can_be_called_independently() -> None:
    default_client = FakeTextClient(DRAFT, SKETCH)
    prove_client = FakeTextClient(PROOF)
    generator = HybridLeanGenerator(
        model="draft-model",
        client=default_client,
        prove_model="prove-model",
        prove_client=prove_client,
    )

    draft = generator.generate_draft(request())
    sketch = generator.generate_sketch(request(), draft)
    proof = generator.generate_proof(request(), draft, sketch)

    assert draft.text == DRAFT
    assert "sorry" in sketch.lean_code
    assert proof.lean_code
    assert default_client.models == ["draft-model", "draft-model"]
    assert prove_client.models == ["prove-model"]


@pytest.mark.parametrize(
    ("route", "default_responses", "expected_default_calls"),
    [
        ("draft", (REVISED_DRAFT, REVISED_SKETCH), 2),
        ("sketch", (REVISED_SKETCH,), 1),
        ("prove", (), 0),
    ],
)
def test_repair_resumes_at_selected_stage_and_reuses_previous_outputs(
    route: RepairRoute,
    default_responses: tuple[str, ...],
    expected_default_calls: int,
) -> None:
    previous_draft, previous_sketch = prior_stages()
    default_client = FakeTextClient(
        '{"instruction":"Apply the selected repair plan to the current stage."}',
        *default_responses,
    )
    prove_client = FakeTextClient(REVISED_PROOF)
    generator = HybridLeanGenerator(
        model="draft-model",
        client=default_client,
        prove_model="prove-model",
        prove_client=prove_client,
    )

    generated = generator.repair(
        request(),
        feedback(route, draft=previous_draft, sketch=previous_sketch),
    )

    assert len(default_client.prompts) == expected_default_calls + 1
    assert "exactly one key, `instruction`" in default_client.prompts[0]
    assert "unknown identifier" in default_client.prompts[0]
    assert len(prove_client.prompts) == 1
    if route == "draft":
        assert generated.draft is not previous_draft
        assert generated.draft is not None and generated.draft.text == REVISED_DRAFT
        assert generated.sketch is not previous_sketch
    elif route == "sketch":
        assert generated.draft is previous_draft
        assert generated.sketch is not previous_sketch
        assert DRAFT in default_client.prompts[1]
    else:
        assert generated.draft is previous_draft
        assert generated.sketch is previous_sketch
    assert generated.draft is not None and generated.draft.text in prove_client.prompts[0]
    assert generated.sketch is not None
    assert generated.sketch.lean_code in prove_client.prompts[0]


@pytest.mark.parametrize(
    ("previous_draft", "previous_sketch", "responses", "expected_calls"),
    [
        (None, None, (REVISED_DRAFT, REVISED_SKETCH), 2),
        (prior_stages()[0], None, (REVISED_SKETCH,), 1),
    ],
)
def test_prove_repair_regenerates_from_earliest_missing_prerequisite(
    previous_draft: GeneratedDraft | None,
    previous_sketch: GeneratedSketch | None,
    responses: tuple[str, ...],
    expected_calls: int,
) -> None:
    default_client = FakeTextClient(
        '{"instruction":"Rebuild the earliest missing prerequisite."}',
        *responses,
    )
    prove_client = FakeTextClient(REVISED_PROOF)
    generator = HybridLeanGenerator(
        model="draft-model",
        client=default_client,
        prove_model="prove-model",
        prove_client=prove_client,
    )

    generated = generator.repair(
        request(),
        feedback("prove", draft=previous_draft, sketch=previous_sketch),
    )

    assert len(default_client.prompts) == expected_calls + 1
    assert len(prove_client.prompts) == 1
    assert generated.lean_code


def test_generation_failure_stops_pipeline_without_success_fallback() -> None:
    default_client = FakeTextClient(DRAFT, "This is not Lean code.")
    prove_client = FakeTextClient(PROOF)
    generator = HybridLeanGenerator(
        model="draft-model",
        client=default_client,
        prove_model="prove-model",
        prove_client=prove_client,
    )

    generated = generator.generate(request())

    assert generated.lean_code == ""
    assert generated.raw_model_output.startswith("[generation-error] sketch stage")
    assert generated.draft is not None
    assert generated.sketch is not None and generated.sketch.lean_code == ""
    assert prove_client.prompts == []


@pytest.mark.parametrize(
    "fake_gap",
    [
        "-- sorry",
        "/- outer /- sorry -/ comment -/",
        'have message : String := "sorry"',
    ],
)
def test_sketch_does_not_count_sorry_in_comment_or_string_as_a_gap(
    fake_gap: str,
) -> None:
    fake_sketch = f"""```lean
import Mathlib

theorem test (n : Nat) : n + 0 = n := by
  {fake_gap}
  exact Nat.add_zero n
```"""
    default_client = FakeTextClient(DRAFT, fake_sketch)
    prove_client = FakeTextClient(PROOF)
    generator = HybridLeanGenerator(
        model="draft-model",
        client=default_client,
        prove_model="prove-model",
        prove_client=prove_client,
    )

    generated = generator.generate(request())

    assert generated.lean_code
    assert generated.sketch is not None
    assert generated.sketch.has_gaps is False
    assert fake_gap in generated.sketch.raw_model_output
    assert len(prove_client.prompts) == 1
    assert generated.lean_code != generated.sketch.lean_code


def test_prove_output_with_sorry_is_failure() -> None:
    default_client = FakeTextClient(DRAFT, SKETCH)
    prove_client = FakeTextClient(SKETCH)
    generator = HybridLeanGenerator(
        model="draft-model",
        client=default_client,
        prove_model="prove-model",
        prove_client=prove_client,
    )

    generated = generator.generate(request())

    assert generated.lean_code == ""
    assert "left sorry or admit" in generated.raw_model_output
    assert "[raw-model-output]" in generated.raw_model_output
    assert SKETCH in generated.raw_model_output


def test_exact_match_draft_method_is_required_and_not_advisory() -> None:
    exact_request = ProofRequest(
        id="test",
        prompt="Prove it.",
        draft=ProofDraft(
            id="draft",
            matched_prompt="Prove it.",
            openmath_xml="<OMOBJ />",
            proof_strategy="Use induction on n.",
            sketch_steps=("Prove the base case.", "Apply the induction hypothesis."),
        ),
        exact_equivalence=True,
    )

    prompt = _draft_prompt_for(exact_request)

    assert "Required proof method from exact-match Draft" in prompt
    assert "must follow this proof strategy and these steps" in prompt
    assert "advisory only" not in prompt
    assert "Use induction on n." in prompt
    assert "Apply the induction hypothesis." in prompt


def test_approximate_draft_context_remains_advisory() -> None:
    approximate_request = ProofRequest(
        id="test",
        prompt="Prove it.",
        draft=ProofDraft(
            id="related",
            matched_prompt="Related problem.",
            openmath_xml="<OMOBJ />",
            proof_strategy="Unused target-specific strategy.",
            sketch_steps=(),
        ),
        exact_equivalence=False,
        related_draft_context=RelatedDraftContext(
            source_draft_id="related",
            strategy_notes=("Try a structural argument.",),
            sketch_steps=("Reduce to a local identity.",),
        ),
    )

    prompt = _draft_prompt_for(approximate_request)

    assert "Target-agnostic related Draft context (advisory only" in prompt
    assert "Try a structural argument." in prompt
    assert "Reduce to a local identity." in prompt


def test_square_continuity_prove_prompt_requires_valid_parenthesized_function() -> None:
    square_request = ProofRequest(
        id="square",
        prompt="x² が連続であることを説明してください。",
    )

    prompt = _prove_prompt_for(
        square_request,
        GeneratedDraft(text="Use epsilon-delta.", model="", raw_model_output=""),
        GeneratedSketch(
            lean_code=(
                "import Mathlib\n\n"
                "theorem bad : Continuous fun x : ℝ => x ^ 2 := by\n"
                "  sorry"
            ),
            model="",
            raw_model_output="",
        ),
    )

    assert "Continuous (fun x : ℝ => x ^ 2)" in prompt
    assert "Never emit `Continuous fun x : ℝ => ...`" in prompt
    assert "fun_prop" in prompt
