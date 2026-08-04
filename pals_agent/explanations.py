from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

_LEAN_SOURCE_TERM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"aesop|all_goals|apply|assumption|by|calc|cases|constructor|continuity|"
    r"convert|decide|def|exact|example|exists|ext|field_simp|fun|gcongr|"
    r"have|induction|infer_instance|intro|lemma|left|let|linarith|native_decide|"
    r"nlinarith|norm_cast|norm_num|obtain|omega|positivity|rcases|refine|repeat|"
    r"rfl|right|ring|ring_nf|rw|simpa|simp|subst|tauto|theorem|trivial|use|where"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_LEAN_QUALIFIED_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+(?![A-Za-z0-9_])"
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
    require_epsilon_delta: bool = False,
) -> tuple[str, tuple[ExplanationSection, ...], str]:
    overview = _required_bounded_japanese_text(
        payload,
        "overview",
        minimum=1,
        maximum=600,
    )
    conclusion = _required_bounded_japanese_text(
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
        title = _required_bounded_japanese_text(
            raw_section,
            "title",
            minimum=1,
            maximum=80,
        )
        summary = _required_bounded_japanese_text(
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
        if not overview.startswith("$\\varepsilon>0$ を任意に取ります。"):
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
) -> tuple[str, tuple[str, ...], tuple[LeanLineReference, ...]]:
    if _required_text(payload, "section_id") != section_id:
        raise ValueError("clarification section_id does not match the requested section")
    answer = _required_bounded_japanese_text(
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
    value, end = json.JSONDecoder().raw_decode(stripped)
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


def _required_bounded_japanese_text(
    payload: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> str:
    value = payload[key]
    text = _bounded_text_value(value, key, minimum=minimum, maximum=maximum)
    if not any(_is_japanese_code_point(character) for character in _trim_unicode_whitespace(text)):
        raise ValueError(f"{key} must contain Japanese text")
    return text


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
        x_squared_instruction = """
This learner asked why x² is continuous. Derive an epsilon-delta explanation from the verified
theorem: give an explicit positive delta choice and use the factorization/bound of |x²-a²|.
Write the mathematical proof itself from the first sentence. The overview must begin exactly with:
$\\varepsilon>0$ を任意に取ります。
Then proceed in textbook order: fix the real point, choose delta explicitly, assume the
delta-neighborhood condition, derive the factorization and epsilon bound, and conclude continuity.
Use section titles that name mathematical steps. Do not begin with a summary, proof-plan preview,
or conclusion preview. Never use source-commentary headings such as ライブラリの利用, 示したい内容,
or 連続性判定を使う. Do not say that the learner requested epsilon-delta, and do not expose Lean
syntax."""
    return f"""Write a mathematical proof for a learner, grounded in a verified Lean artifact.
The theorem statement and verified Lean code below are the only sources of truth.
Provide user-facing rationale as mathematical exposition, not hidden chain-of-thought and not
commentary on the Lean source. Begin with the proof itself. Do not first summarize the proof,
describe imports or libraries, preview the conclusion, or explain what individual source lines,
commands, or tactics do.
Across overview, sections, and conclusion, write one continuous proof in logical textbook order.
{x_squared_instruction}

Output language: {language}
User theorem statement: {theorem_statement}

Return exactly one JSON object with this schema:
{{
  "overview": "opening sentences of the mathematical proof",
  "sections": [
    {{
      "id": "stable-kebab-case-id",
      "title": "short title naming a mathematical step",
      "summary": "the next part of the mathematical proof",
      "references": [
        {{"start_line": 1, "end_line": 2, "excerpt": "exact text from those lines"}}
      ]
    }}
  ],
  "conclusion": "the final mathematical conclusion"
}}

Write Japanese text. Overview and conclusion must be 1-600 code points. Return 1-20
sections; each title is 1-80 code points, each summary is 1-800, and every section has
1-20 references. Every prose field must contain Japanese. Each excerpt must match the
cited code exactly. Do not claim anything unsupported by the cited lines. Learner-facing
prose must not quote Lean source, tactic or command names, or Lean identifiers. Explain
the underlying mathematical step in Japanese; Lean source belongs only in `references`.
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

Write a Japanese answer of 40-4000 code points that is longer than and does not repeat
the selected summary. Return 2-10 nonblank key points of at most 500 code points and
1-20 references. At least one reference must overlap the selected section. Every
excerpt must exactly match the cited 1-based line range. The answer and key points must
not quote Lean source, tactic or command names, or Lean identifiers. Explain the
underlying mathematical step in Japanese; Lean source belongs only in `references`.
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
        .replace("\\leq", "<=")
        .replace("\\le", "<=")
        .replace("\\lt", "<")
        .replace("≤", "<=")
        .replace("\\{", "(")
        .replace("\\}", ")")
        .replace("\\min", "min")
        .replace("²", "^2")
    )
    compact = re.sub(r"\\(?:left|right|quad|qquad|[,;:!])", "", compact)
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
        and re.match(
            r"(?:<ε|<=?[^$。、；;]{1,200}<ε)",
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
        and "連続" in compact[factorization.end() if factorization is not None else 0 :]
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
