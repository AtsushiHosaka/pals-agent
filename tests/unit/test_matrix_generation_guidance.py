from pals_agent.generator import (
    _draft_prompt_for,
    _prove_prompt_for,
    _repair_instruction_prompt_for,
    _repair_route_prompt_for,
    _sketch_prompt_for,
)
from pals_agent.models import ProofRequest
from tests.unit.test_generator import feedback, prior_stages


def test_matrix_shape_and_carrier_guidance_reaches_formal_generation_and_repair_stages():
    request = ProofRequest(
        id="matrix",
        prompt=(
            "For every field K, [[1, 2], [3, 4]] times [[2, 0], [1, 2]] equals [[4, 4], [10, 8]]."
        ),
    )
    draft, sketch = prior_stages()
    failure = feedback("prove")
    prompts = [
        _sketch_prompt_for(request, draft),
        _prove_prompt_for(request, draft, sketch),
        _repair_instruction_prompt_for(request, failure),
        _repair_route_prompt_for(request, failure),
    ]
    for prompt in prompts:
        assert "(!![1, 2; 3, 4] : Matrix (Fin 2) (Fin 2) K)" in prompt
        assert "one row of vector-valued entries" in prompt
        assert "tactic-only edit cannot" in prompt
        assert "exact\nuser-supplied Lean harness" in prompt
        assert request.prompt in prompt


def test_matrix_guidance_does_not_leak_into_unrelated_requests():
    request = ProofRequest(id="natural", prompt="For every natural n, n + 0 = n.")
    assert "Lean matrix syntax" not in _draft_prompt_for(request)


def test_specific_inverse_preserves_both_products_and_the_supplied_witness():
    request = ProofRequest(
        id="inverse",
        prompt="Over a field K, prove that matrix B is the two-sided inverse of matrix A.",
    )
    draft, sketch = prior_stages()
    for prompt in (
        _sketch_prompt_for(request, draft),
        _prove_prompt_for(request, draft, sketch),
        _repair_route_prompt_for(request, feedback("draft")),
        _repair_instruction_prompt_for(request, feedback("draft")),
    ):
        assert "A * B = I and B * A = I for those exact matrices" in prompt
        assert "existence of some inverse is insufficient" in prompt
        assert "preserve the supplied witness's" in prompt
        assert "weaker statement IsUnit A" in prompt


def test_matrix_rank_uses_natural_matrix_rank_not_module_cardinal_rank():
    request = ProofRequest(
        id="matrix-rank",
        prompt=("For every field K, the rank of the 2 by 2 identity matrix over K "
                "is the natural number 2."),
    )
    draft, sketch = prior_stages()
    for prompt in (
        _sketch_prompt_for(request, draft),
        _prove_prompt_for(request, draft, sketch),
        _repair_route_prompt_for(request, feedback("prove")),
        _repair_instruction_prompt_for(request, feedback("prove")),
    ):
        assert "use `Matrix.rank M`" in prompt
        assert "takes a module TYPE V" in prompt
        assert "returns a Cardinal; never pass a matrix value" in prompt
        assert "(1 : Matrix (Fin 2) (Fin 2) K).rank = 2" in prompt
        assert "rather than replacing it with the dimension" in prompt


def test_matrix_local_let_uses_lean4_body_delimiters_through_generation_and_repair():
    request = ProofRequest(
        id="inverse-let",
        prompt="For every field K, the exchange matrix is a two-sided inverse of itself.",
    )
    draft, sketch = prior_stages()
    for prompt in (
        _sketch_prompt_for(request, draft),
        _prove_prompt_for(request, draft, sketch),
        _repair_route_prompt_for(request, feedback("prove")),
        _repair_instruction_prompt_for(request, feedback("prove")),
    ):
        assert "`let E : T := value; property E`" in prompt
        assert "`in` is not the Lean 4 let-body delimiter" in prompt
        assert "Parenthesize a complex initializer" in prompt
        assert request.prompt in prompt
