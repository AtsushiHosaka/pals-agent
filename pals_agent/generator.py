from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, replace
from typing import Protocol

from pals_agent.mlx import MlxError
from pals_agent.models import (
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
    RelatedDraftContext,
    RepairRoute,
    RepairRouteAttemptEvidence,
    RepairRouteDecision,
    RepairRouteSelectionError,
)
from pals_agent.ollama import OllamaClient, OllamaError
from pals_agent.openai import OpenAIError, OpenAIResponsesClient

_LEAN_BLOCK_RE = re.compile(r"```(?:lean4?|Lean)?\s*(.*?)```", re.DOTALL)
_MAX_REPAIR_INSTRUCTION_BYTES = 8_192


class TextGenerationClient(Protocol):
    def generate(self, *, model: str, prompt: str) -> str: ...


class RepairInstructionError(RuntimeError):
    """A repair-role response could not be parsed as the required typed input."""


@dataclass(frozen=True, slots=True)
class RepairInstruction:
    instruction: str
    raw_model_output: str


@dataclass(frozen=True, slots=True)
class HybridLeanGenerator:
    model: str
    provider: str = "ollama"
    client: TextGenerationClient | None = None
    ollama: OllamaClient | None = None
    openai: OpenAIResponsesClient | None = None
    prove_model: str | None = None
    prove_provider: str | None = None
    prove_client: TextGenerationClient | None = None

    def generate(self, request: ProofRequest) -> GeneratedProof:
        return self._generate_staged(request=request, feedback=None, start_stage="draft")

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        try:
            repair_instruction = self._generate_repair_instruction(request, feedback)
        except RepairInstructionError as exc:
            return self._failed_proof(
                f"[generation-error] repair stage returned invalid typed output: {exc}",
                draft=feedback.previous_draft,
                sketch=feedback.previous_sketch,
            )
        except (OllamaError, OpenAIError, MlxError) as exc:
            return self._failed_proof(
                f"[{self.provider}-error] repair generation failed: {exc}",
                draft=feedback.previous_draft,
                sketch=feedback.previous_sketch,
            )

        feedback = replace(
            feedback,
            repair_rationale=repair_instruction.instruction,
        )
        start_stage: RepairRoute = feedback.repair_route
        if feedback.previous_draft is None:
            start_stage = "draft"
        elif (
            start_stage == "prove"
            and (
                feedback.previous_sketch is None
                or not feedback.previous_sketch.lean_code.strip()
            )
        ):
            start_stage = "sketch"

        return self._generate_staged(
            request=request,
            feedback=feedback,
            start_stage=start_stage,
        )

    def _generate_repair_instruction(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairInstruction:
        client, model, _provider = self._default_endpoint()
        if client is None:
            raise RepairInstructionError("repair client is not configured")
        raw_model_output = client.generate(
            model=model,
            prompt=_repair_instruction_prompt_for(request, feedback),
        )
        return parse_repair_instruction(raw_model_output)

    def select_repair_route(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback,
    ) -> RepairRouteDecision:
        client, model, provider = self._default_endpoint()
        prompt = _repair_route_prompt_for(request, feedback)
        if client is None:
            raise RepairRouteSelectionError(
                f"{self.provider} client is not configured for DSP repair route selection.",
                prompt=prompt,
                model=model,
                provider=provider,
            )

        last_error: Exception | None = None
        attempt_outputs: list[str] = []
        selector_attempts: list[RepairRouteAttemptEvidence] = []
        started_at = time.monotonic()
        current_prompt = prompt
        for attempt in range(1, 4):
            try:
                raw_model_output = client.generate(model=model, prompt=current_prompt)
                attempt_outputs.append(raw_model_output)
                parsed = parse_repair_route_decision(raw_model_output)
                selector_attempts.append(
                    RepairRouteAttemptEvidence(
                        attempt=attempt,
                        outcome="selected",
                        diagnostic_code=None,
                        route=parsed.route,
                    )
                )
                return RepairRouteDecision(
                    route=parsed.route,
                    rationale=parsed.rationale,
                    raw_model_output=parsed.raw_model_output,
                    prompt=current_prompt,
                    model=model,
                    provider=provider,
                    elapsed_ms=_elapsed_ms(started_at),
                    attempt_outputs=tuple(attempt_outputs),
                    selector_attempts=tuple(selector_attempts),
                )
            except (OllamaError, OpenAIError, MlxError) as exc:
                last_error = exc
                attempt_outputs.append(f"[{provider}-transport-error]")
                selector_attempts.append(
                    RepairRouteAttemptEvidence(
                        attempt=attempt,
                        outcome="transport_error",
                        diagnostic_code="pals.repair_route_transport_error",
                        route=None,
                    )
                )
            except RepairRouteSelectionError as exc:
                last_error = exc
                selector_attempts.append(
                    RepairRouteAttemptEvidence(
                        attempt=attempt,
                        outcome="invalid_response",
                        diagnostic_code="pals.repair_route_invalid_response",
                        route=None,
                    )
                )
                if attempt < 3:
                    current_prompt = (
                        f"{prompt}\n\n"
                        f"The previous route response was invalid: {exc}\n"
                        "Return corrected strict JSON only with exactly the keys "
                        '`route` and `rationale`; route must be `draft`, `sketch`, '
                        "or `prove`."
                    )

        raise RepairRouteSelectionError(
            f"{provider} DSP repair route selection failed after 3 attempts.",
            prompt=current_prompt,
            model=model,
            provider=provider,
            elapsed_ms=_elapsed_ms(started_at),
            attempt_outputs=tuple(attempt_outputs),
            selector_attempts=tuple(selector_attempts),
        ) from last_error

    def _generate_staged(
        self,
        *,
        request: ProofRequest,
        feedback: GenerationFeedback | None,
        start_stage: RepairRoute,
    ) -> GeneratedProof:
        draft = feedback.previous_draft if feedback is not None else None
        sketch = feedback.previous_sketch if feedback is not None else None

        if start_stage == "draft":
            draft = self.generate_draft(request, feedback)
            sketch = None
            if not draft.text:
                return self._failed_proof(draft.raw_model_output, draft=draft)

        if start_stage in {"draft", "sketch"}:
            if draft is None:
                draft = self.generate_draft(request, feedback)
                if not draft.text:
                    return self._failed_proof(draft.raw_model_output, draft=draft)
            sketch = self.generate_sketch(request, draft, feedback)
            if not sketch.lean_code:
                return self._failed_proof(
                    sketch.raw_model_output,
                    draft=draft,
                    sketch=sketch,
                )

        if draft is None:
            draft = self.generate_draft(request, feedback)
            if not draft.text:
                return self._failed_proof(draft.raw_model_output, draft=draft)
        if sketch is None:
            sketch = self.generate_sketch(request, draft, feedback)
            if not sketch.lean_code:
                return self._failed_proof(
                    sketch.raw_model_output,
                    draft=draft,
                    sketch=sketch,
                )

        return self.generate_proof(request, draft, sketch, feedback)

    def generate_draft(
        self,
        request: ProofRequest,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedDraft:
        client, model, provider = self._default_endpoint()
        if client is None:
            error = f"[generation-error] {provider} client is not configured for draft stage."
            return GeneratedDraft(
                text="",
                model=model,
                raw_model_output=error,
                provider=provider,
            )

        prompt = _draft_prompt_for(request, feedback=feedback)
        started_at = time.monotonic()
        try:
            raw_model_output = client.generate(
                model=model,
                prompt=prompt,
            )
        except (OllamaError, OpenAIError, MlxError) as exc:
            return GeneratedDraft(
                text="",
                model=model,
                raw_model_output=f"[{provider}-error] draft generation failed: {exc}",
                prompt=prompt,
                provider=provider,
                elapsed_ms=_elapsed_ms(started_at),
            )

        text = raw_model_output.strip()
        if not text:
            raw_model_output = (
                f"[generation-error] draft stage returned empty output from {provider}."
            )
        return GeneratedDraft(
            text=text,
            model=model,
            raw_model_output=raw_model_output,
            prompt=prompt,
            provider=provider,
            elapsed_ms=_elapsed_ms(started_at),
        )

    def generate_sketch(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedSketch:
        client, model, provider = self._default_endpoint()
        if client is None:
            error = f"[generation-error] {provider} client is not configured for sketch stage."
            return GeneratedSketch(
                lean_code="",
                model=model,
                raw_model_output=error,
                provider=provider,
            )

        prompt = _sketch_prompt_for(request, draft, feedback=feedback)
        started_at = time.monotonic()
        try:
            raw_model_output = client.generate(
                model=model,
                prompt=prompt,
            )
        except (OllamaError, OpenAIError, MlxError) as exc:
            return GeneratedSketch(
                lean_code="",
                model=model,
                raw_model_output=f"[{provider}-error] sketch generation failed: {exc}",
                prompt=prompt,
                provider=provider,
                elapsed_ms=_elapsed_ms(started_at),
            )

        lean_code = extract_lean_code(raw_model_output) or ""
        if not lean_code:
            error = f"[generation-error] sketch stage did not return Lean code from {provider}."
            return GeneratedSketch(
                lean_code="",
                model=model,
                raw_model_output=_generation_error_with_raw_output(
                    error,
                    raw_model_output,
                ),
                prompt=prompt,
                provider=provider,
                elapsed_ms=_elapsed_ms(started_at),
            )
        return GeneratedSketch(
            lean_code=lean_code,
            model=model,
            raw_model_output=raw_model_output,
            has_gaps=_has_sorry_gap(lean_code),
            prompt=prompt,
            provider=provider,
            elapsed_ms=_elapsed_ms(started_at),
        )

    def generate_proof(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        sketch: GeneratedSketch,
        feedback: GenerationFeedback | None = None,
    ) -> GeneratedProof:
        client, model, provider = self._prove_endpoint()
        if client is None:
            return self._failed_proof(
                f"[generation-error] {provider} client is not configured for prove stage.",
                draft=draft,
                sketch=sketch,
                model=model,
                provider=provider,
            )

        prompt = _prove_prompt_for(request, draft, sketch, feedback=feedback)
        started_at = time.monotonic()
        try:
            raw_model_output = client.generate(
                model=model,
                prompt=prompt,
            )
        except (OllamaError, OpenAIError, MlxError) as exc:
            return self._failed_proof(
                f"[{provider}-error] prove generation failed: {exc}",
                draft=draft,
                sketch=sketch,
                model=model,
                prompt=prompt,
                provider=provider,
                elapsed_ms=_elapsed_ms(started_at),
            )

        lean_code = extract_lean_code(raw_model_output) or ""
        if not lean_code:
            raw_model_output = _generation_error_with_raw_output(
                f"[generation-error] prove stage did not return Lean code from {provider}.",
                raw_model_output,
            )
        elif re.search(r"\b(?:sorry|admit)\b", _lean_code_only(lean_code)):
            lean_code = ""
            raw_model_output = _generation_error_with_raw_output(
                f"[generation-error] prove stage left sorry or admit in Lean code from {provider}.",
                raw_model_output,
            )

        return GeneratedProof(
            lean_code=lean_code,
            model=model,
            raw_model_output=raw_model_output,
            draft=draft,
            sketch=sketch,
            prompt=prompt,
            provider=provider,
            elapsed_ms=_elapsed_ms(started_at),
        )

    def _failed_proof(
        self,
        error: str,
        *,
        draft: GeneratedDraft | None = None,
        sketch: GeneratedSketch | None = None,
        model: str | None = None,
        prompt: str = "",
        provider: str = "",
        elapsed_ms: int = 0,
    ) -> GeneratedProof:
        return GeneratedProof(
            lean_code="",
            model=model or (self.prove_model or self.model),
            raw_model_output=error,
            draft=draft,
            sketch=sketch,
            prompt=prompt,
            provider=provider,
            elapsed_ms=elapsed_ms,
        )

    def _default_endpoint(self) -> tuple[TextGenerationClient | None, str, str]:
        return self.client or self.openai or self.ollama, self.model, self.provider

    def _prove_endpoint(self) -> tuple[TextGenerationClient | None, str, str]:
        client = self.prove_client or self.client or self.openai or self.ollama
        model = self.prove_model or self.model
        provider = self.prove_provider or self.provider
        return client, model, provider


def extract_lean_code(text: str) -> str | None:
    match = _LEAN_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()

    stripped = text.strip()
    if (
        stripped.startswith("import ")
        or stripped.startswith("theorem ")
        or stripped.startswith("example ")
    ):
        return stripped
    return None


def _has_sorry_gap(lean_code: str) -> bool:
    return re.search(r"\bsorry\b", _lean_code_only(lean_code)) is not None


def _generation_error_with_raw_output(error: str, raw_model_output: str) -> str:
    return f"{error}\n\n[raw-model-output]\n{raw_model_output}"


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _lean_code_only(lean_code: str) -> str:
    """Remove comments and strings before checking for a proof-hole token."""
    code: list[str] = []
    index = 0
    length = len(lean_code)
    while index < length:
        if lean_code.startswith("--", index):
            newline = lean_code.find("\n", index + 2)
            if newline == -1:
                break
            code.append("\n")
            index = newline + 1
            continue

        if lean_code.startswith("/-", index):
            depth = 1
            index += 2
            while index < length and depth:
                if lean_code.startswith("/-", index):
                    depth += 1
                    index += 2
                elif lean_code.startswith("-/", index):
                    depth -= 1
                    index += 2
                else:
                    if lean_code[index] == "\n":
                        code.append("\n")
                    index += 1
            continue

        if lean_code[index] == '"':
            index += 1
            while index < length:
                if lean_code[index] == "\\":
                    index += 2
                elif lean_code[index] == '"':
                    index += 1
                    break
                else:
                    if lean_code[index] == "\n":
                        code.append("\n")
                    index += 1
            continue

        code.append(lean_code[index])
        index += 1
    return "".join(code)


def parse_repair_route_decision(text: str) -> RepairRouteDecision:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RepairRouteSelectionError(
            "DSP repair route selector returned invalid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise RepairRouteSelectionError(
            "DSP repair route selector returned JSON that is not an object."
        )

    route = payload.get("route")
    rationale = payload.get("rationale")
    if route not in {"draft", "sketch", "prove"}:
        raise RepairRouteSelectionError(
            "DSP repair route selector returned an invalid route."
        )

    return RepairRouteDecision(
        route=_repair_route_from_string(str(route)),
        rationale=str(rationale or "").strip(),
        raw_model_output=text,
    )


def parse_repair_instruction(text: str) -> RepairInstruction:
    """Accept exactly the closed repair-role handoff object."""

    try:
        payload = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise RepairInstructionError("repair role returned invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"instruction"}:
        raise RepairInstructionError("repair role output has an invalid shape")
    instruction = payload["instruction"]
    if (
        not isinstance(instruction, str)
        or not instruction.strip()
        or len(instruction.encode("utf-8")) > _MAX_REPAIR_INSTRUCTION_BYTES
    ):
        raise RepairInstructionError("repair role instruction is invalid")
    return RepairInstruction(instruction=instruction, raw_model_output=text)


def _repair_route_from_string(value: str) -> RepairRoute:
    route = value.strip().lower()
    if route == "sketch":
        return "sketch"
    if route == "prove":
        return "prove"
    if route == "draft":
        return "draft"
    raise RepairRouteSelectionError(f"Unsupported DSP repair route: {value}")


def _draft_prompt_for(
    request: ProofRequest,
    feedback: GenerationFeedback | None = None,
) -> str:
    draft_guidance = _draft_guidance(request)
    return f"""Write an informal natural-language proof Draft for a theorem-proving request.
Return only the Draft. Do not write Lean code yet.
Give an ordered, mathematically explicit sequence of atomic proof moves that can be
translated into intermediate Lean `have` statements or local lemmas.
Follow any required exact-match proof method below.

Problem:
{request.prompt}
{_formal_statement_guidance(request.formal_statement)}
{draft_guidance}
{_repair_guidance(feedback)}
"""


def _sketch_prompt_for(
    request: ProofRequest,
    draft: GeneratedDraft,
    feedback: GenerationFeedback | None = None,
) -> str:
    return f"""Translate the informal Draft into a Lean 4/mathlib formal Sketch.
Return exactly one fenced Lean code block. Do not include prose outside the code block.
The code must start with `import Mathlib`.
Use Lean 4 syntax. Do not use Lean 3 imports such as `topology.*`, `data.*`, or
`linear_algebra.*`. Do not use `begin ... end`.
You must prove the exact Lean theorem harness shown below when one is provided.
Preserve the Draft's proof structure with intermediate `have` statements or local lemmas.
Leave one or more localized `sorry` gaps for the substantive proof obligations.
Do not use a shortcut tactic or proof term to close the whole theorem instead of
representing the Draft's intermediate reasoning.

Problem:
{request.prompt}
{_formal_statement_guidance(request.formal_statement)}
Retrieved method context (its required/advisory status is declared inside):
{_draft_guidance(request)}
Required informal Draft to formalize:
<draft>
{draft.text}
</draft>
{_repair_guidance(feedback)}
"""


def _prove_prompt_for(
    request: ProofRequest,
    draft: GeneratedDraft,
    sketch: GeneratedSketch,
    feedback: GenerationFeedback | None = None,
) -> str:
    return f"""Complete a Lean 4/mathlib proof from the supplied Draft and formal Sketch.
Return exactly one fenced Lean code block. Do not include prose outside the code block.
The code must start with `import Mathlib`.
Use Lean 4 syntax. Do not use Lean 3 imports such as `topology.*`, `data.*`, or
`linear_algebra.*`. Do not use `begin ... end`.
Preserve the Sketch's theorem statement and mathematical target. Fill every gap with
valid Lean code. Treat every theorem name and proof term in the Sketch as untrusted:
correct or replace invalid intermediate code before returning. Prefer a small,
well-supported mathlib proof over a longer proof that merely looks plausible. In
particular, for routine continuity goals prefer `fun_prop` over inventing a
product-domain type annotation for `continuous_mul`. The learner-facing explanation
is generated separately from the verified theorem and must still expand the Draft's
mathematical argument.
{_lean_reliability_guidance(request)}
Do not use `sorry` or `admit`.
You must prove the exact Lean theorem harness shown below when one is provided.

Problem:
{request.prompt}
{_formal_statement_guidance(request.formal_statement)}
Retrieved method context (its required/advisory status is declared inside):
{_draft_guidance(request)}
Informal Draft whose required proof method must be preserved:
<draft>
{draft.text}
</draft>

Lean Sketch to complete:
```lean
{sketch.lean_code}
```
{_repair_guidance(feedback)}
"""


def _lean_reliability_guidance(request: ProofRequest) -> str:
    normalized = request.prompt.lower().replace(" ", "")
    is_square = any(
        token in normalized
        for token in ("x²", "x^2", "x**2", "xの2乗", "x二乗")
    )
    is_continuity = "連続" in normalized or "continuous" in normalized
    if not (is_square and is_continuity):
        return ""

    return """
This request is specifically the continuity of the real square function. Use a
syntactically valid parenthesized function proposition. The following is the
preferred reliable shape (the theorem name may differ):

```lean
import Mathlib

theorem square_continuous : Continuous (fun x : ℝ => x ^ 2) := by
  fun_prop
```

Never emit `Continuous fun x : ℝ => ...`; Lean requires parentheses around the
function expression in this proposition.
"""


def _prompt_for(request: ProofRequest, feedback: GenerationFeedback | None = None) -> str:
    """Compatibility prompt for callers that only need complete-proof guidance."""
    placeholder_draft = GeneratedDraft(
        text=_draft_guidance(request).strip(),
        model="",
        raw_model_output="",
    )
    placeholder_sketch = GeneratedSketch(
        lean_code=request.formal_statement or "import Mathlib\n-- No formal sketch supplied.",
        model="",
        raw_model_output="",
    )
    return _prove_prompt_for(
        request,
        placeholder_draft,
        placeholder_sketch,
        feedback=feedback,
    )


def _repair_route_prompt_for(request: ProofRequest, feedback: GenerationFeedback) -> str:
    diagnostics = "\n".join(
        f"- {_format_diagnostic_for_prompt(diagnostic)}"
        for diagnostic in feedback.diagnostics
    )
    return f"""Choose where the PALS Draft-Sketch-Prove repair loop should resume.
Return exactly one compact JSON object with keys `route` and `rationale`.
The `route` value must be exactly one of: `draft`, `sketch`, `prove`.

Route meanings:
- `draft`: The formal statement, problem interpretation, theorem harness, imports, or
  required formalization fragments may be wrong. Restart from draft.
- `sketch`: The formal statement is likely right, but the proof plan or decomposition
  is probably wrong. Restart from sketch and then prove.
- `prove`: The formal statement and proof sketch are likely right; the failure looks
  local to Lean tactics, theorem names, coercions, imports, or a small proof term.
  Resume directly at prove.

If diagnostics include `pals.repair_stagnation`, the same errors survived at least
three attempts. Do not reflexively repeat the previous route. Decide whether the
formal decomposition itself should be regenerated at `sketch`, or whether there is a
specific materially different `prove` repair. Explain that choice in `rationale`.

Problem:
{request.prompt}

Formal statement:
{request.formal_statement or "(none)"}

Failed attempt number:
{feedback.attempt}

Failed Lean code:
```lean
{feedback.previous_lean_code.strip()}
```

Previous informal Draft:
<draft>
{feedback.previous_draft.text if feedback.previous_draft is not None else "(none)"}
</draft>

Previous Lean Sketch:
```lean
{feedback.previous_sketch.lean_code if feedback.previous_sketch is not None else "-- (none)"}
```

Lean diagnostics:
{diagnostics or "- no diagnostics returned"}
"""


def _repair_instruction_prompt_for(
    request: ProofRequest,
    feedback: GenerationFeedback,
) -> str:
    """Build the one typed handoff from a valid route to its selected stage."""

    return f"""Create the PALS repair handoff for the selected DSP route.
Return exactly one JSON object with exactly one key, `instruction`.
`instruction` must be a concise, concrete repair plan for the selected `{feedback.repair_route}`
stage. It must address the actual diagnostics and failed Lean candidate below. Do not return Lean
code, a route choice, an evaluation rubric, or any extra JSON field.

Problem:
{request.prompt}
{_formal_statement_guidance(request.formal_statement)}
{_repair_guidance(feedback)}
"""


def _draft_guidance(request: ProofRequest) -> str:
    draft = request.draft
    if request.related_draft_contexts:
        required_contexts = tuple(
            context
            for context in request.related_draft_contexts
            if (
                context.exact_equivalence
                and context.selected_proof_method == "epsilon_delta"
            )
        )
        contexts = "\n\n".join(
            _related_context_guidance(context)
            for context in request.related_draft_contexts
        )
        if required_contexts:
            return f"""
Required ε–δ proof method from exact retrieved Draft (not a target or verification harness):
The user's Problem remains the only theorem target. The generated Draft, Sketch, and Proof must
follow the ε–δ strategy and steps below; do not close it with a continuity shortcut.

{contexts}
"""
        return f"""
Reranked related Draft contexts (advisory only, never targets or harnesses):
Each candidate is contextual evidence only. Derive every target-specific detail
from the user's Problem and approved harness only.

{contexts}
"""
    if draft is None:
        return (
            "\nNo reusable draft was found. Formalize the statement conservatively and "
            "avoid claiming success unless the Lean code proves the requested theorem.\n"
        )

    if not request.exact_equivalence:
        related = request.related_draft_context
        strategy_notes = _prompt_list(
            related.strategy_notes if related is not None else (),
        )
        sketch_steps = _prompt_list(
            related.sketch_steps if related is not None else (),
        )
        return f"""
Target-agnostic related Draft context (advisory only, never the target or a harness):
The retrieved candidate is only approximate. Target-specific mathematical expressions
are excluded.
Derive every target-specific detail from the user's Problem and approved harness only.

Related strategy notes after target redaction:
{strategy_notes}

Related sketch pattern after target redaction:
{sketch_steps}
"""

    sketch = "\n".join(f"- {step}" for step in draft.sketch_steps)
    return f"""
Required proof method from exact-match Draft (not a verification harness):
The approved harness above, when present, is the only target that may be verified.
The generated Draft, Sketch, and Proof must follow this proof strategy and these steps.

Draft proof strategy:
{draft.proof_strategy}

Sketch:
{sketch}
"""


def _prompt_list(items: tuple[str, ...]) -> str:
    if not items:
        return "- (none retained after target redaction)"
    return "\n".join(f"- {item}" for item in items)


def _related_context_guidance(context: RelatedDraftContext) -> str:
    return f"""Candidate `{context.source_draft_id}` strategy notes:
{_prompt_list(context.strategy_notes)}

Candidate `{context.source_draft_id}` sketch pattern:
{_prompt_list(context.sketch_steps)}"""


def _formal_statement_guidance(formal_statement: str | None) -> str:
    if not formal_statement:
        return ""
    return f"""
Exact Lean formal statement or harness to prove:
```lean
{formal_statement.strip()}
```
"""


def _repair_guidance(feedback: GenerationFeedback | None) -> str:
    if feedback is None:
        return ""

    diagnostics = "\n".join(
        f"- {_format_diagnostic_for_prompt(diagnostic)}"
        for diagnostic in feedback.diagnostics
    )
    unknown_identifiers = sorted(
        {
            identifier
            for diagnostic in feedback.diagnostics
            if diagnostic.code == "lean.unknownIdentifier"
            for identifier in re.findall(r"`([^`]+)`", diagnostic.message)
        }
    )
    unknown_identifier_guidance = ""
    if unknown_identifiers:
        unknown_identifier_guidance = (
            "\nIdentifiers rejected by Lean and forbidden in the next candidate unless "
            "replaced by a verified fully-qualified declaration:\n"
            + "\n".join(f"- `{identifier}`" for identifier in unknown_identifiers)
        )
    return f"""
Previous attempt failed Lean validation or compilation.
The selected DSP repair route is `{feedback.repair_route}`.
Route rationale:
{feedback.repair_rationale or "No rationale recorded."}

At the current DSP stage, correct the identified failure while keeping the exact
theorem harness. Every error diagnostic below is mandatory to fix. Produce materially
corrected Lean code, not a paraphrase of the same failing term. Do not reuse a failing
proof term, tactic sequence, or unknown identifier unless the diagnostic is explicitly
addressed. Warnings do not excuse any remaining error.

Failed attempt number:
{feedback.attempt}

Failed Lean code:
```lean
{feedback.previous_lean_code.strip()}
```

Lean diagnostics to fix:
{diagnostics or "- no diagnostics returned"}
{unknown_identifier_guidance}
"""


def _format_diagnostic_for_prompt(diagnostic: object) -> str:
    code = getattr(diagnostic, "code", None)
    severity = getattr(diagnostic, "severity", "error")
    line = getattr(diagnostic, "line", None)
    column = getattr(diagnostic, "column", None)
    message = getattr(diagnostic, "message", "")
    location = ""
    if line is not None:
        location = f" line {line}"
        if column is not None:
            location += f":{column}"
    code_part = f" [{code}]" if code else ""
    return f"{severity}{location}{code_part}: {message}"
