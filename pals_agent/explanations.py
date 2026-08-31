from __future__ import annotations

import json
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from pals_agent.lean_target import LeanTargetDeclaration

_LEAN_SOURCE_TERM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    # Keep only terms that are recognisably Lean-specific in ordinary learner prose.
    # English mathematical explanations legitimately use words such as "let", "left",
    # "right", "continuity", and "theorem".
    r"aesop|all_goals|field_simp|gcongr|infer_instance|linarith|native_decide|"
    r"nlinarith|norm_cast|norm_num|omega|rcases|rfl|ring_nf|rw|simpa|simp|subst|tauto"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_LEAN_QUALIFIED_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?![A-Za-z0-9_])"
)
_BARE_LATEX_JSON_BACKSLASH_PATTERN = re.compile(
    r'(?<!\\)\\(?=(?:[A-Za-z]{2,}|(?!["\\\\/bfnrt]|u[0-9A-Fa-f]{4})))'
)


class TextGenerationClient(Protocol):
    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: float | None = None,
    ) -> str: ...


class ExplanationGenerationError(RuntimeError):
    """Raised when an LLM response cannot become a Lean-grounded explanation."""

    def __init__(self, message: str, *, attempt_outputs: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.attempt_outputs = attempt_outputs


class ExplanationDeadlineExceeded(ExplanationGenerationError):
    """Raised when explanation work reaches its monotonic hard deadline."""


class ProofOutputReviewError(RuntimeError):
    """Raised when an independent review cannot approve learner-facing output."""


@dataclass(frozen=True, slots=True)
class ProofOutputReview:
    """An independent approval attached to one exact learner-facing output."""

    kind: Literal["explanation", "clarification"]
    reviewer_provider: str
    reviewer_model: str
    session_id: str
    rationale: str


@dataclass(frozen=True, slots=True)
class ProofSemanticReview:
    """An independently reviewed decision, ready for durable settlement."""

    decision: Literal["approved", "rejected"]
    rationale: str
    reviewer_provider: str
    reviewer_model: str
    session_id: str


@dataclass(frozen=True, slots=True)
class LeanLineReference:
    start_line: int
    end_line: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class ExplanationSection:
    id: str
    title: str
    summary: str
    references: tuple[LeanLineReference, ...]


@dataclass(frozen=True, slots=True)
class ProofExplanation:
    overview: str
    sections: tuple[ExplanationSection, ...]
    conclusion: str
    model: str
    provider: str
    prompt: str
    raw_model_output: str
    elapsed_ms: int


class ProofOutputReviewer(Protocol):
    """A separate LLM session that approves output before learner publication."""

    def review_explanation(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        explanation: ProofExplanation,
        language: str,
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofOutputReview: ...

    def review_clarification(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        explanation: ProofExplanation,
        clarification: ProofClarification,
        language: str,
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofOutputReview: ...


class ProofSemanticReviewer(Protocol):
    """A separate LLM session that decides whether a Lean candidate matches the request."""

    def review_proof(
        self,
        *,
        theorem_statement: str,
        formal_statement: str | None,
        target_declaration: LeanTargetDeclaration,
        lean_code: str,
        timeout_seconds: float | None = None,
    ) -> ProofSemanticReview: ...


@dataclass(frozen=True, slots=True)
class LeanGroundedOutputReviewer:
    """Fail-closed reviewer for explanation and clarification publication.

    The reviewer is built with a separate client instance from the generator.  Each
    `generate` call is a standalone Responses request, so it does not inherit the
    generator's prompt or response state even when the release model is the same.
    """

    client: TextGenerationClient
    model: str
    provider: str
    max_attempts: int = 2
    monotonic: Callable[[], float] = time.monotonic
    session_id_factory: Callable[[], uuid.UUID] = uuid.uuid4

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if not self.provider.strip():
            raise ValueError("provider must be non-empty")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between one and three")

    def review_explanation(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        explanation: ProofExplanation,
        language: str,
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofOutputReview:
        return self._review(
            kind="explanation",
            session_id=str(self.session_id_factory()),
            prompt=_output_review_prompt(
                theorem_statement=theorem_statement,
                lean_code=lean_code,
                explanation=explanation,
                language=language,
            ),
            deadline=deadline,
            timeout_seconds=timeout_seconds,
        )

    def review_clarification(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        explanation: ProofExplanation,
        clarification: ProofClarification,
        language: str,
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofOutputReview:
        return self._review(
            kind="clarification",
            session_id=str(self.session_id_factory()),
            prompt=_output_review_prompt(
                theorem_statement=theorem_statement,
                lean_code=lean_code,
                explanation=explanation,
                clarification=clarification,
                language=language,
            ),
            deadline=deadline,
            timeout_seconds=timeout_seconds,
        )

    def _review(
        self,
        *,
        kind: Literal["explanation", "clarification"],
        session_id: str,
        prompt: str,
        deadline: float | None,
        timeout_seconds: float | None,
    ) -> ProofOutputReview:
        _validate_deadline_options(deadline, timeout_seconds)
        validation_error = ""
        current_prompt = prompt
        for attempt in range(1, self.max_attempts + 1):
            transport_timeout = _remaining_transport_timeout(
                deadline=deadline,
                timeout_seconds=timeout_seconds,
                monotonic=self.monotonic,
            )
            try:
                if transport_timeout is None:
                    raw_output = self.client.generate(
                        model=self.model,
                        prompt=current_prompt,
                    )
                else:
                    raw_output = self.client.generate(
                        model=self.model,
                        prompt=current_prompt,
                        timeout_seconds=transport_timeout,
                    )
            except Exception as exc:
                raise ProofOutputReviewError("independent output review transport failed") from exc
            _raise_if_deadline_reached(deadline, self.monotonic)
            try:
                approved, rationale = _output_review_decision(_parse_json_object(raw_output))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                _raise_if_deadline_reached(deadline, self.monotonic)
                validation_error = str(exc)
                if attempt < self.max_attempts:
                    current_prompt = (
                        f"{prompt}\n\nThe previous response failed schema validation: "
                        f"{validation_error}\nReturn the exact JSON object only."
                    )
                continue
            if approved:
                return ProofOutputReview(
                    kind=kind,
                    reviewer_provider=self.provider,
                    reviewer_model=self.model,
                    session_id=session_id,
                    rationale=rationale,
                )
            validation_error = "independent reviewer rejected the output"
            if attempt < self.max_attempts:
                current_prompt = (
                    f"{prompt}\n\nThe previous review rejected the candidate. Re-evaluate the "
                    "same evidence independently and return the exact JSON decision only. Do not "
                    "infer a preferred outcome from this retry."
                )
                continue
            raise ProofOutputReviewError(validation_error)

        raise ProofOutputReviewError(
            "independent output review did not approve the output: "
            f"{validation_error}",
        )


@dataclass(frozen=True, slots=True)
class LeanProofSemanticReviewer:
    """Fail closed before the API may publish a Lean-verified candidate."""

    client: TextGenerationClient
    model: str
    provider: str
    max_attempts: int = 2
    session_id_factory: Callable[[], uuid.UUID] = uuid.uuid4

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.provider.strip():
            raise ValueError("semantic reviewer model and provider must be non-empty")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between one and three")

    def review_proof(
        self,
        *,
        theorem_statement: str,
        formal_statement: str | None,
        target_declaration: LeanTargetDeclaration,
        lean_code: str,
        timeout_seconds: float | None = None,
    ) -> ProofSemanticReview:
        session_id = str(self.session_id_factory())
        prompt = _proof_semantic_review_prompt(
            theorem_statement=theorem_statement,
            formal_statement=formal_statement,
            target_declaration=target_declaration,
            lean_code=lean_code,
        )
        validation_error = ""
        current_prompt = prompt
        for attempt in range(1, self.max_attempts + 1):
            try:
                if timeout_seconds is None:
                    raw_output = self.client.generate(model=self.model, prompt=current_prompt)
                else:
                    raw_output = self.client.generate(
                        model=self.model,
                        prompt=current_prompt,
                        timeout_seconds=timeout_seconds,
                    )
                decision, rationale = _proof_semantic_review_decision(
                    _parse_json_object(raw_output)
                )
            except Exception as exc:
                validation_error = str(exc)
                if attempt < self.max_attempts:
                    current_prompt = (
                        f"{prompt}\n\nThe previous response was invalid: {validation_error}. "
                        "Return the exact JSON object only."
                    )
                    continue
                return ProofSemanticReview(
                    decision="rejected",
                    rationale="The independent proof review could not be completed.",
                    reviewer_provider=self.provider,
                    reviewer_model=self.model,
                    session_id=session_id,
                )
            return ProofSemanticReview(
                decision=decision,
                rationale=rationale,
                reviewer_provider=self.provider,
                reviewer_model=self.model,
                session_id=session_id,
            )
        raise AssertionError("semantic reviewer exhausted without a decision")


@dataclass(frozen=True, slots=True)
class ProofClarification:
    section_id: str
    question: str
    answer: str
    key_points: tuple[str, ...]
    references: tuple[LeanLineReference, ...]
    model: str
    provider: str
    prompt: str
    raw_model_output: str
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class LeanProofExplainer:
    client: TextGenerationClient
    model: str
    provider: str
    max_attempts: int = 2
    monotonic: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if not self.provider.strip():
            raise ValueError("provider must be non-empty")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between one and three")

    def explain(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        verified: bool,
        language: str = "ja",
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofExplanation:
        if not verified:
            raise ExplanationGenerationError(
                "A concise explanation can only be generated from Lean code accepted by Lean."
            )
        if not lean_code.strip():
            raise ExplanationGenerationError("Verified Lean code is required for explanation.")

        prompt = _explanation_prompt(
            theorem_statement=theorem_statement,
            lean_code=lean_code,
            language=language,
            require_epsilon_delta=_is_x_squared_continuity(theorem_statement),
        )
        _validate_deadline_options(deadline, timeout_seconds)
        started_at = self.monotonic()
        payload, raw_output = self._generate_validated(
            prompt=prompt,
            validator=lambda value: _parse_explanation(
                value,
                lean_code,
                language=language,
                require_epsilon_delta=_is_x_squared_continuity(theorem_statement),
            ),
            deadline=deadline,
            timeout_seconds=timeout_seconds,
        )
        overview, sections, conclusion = payload
        return ProofExplanation(
            overview=overview,
            sections=sections,
            conclusion=conclusion,
            model=self.model,
            provider=self.provider,
            prompt=prompt,
            raw_model_output=raw_output,
            elapsed_ms=_elapsed_ms(started_at, self.monotonic),
        )

    def clarify(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        verified: bool,
        explanation: ProofExplanation,
        section_id: str,
        question: str,
        selected_text: str = "",
        after_clarification_id: str | None = None,
        language: str = "ja",
        deadline: float | None = None,
        timeout_seconds: float | None = None,
    ) -> ProofClarification:
        if verified is not True:
            raise ExplanationGenerationError(
                "A clarification can only be generated from Lean code accepted by Lean."
            )
        if not lean_code.strip():
            raise ExplanationGenerationError("Verified Lean code is required for clarification.")
        selected = next(
            (section for section in explanation.sections if section.id == section_id),
            None,
        )
        if selected is None:
            raise ExplanationGenerationError(f"Unknown explanation section: {section_id}")
        if not _trim_unicode_whitespace(question):
            raise ExplanationGenerationError("A clarification question is required.")

        prompt = _clarification_prompt(
            theorem_statement=theorem_statement,
            lean_code=lean_code,
            explanation=explanation,
            selected=selected,
            question=question,
            selected_text=selected_text,
            after_clarification_id=after_clarification_id,
            language=language,
        )
        _validate_deadline_options(deadline, timeout_seconds)
        started_at = self.monotonic()
        payload, raw_output = self._generate_validated(
            prompt=prompt,
            validator=lambda value: _parse_clarification(
                value,
                lean_code=lean_code,
                section_id=section_id,
                selected=selected,
                language=language,
            ),
            deadline=deadline,
            timeout_seconds=timeout_seconds,
        )
        answer, key_points, references = payload
        return ProofClarification(
            section_id=section_id,
            question=question,
            answer=answer,
            key_points=key_points,
            references=references,
            model=self.model,
            provider=self.provider,
            prompt=prompt,
            raw_model_output=raw_output,
            elapsed_ms=_elapsed_ms(started_at, self.monotonic),
        )

    def _generate_validated(
        self,
        *,
        prompt: str,
        validator: Any,
        deadline: float | None,
        timeout_seconds: float | None,
    ) -> tuple[Any, str]:
        outputs: list[str] = []
        validation_error = ""
        current_prompt = prompt
        for attempt in range(1, self.max_attempts + 1):
            transport_timeout = _remaining_transport_timeout(
                deadline=deadline,
                timeout_seconds=timeout_seconds,
                monotonic=self.monotonic,
            )
            if transport_timeout is None:
                raw_output = self.client.generate(
                    model=self.model,
                    prompt=current_prompt,
                )
            else:
                raw_output = self.client.generate(
                    model=self.model,
                    prompt=current_prompt,
                    timeout_seconds=transport_timeout,
                )
            _raise_if_deadline_reached(deadline, self.monotonic)
            outputs.append(raw_output)
            try:
                parsed = validator(_parse_json_object(raw_output))
                _raise_if_deadline_reached(deadline, self.monotonic)
                return parsed, raw_output
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                _raise_if_deadline_reached(deadline, self.monotonic)
                validation_error = str(exc)
                if attempt < self.max_attempts:
                    current_prompt = (
                        f"{prompt}\n\nYour previous response was invalid: {validation_error}\n"
                        "Re-read the canonical line table and return a corrected JSON object "
                        "only. Copy each excerpt byte-for-byte from the `text` fields, preserving "
                        "leading spaces and joining multi-line ranges with `\\n`. Do not omit "
                        "Lean references."
                    )

        raise ExplanationGenerationError(
            f"The explanation model returned invalid grounded JSON after "
            f"{self.max_attempts} attempts: {validation_error}",
            attempt_outputs=tuple(outputs),
        )


def proof_explanation_from_api(
    payload: dict[str, Any],
    *,
    lean_code: str,
) -> ProofExplanation:
    overview, sections, conclusion = _parse_explanation(payload, lean_code)
    elapsed_ms = payload.get("elapsed_ms", 0)
    if type(elapsed_ms) is not int or elapsed_ms < 0:
        raise ValueError("elapsed_ms must be a non-negative integer")
    return ProofExplanation(
        overview=overview,
        sections=sections,
        conclusion=conclusion,
        model=_required_text(payload, "model"),
        provider=_required_text(payload, "provider"),
        prompt="",
        raw_model_output="",
        elapsed_ms=elapsed_ms,
    )


def _parse_explanation(
    payload: dict[str, Any],
    lean_code: str,
    *,
    language: str = "ja",
    require_epsilon_delta: bool = False,
) -> tuple[str, tuple[ExplanationSection, ...], str]:
    _require_output_language(language)
    overview = _required_bounded_language_text(
        payload,
        "overview",
        minimum=1,
        maximum=600,
    )
    conclusion = _required_bounded_language_text(
        payload,
        "conclusion",
        minimum=1,
        maximum=600,
    )
    _reject_lean_source_terms(overview, "overview")
    _reject_lean_source_terms(conclusion, "conclusion")
    raw_sections = _required_list(payload, "sections")
    if not 1 <= len(raw_sections) <= 20:
        raise ValueError("sections must contain between 1 and 20 items")

    sections: list[ExplanationSection] = []
    seen_ids: set[str] = set()
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            raise TypeError("each explanation section must be an object")
        section_id = _required_text(raw_section, "id")
        if section_id in seen_ids:
            raise ValueError(f"duplicate explanation section id: {section_id}")
        seen_ids.add(section_id)
        references = _parse_references(raw_section, lean_code)
        title = _required_bounded_language_text(
            raw_section,
            "title",
            minimum=1,
            maximum=80,
        )
        summary = _required_bounded_language_text(
            raw_section,
            "summary",
            minimum=1,
            maximum=800,
        )
        _reject_lean_source_terms(title, "section title")
        _reject_lean_source_terms(summary, "section summary")
        sections.append(
            ExplanationSection(
                id=section_id,
                title=title,
                summary=summary,
                references=references,
            )
        )
    if require_epsilon_delta:
        if language == "ja" and not overview.startswith("$\\varepsilon>0$ を任意に取ります。"):
            raise ValueError(
                "x-squared continuity explanation must start with the mathematical proof"
            )
        if not _has_x_squared_epsilon_delta(
            "\n".join([overview, *(section.summary for section in sections), conclusion])
        ):
            raise ValueError(
                "x-squared continuity explanation must include epsilon-delta reasoning"
            )
    return overview, tuple(sections), conclusion


def _parse_clarification(
    payload: dict[str, Any],
    *,
    lean_code: str,
    section_id: str,
    selected: ExplanationSection,
    language: str = "ja",
) -> tuple[str, tuple[str, ...], tuple[LeanLineReference, ...]]:
    if _required_text(payload, "section_id") != section_id:
        raise ValueError("clarification section_id does not match the requested section")
    _require_output_language(language)
    answer = _required_bounded_language_text(
        payload,
        "answer",
        minimum=40,
        maximum=4000,
    )
    _reject_lean_source_terms(answer, "clarification answer")
    raw_points = _required_list(payload, "key_points")
    if not 2 <= len(raw_points) <= 10:
        raise ValueError("key_points must contain between 2 and 10 items")
    key_points = tuple(
        _bounded_text_value(point, "key_points item", minimum=1, maximum=500)
        for point in raw_points
    )
    for point in key_points:
        _reject_lean_source_terms(point, "clarification key point")
    normalized_answer = _normalize_unicode_whitespace(answer)
    normalized_summary = _normalize_unicode_whitespace(selected.summary)
    if (
        normalized_answer == normalized_summary
        or len(normalized_answer) <= len(normalized_summary)
    ):
        raise ValueError(
            "clarification answer must differ from and be longer than the selected summary"
        )
    references = _parse_references(payload, lean_code)
    if not any(
        _references_overlap(reference, selected_reference)
        for reference in references
        for selected_reference in selected.references
    ):
        raise ValueError("clarification must reference the selected Lean section")
    return answer, key_points, references


def _parse_references(
    payload: dict[str, Any],
    lean_code: str,
) -> tuple[LeanLineReference, ...]:
    raw_references = _required_list(payload, "references")
    if not 1 <= len(raw_references) <= 20:
        raise ValueError("references must contain between 1 and 20 Lean line ranges")
    references = tuple(
        _validated_reference(reference, lean_code) for reference in raw_references
    )
    return references


def _validated_reference(payload: Any, lean_code: str) -> LeanLineReference:
    if not isinstance(payload, dict):
        raise TypeError("each Lean reference must be an object")
    reference = _reference_from_mapping(payload)
    lines = lean_code.splitlines()
    if reference.start_line < 1 or reference.end_line < reference.start_line:
        raise ValueError("Lean reference line range is invalid")
    if reference.end_line > len(lines):
        raise ValueError("Lean reference points outside the verified Lean code")
    actual_excerpt = "\n".join(lines[reference.start_line - 1 : reference.end_line])
    if reference.excerpt != actual_excerpt:
        raise ValueError("Lean reference excerpt does not exactly match the verified code")
    return LeanLineReference(
        start_line=reference.start_line,
        end_line=reference.end_line,
        excerpt=actual_excerpt,
    )


def _reference_from_mapping(payload: dict[str, Any]) -> LeanLineReference:
    start_line = payload.get("start_line")
    end_line = payload.get("end_line")
    if type(start_line) is not int or type(end_line) is not int:
        raise TypeError("Lean reference line numbers must be integers")
    return LeanLineReference(
        start_line=start_line,
        end_line=end_line,
        excerpt=_required_exact_text(payload, "excerpt"),
    )


def _references_overlap(left: LeanLineReference, right: LeanLineReference) -> bool:
    return left.start_line <= right.end_line and right.start_line <= left.end_line


def _parse_json_object(raw_output: str) -> dict[str, Any]:
    stripped = raw_output.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        last_fence = stripped.rfind("```")
        if first_newline >= 0 and last_fence > first_newline:
            stripped = stripped[first_newline + 1 : last_fence].strip()
    if not stripped.startswith("{"):
        raise json.JSONDecodeError("response does not contain a JSON object", stripped, 0)
    # JSON permits `\n` and `\t`, while TeX commands such as `\neq` and `\text`
    # begin with the same letters. Repair a single TeX command slash before decoding;
    # correctly escaped JSON backslashes and one-letter JSON escapes remain untouched.
    stripped = _BARE_LATEX_JSON_BACKSLASH_PATTERN.sub(r"\\\\", stripped)
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError as exc:
        # Responses routinely contain LaTeX such as ``\varepsilon`` inside JSON strings.
        # A model may emit its single backslash without JSON-escaping it; repair only that
        # otherwise-invalid escape class, then apply the same strict JSON and schema checks.
        if "Invalid \\escape" not in exc.msg:
            raise
        repaired = re.sub(
            r'(?<!\\)\\(?!(?:["\\\\/bfnrt]|u[0-9A-Fa-f]{4}))', r"\\\\", stripped
        )
        value, end = decoder.raw_decode(repaired)
        stripped = repaired
    if stripped[end:].strip():
        raise json.JSONDecodeError("response contains text after the JSON object", stripped, end)
    if not isinstance(value, dict):
        raise TypeError("response JSON must be an object")
    return value


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not _trim_unicode_whitespace(value):
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_exact_text(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not _trim_unicode_whitespace(value):
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array")
    return value


def _required_bounded_language_text(
    payload: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    value = payload[key]
    text = _bounded_text_value(value, key, minimum=minimum, maximum=maximum)
    return text


def _require_output_language(language: str) -> None:
    if language not in {"en", "ja", "zh-Hans", "zh-Hant"}:
        raise ValueError("output language is unsupported")


def _bounded_text_value(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    length = len(_trim_unicode_whitespace(value))
    if not minimum <= length <= maximum:
        raise ValueError(
            f"{label} must contain between {minimum} and {maximum} code points"
        )
    return value


def _reject_lean_source_terms(text: str, label: str) -> None:
    """Keep learner prose independent from the Lean implementation vocabulary."""
    if "`" in text:
        raise ValueError(f"{label} must not quote Lean source code")
    source_term = _LEAN_SOURCE_TERM_PATTERN.search(text)
    if source_term is not None:
        raise ValueError(
            f"{label} must not mention Lean tactic or command: {source_term.group(0)}"
        )
    qualified_identifier = _LEAN_QUALIFIED_IDENTIFIER_PATTERN.search(text)
    if qualified_identifier is not None:
        raise ValueError(
            f"{label} must not mention Lean identifier: {qualified_identifier.group(0)}"
        )


def _is_japanese_code_point(character: str) -> bool:
    code_point = ord(character)
    return (
        0x3040 <= code_point <= 0x309F
        or 0x30A0 <= code_point <= 0x30FF
        or 0x4E00 <= code_point <= 0x9FFF
    )


def _is_unicode_whitespace(character: str) -> bool:
    code_point = ord(character)
    return (
        0x0009 <= code_point <= 0x000D
        or code_point == 0x0020
        or code_point == 0x0085
        or code_point == 0x00A0
        or code_point == 0x1680
        or 0x2000 <= code_point <= 0x200A
        or code_point in {0x2028, 0x2029, 0x202F, 0x205F, 0x3000}
    )


def _trim_unicode_whitespace(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_unicode_whitespace(value[start]):
        start += 1
    while end > start and _is_unicode_whitespace(value[end - 1]):
        end -= 1
    return value[start:end]


def _normalize_unicode_whitespace(value: str) -> str:
    normalized: list[str] = []
    in_whitespace = False
    for character in value:
        if _is_unicode_whitespace(character):
            if normalized and not in_whitespace:
                normalized.append(" ")
            in_whitespace = True
            continue
        normalized.append(character)
        in_whitespace = False
    if normalized and normalized[-1] == " ":
        normalized.pop()
    return "".join(normalized)


def _explanation_prompt(
    *,
    theorem_statement: str,
    lean_code: str,
    language: str,
    require_epsilon_delta: bool = False,
) -> str:
    x_squared_instruction = ""
    if require_epsilon_delta:
        opening_instruction = (
            "The overview must begin exactly with:\n"
            "$\\varepsilon>0$ を任意に取ります。"
            if language == "ja"
            else (
                "Begin directly with an epsilon-delta proof in the requested output language, "
                "starting from an arbitrary $\\varepsilon>0$."
            )
        )
        x_squared_instruction = f"""
This learner asked why x² is continuous. Derive an epsilon-delta explanation from the verified
theorem: give an explicit positive delta choice and use the factorization/bound of |x²-a²|.
Write the mathematical proof itself from the first sentence. {opening_instruction}
Then proceed in textbook order: fix the real point, choose delta explicitly, assume the
delta-neighborhood condition, derive the factorization and epsilon bound, and conclude continuity.
Do not begin with a summary. Do not create visible section titles, a proof-plan preview, or a
conclusion preview. Never use source-commentary headings such as ライブラリの利用, 示したい内容,
or 連続性判定を使う. Use direct proof prose such as “Fix”, “Let”, “Set”, “Assume”, and
“Therefore”, rather than conversational framing such as “We will show”, “Let us”, or
“In this step”. Do not say that the learner requested epsilon-delta, and do not expose Lean
syntax."""
    return f"""Write a mathematical proof for a learner, grounded in a verified Lean artifact.
The theorem statement and verified Lean code below are the only sources of truth.
Provide user-facing rationale as mathematical exposition, not hidden chain-of-thought and not
commentary on the Lean source. Begin with the proof itself. Do not first summarize the proof,
describe imports or libraries, preview the conclusion, or explain what individual source lines,
commands, or tactics do.
Across overview, sections, and conclusion, write one continuous proof in logical textbook order.
The visible proof has no headings, bullets, numbered steps, or conversational step labels. Each
section is only an internal anchor for learner questions; its `title` is never shown. The summary
must continue the proof in ordinary mathematical prose, not introduce a titled step. Prefer direct
mathematical constructions (“Fix …”, “Let …”, “Set …”, “Assume …”, “Thus …”) over conversational
or pedagogical framing (“We will show …”, “Let us …”, “In this step …”, or “The idea is …”).
{x_squared_instruction}

Output language: {language}
User theorem statement: {theorem_statement}

Return exactly one JSON object with this schema:
{{
  "overview": "opening sentences of the mathematical proof",
  "sections": [
    {{
      "id": "stable-kebab-case-id",
      "title": "internal short label; it is not learner-facing",
      "summary": "the next part of the mathematical proof",
      "references": [
        {{"start_line": 1, "end_line": 2, "excerpt": "exact text from those lines"}}
      ]
    }}
  ],
  "conclusion": "the final mathematical conclusion"
}}

Write all learner-facing prose in the requested output language. Overview and conclusion must be
1-600 code points. Return 1-20 sections; each internal title is 1-80 code points, each summary
is 1-800,
and every section has 1-20 references. Each excerpt must match the
cited code exactly. Do not claim anything unsupported by the cited lines. Learner-facing
prose must not quote Lean source, tactic or command names, or Lean identifiers. Explain the
underlying mathematical step in the requested output language; Lean source belongs only in
`references`.
Wrap every mathematical expression in `$...$` using KaTeX-compatible LaTeX. For
example, write `$|x^2-a^2|=|x-a||x+a|$`, `$\\varepsilon$`, and `$\\delta$`;
do not leave mathematical expressions as un-delimited plain text.

Verified Lean code:
```lean
{lean_code}
```

Canonical Lean line table (JSON; each `text` value preserves leading spaces):
{_line_reference_table(lean_code)}

For a reference from `start_line` through `end_line`, set `excerpt` to the exact `text`
values for those lines joined with a single newline. Do not trim or normalize spaces."""


def _clarification_prompt(
    *,
    theorem_statement: str,
    lean_code: str,
    explanation: ProofExplanation,
    selected: ExplanationSection,
    question: str,
    language: str,
    selected_text: str = "",
    after_clarification_id: str | None = None,
) -> str:
    public_explanation = {
        "overview": explanation.overview,
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "summary": section.summary,
                "references": [asdict(reference) for reference in section.references],
            }
            for section in explanation.sections
        ],
        "conclusion": explanation.conclusion,
    }
    return f"""Clarify one part of an existing Lean proof explanation for a learner.
The theorem statement and verified Lean code below are the only sources of truth.
Provide user-facing rationale, not hidden chain-of-thought. Focus on the selected
section and the learner's question. Unpack notation, hypotheses, and the mathematical implication
in more detail.

Output language: {language}
User theorem statement: {theorem_statement}
Selected section id: {selected.id}
Learner question: {question}
Selected learner text: {selected_text}
Preceding clarification id: {after_clarification_id or "none"}

Existing explanation:
{json.dumps(public_explanation, ensure_ascii=False)}

Return exactly one JSON object with this schema:
{{
  "section_id": "{selected.id}",
  "answer": "detailed answer",
  "key_points": ["point one", "point two"],
  "references": [
    {{"start_line": 1, "end_line": 2, "excerpt": "exact text from those lines"}}
  ]
}}

Write an answer in the requested output language of 40-4000 code points that is longer than
and does not repeat the selected summary. Return 2-10 nonblank key points of at most 500
code points and 1-20 references. At least one reference must overlap the selected section. Every
excerpt must exactly match the cited 1-based line range. The answer and key points must
not quote Lean source, tactic or command names, or Lean identifiers. Explain the
underlying mathematical step in the requested output language; Lean source belongs only in
`references`.
Wrap every mathematical expression in `$...$` using KaTeX-compatible LaTeX. Do not
leave formulas, variables, epsilon, or delta as un-delimited plain text.

Verified Lean code:
```lean
{lean_code}
```

Canonical Lean line table (JSON; each `text` value preserves leading spaces):
{_line_reference_table(lean_code)}

Copy every `excerpt` exactly from the referenced `text` values, preserving leading
spaces and joining multi-line ranges with a single newline."""


def _output_review_prompt(
    *,
    theorem_statement: str,
    lean_code: str,
    explanation: ProofExplanation,
    language: str,
    clarification: ProofClarification | None = None,
) -> str:
    _require_output_language(language)
    reviewed_output: dict[str, Any] = {
        "explanation": {
            "overview": explanation.overview,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "summary": section.summary,
                    "references": [asdict(reference) for reference in section.references],
                }
                for section in explanation.sections
            ],
            "conclusion": explanation.conclusion,
        }
    }
    if clarification is not None:
        reviewed_output["clarification"] = {
            "section_id": clarification.section_id,
            "question": clarification.question,
            "answer": clarification.answer,
            "key_points": list(clarification.key_points),
            "references": [asdict(reference) for reference in clarification.references],
        }
    output_kind = "clarification" if clarification is not None else "explanation"
    return f"""You are an independent review session for learner-facing mathematical output.
You did not generate the candidate. Do not continue or repair it. Review only the supplied
candidate against the verified Lean source and the learner theorem statement. A clarification
must also be grounded in the supplied explanation. Approve only if every mathematical claim in
the candidate is supported by those sources and all learner-facing prose is written in `{language}`.
Mathematical notation, formula variables, and exact Lean excerpts are language-neutral: do not
reject a candidate merely because those non-prose spans are not words in `{language}`.
For a verified theorem, standard mathematical derivations of its stated claim are grounded even
when the Lean proof uses automation. Do not require the learner-facing explanation to mention a
tactic, source line, or other Lean implementation detail; reject only a genuine mathematical or
grounding contradiction in the candidate itself.
Do not reveal hidden chain-of-thought.

The proof is already verified. Your decision controls only whether this {output_kind} can be
published; it must not alter the proof's verified state.

Return exactly one JSON object and no surrounding text:
{{"approved": true, "rationale": "a concise review reason"}}
or
{{"approved": false, "rationale": "a concise review reason"}}

User theorem statement:
{theorem_statement}

Verified Lean source:
```lean
{lean_code}
```

Candidate {output_kind} JSON:
{json.dumps(reviewed_output, ensure_ascii=False, sort_keys=True)}"""


def _review_approved(payload: dict[str, Any]) -> bool:
    if set(payload) != {"approved"} or type(payload["approved"]) is not bool:
        raise ValueError("review response must contain exactly one boolean approved field")
    return payload["approved"]


def _output_review_decision(payload: dict[str, Any]) -> tuple[bool, str]:
    if set(payload) != {"approved", "rationale"} or type(payload.get("approved")) is not bool:
        raise ValueError("output review response must contain approved and rationale fields")
    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 8_000:
        raise ValueError("output review rationale must be a bounded nonblank string")
    return payload["approved"], rationale


def _proof_semantic_review_decision(
    payload: dict[str, Any],
) -> tuple[Literal["approved", "rejected"], str]:
    if set(payload) != {"approved", "rationale"}:
        raise ValueError(
            "proof review response must contain exactly approved and rationale fields"
        )
    approved = payload["approved"]
    rationale = payload["rationale"]
    if type(approved) is not bool:
        raise ValueError("proof review approved field must be boolean")
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or len(rationale) > 8_000
    ):
        raise ValueError("proof review rationale must be nonblank and at most 8000 characters")
    return ("approved" if approved else "rejected"), rationale


def _proof_semantic_review_prompt(
    *,
    theorem_statement: str,
    formal_statement: str | None,
    target_declaration: LeanTargetDeclaration,
    lean_code: str,
) -> str:
    formal = formal_statement or "(No separate formal statement was supplied.)"
    return f"""You are an independent proof-review session. You did not generate this Lean
candidate. The deterministic parser extracted exactly this one target declaration; reject if it
does not correspond to the displayed Lean source. Decide whether that exact proposition corresponds
to the learner's request and whether the candidate's proof logically establishes it. Lean
compilation has already succeeded, but that alone is not approval. Do not repair
or continue the proof. Return exactly one JSON object and no surrounding text:
{{\"approved\": true, \"rationale\": \"concise review rationale\"}}
or
{{\"approved\": false, \"rationale\": \"concise review rationale\"}}
The rationale must be nonblank, under 8,000 characters, and must not disclose hidden
chain-of-thought.

Learner request:
{theorem_statement}

Learner-provided formal statement:
{formal}

Exact extracted target declaration:
{json.dumps(target_declaration.as_dict(), ensure_ascii=False, sort_keys=True)}

Lean candidate source:
```lean
{lean_code}
```"""


def _is_x_squared_continuity(theorem_statement: str) -> bool:
    compact = re.sub(r"\s+", "", theorem_statement).lower()
    return "連続" in compact and ("x²" in compact or "x^2" in compact)


def _has_x_squared_epsilon_delta(text: str) -> bool:
    compact = (
        re.sub(r"\s+", "", text)
        .replace("\\varepsilon", "ε")
        .replace("\\epsilon", "ε")
        .replace("\\delta", "δ")
        .replace("\\lvert", "|")
        .replace("\\rvert", "|")
        .replace("\\cdot", "*")
        .replace("\\times", "*")
        .replace("≤", "<=")
        .replace("\\{", "(")
        .replace("\\}", ")")
        .replace("\\min", "min")
        .replace("²", "^2")
    )
    compact = re.sub(r"\\(?:left|right|quad|qquad|[,;:!])", "", compact)
    compact = re.sub(r"\\leq?(?![A-Za-z])", "<=", compact)
    compact = re.sub(r"\\lt(?![A-Za-z])", "<", compact)
    compact = re.sub(r"\\frac\{ε\}\{([^{}]*)\}", r"ε/(\1)", compact)
    compact = compact.replace("{", "").replace("}", "")
    construction = re.search(r"δ(?::=|=)(?P<choice>[^$。、；;]{1,200})", compact)
    has_delta_construction = (
        construction is not None and "ε" in construction.group("choice")
    )
    has_sufficient_delta_choice = (
        construction is not None
        and _is_sufficient_x_squared_delta_choice(construction.group("choice"))
    )
    has_positive_delta = (
        "δ>0" in compact
        or "0<δ" in compact
        or (
            construction is not None
            and re.search(r">0", construction.group("choice")) is not None
        )
    )
    factorization = re.search(
        (
            r"\|x\^2-a\^2\|="
            r"(?:\|x-a\|\*?\|x\+a\||\|x\+a\|\*?\|x-a\|)"
        ),
        compact,
    )
    neighborhood_position = compact.find("|x-a|<δ")
    applies_delta_neighborhood = (
        factorization is not None
        and 0 <= neighborhood_position < factorization.start()
    )
    applies_epsilon_bound = (
        factorization is not None
        and re.search(
            r"[^$。、；;]{0,240}<=?ε",
            compact[factorization.end() :],
        )
        is not None
    )
    return (
        has_delta_construction
        and has_sufficient_delta_choice
        and has_positive_delta
        and applies_delta_neighborhood
        and applies_epsilon_bound
        and re.search(
            r"(?:連続|continuous|continuity)",
            compact[factorization.end() if factorization is not None else 0 :],
            re.IGNORECASE,
        )
        is not None
    )


def _is_sufficient_x_squared_delta_choice(choice: str) -> bool:
    denominator = (
        r"(?:"
        r"(?P<a_coefficient_first>\d+)\*?\|a\|\+(?P<constant_last>\d+)"
        r"|"
        r"(?P<constant_first>\d+)\+(?P<a_coefficient_last>\d+)\*?\|a\|"
        r"|"
        r"(?P<outer_factor>\d+)\*?\(\|a\|\+(?P<inner_constant>\d+)\)"
        r")"
    )
    direct = re.fullmatch(
        rf"min\(1,ε/\({denominator}\)\)(?:>0)?",
        choice,
    )
    fraction = re.fullmatch(
        rf"min\(1,\\fracε{denominator}\)(?:>0)?",
        choice,
    )
    matched = direct if direct is not None else fraction
    if matched is None:
        return False
    outer_factor = matched.group("outer_factor")
    if outer_factor is not None:
        factor = int(outer_factor)
        return factor >= 2 and factor * int(matched.group("inner_constant")) >= 1
    a_coefficient = matched.group("a_coefficient_first") or matched.group(
        "a_coefficient_last"
    )
    constant = matched.group("constant_last") or matched.group("constant_first")
    return int(a_coefficient) >= 2 and int(constant) >= 1


def _line_reference_table(lean_code: str) -> str:
    return json.dumps(
        [
            {"line": line_number, "text": line}
            for line_number, line in enumerate(lean_code.splitlines(), start=1)
        ],
        ensure_ascii=False,
        indent=2,
    )


def _validate_deadline_options(
    deadline: float | None,
    timeout_seconds: float | None,
) -> None:
    if deadline is None and timeout_seconds is None:
        return
    if deadline is None or timeout_seconds is None:
        raise ValueError("deadline and timeout_seconds must be provided together")
    if not math.isfinite(deadline):
        raise ValueError("deadline must be finite")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 300
    ):
        raise ValueError("timeout_seconds must be between 0 and 300")


def _remaining_transport_timeout(
    *,
    deadline: float | None,
    timeout_seconds: float | None,
    monotonic: Callable[[], float],
) -> float | None:
    if deadline is None or timeout_seconds is None:
        return None
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ExplanationDeadlineExceeded("explanation generation deadline exceeded")
    return min(float(timeout_seconds), remaining)


def _raise_if_deadline_reached(
    deadline: float | None,
    monotonic: Callable[[], float],
) -> None:
    if deadline is not None and monotonic() >= deadline:
        raise ExplanationDeadlineExceeded("explanation generation deadline exceeded")


def _elapsed_ms(started_at: float, monotonic: Callable[[], float]) -> int:
    return max(0, int((monotonic() - started_at) * 1000))
