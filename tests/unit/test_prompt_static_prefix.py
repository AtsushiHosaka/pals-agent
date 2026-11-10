"""PALS_PROMPT_STATIC_PREFIX_ENABLED: flag off is byte-identical; flag on gives a static prefix."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pals_agent import generator as g
from pals_agent.models import (
    Diagnostic,
    GeneratedDraft,
    GeneratedSketch,
    GenerationFeedback,
    ProofRequest,
    RelatedDraftContext,
)
from tests.unit.prompt_static_prefix_cases import (
    all_prompts,
)

FLAG = g.PROMPT_STATIC_PREFIX_ENV
GOLDEN = Path(__file__).parents[1] / "fixtures" / "generation_prompts_legacy.json"
# Prompt-caching threshold is 1024 tokens; estimate at 4 characters per token.
MIN_PREFIX_CHARS = 1024 * 4


@pytest.fixture(autouse=True)
def _flag_unset(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lcp(strings: list[str]) -> int:
    first = min(strings, key=len)
    n = 0
    for i, ch in enumerate(first):
        if any(s[i] != ch for s in strings):
            break
        n = i + 1
    return n


@pytest.mark.parametrize("flag_value", [None, "false"])
def test_flag_off_prompts_are_byte_identical_to_origin_main(monkeypatch, flag_value):
    """Hashes were taken from the builders at origin/main 3010c8c, before this change."""
    if flag_value is not None:
        monkeypatch.setenv(FLAG, flag_value)
    golden = json.loads(GOLDEN.read_text())
    current = {key: _sha(text) for key, text in all_prompts("current").items()}
    assert current.keys() == golden.keys()
    assert [k for k in golden if current[k] != golden[k]] == []


def test_flag_rejects_non_boolean(monkeypatch):
    monkeypatch.setenv(FLAG, "yes")
    with pytest.raises(ValueError):
        g.static_prefix_enabled()


def _requests() -> list[ProofRequest]:
    ctx = lambda tag: RelatedDraftContext(f"id-{tag}", (f"note-{tag}",), (f"step-{tag}",))  # noqa: E731
    return [
        ProofRequest(
            id="r1", prompt="PROBLEM-ONE even integers", related_draft_contexts=(ctx("1"),)
        ),
        ProofRequest(
            id="r2", prompt="PROBLEM-TWO irrational root",
            formal_statement="theorem two : True := by sorry",
        ),
        ProofRequest(id="r3", prompt="PROBLEM-THREE x^3 continuous 連続"),  # reliability block
        ProofRequest(id="r4", prompt="PROBLEM-FOUR matrix [[1,2],[3,4]] over a field"),
    ]


def _feedback(tag: str, route: str, unknown: bool) -> GenerationFeedback:
    diag = (
        Diagnostic("error", "Unknown identifier foo; use an available declaration.",
                   code="lean.unknown_identifier", line=3)
        if unknown else Diagnostic("error", f"MSG-{tag}", line=3)
    )
    return GenerationFeedback(
        1, f"FAILED-CODE-{tag}", (diag,), route, f"RATIONALE-{tag}",  # type: ignore[arg-type]
        GeneratedDraft(f"PREV-DRAFT-{tag}", "m", ""),
        GeneratedSketch(f"PREV-SKETCH-{tag}", "m", ""),
    )


def _stage_prompts(request: ProofRequest, tag: str, feedback):
    draft = GeneratedDraft(f"DRAFT-TEXT-{tag}", "m", "")
    sketch = GeneratedSketch(f"SKETCH-CODE-{tag}", "m", "")
    out = {
        "draft": g._draft_prompt_for(request, feedback),
        "sketch": g._sketch_prompt_for(request, draft, feedback),
        "prove": g._prove_prompt_for(request, draft, sketch, feedback),
    }
    if feedback is not None:
        out["route"] = g._repair_route_prompt_for(request, feedback)
        out["repair_instruction"] = g._repair_instruction_prompt_for(request, feedback)
    return out


# Stages whose guidance is long enough to be cached at all (Draft and route are below 1024 tokens
# of static text; their prefix is still checked to be identical).
LONG_STAGES = {"sketch", "prove", "repair_instruction"}


@pytest.mark.parametrize("with_feedback", [False, True])
def test_flag_on_prefix_is_identical_across_requests_and_long_enough(monkeypatch, with_feedback):
    monkeypatch.setenv(FLAG, "true")
    per_stage: dict[str, list[str]] = {}
    for i, request in enumerate(_requests()):
        fb = _feedback(str(i), "prove", unknown=i % 2 == 0) if with_feedback else None
        for stage, prompt in _stage_prompts(request, str(i), fb).items():
            per_stage.setdefault(stage, []).append(prompt)
    for stage, prompts in per_stage.items():
        prefix = _lcp(prompts)
        # Nothing request-specific may sit inside the shared prefix.
        shared = prompts[0][:prefix]
        markers = (
            "PROBLEM-ONE", "PROBLEM-TWO", "PROBLEM-THREE", "PROBLEM-FOUR",
            "DRAFT-TEXT-", "SKETCH-CODE-", "FAILED-CODE-", "RATIONALE-",
        )
        for marker in markers:
            assert marker not in shared, (stage, marker)
        if stage in LONG_STAGES:
            assert prefix >= MIN_PREFIX_CHARS, (stage, prefix)
        else:
            assert prefix > 2000, (stage, prefix)


def test_flag_on_repair_instruction_prefix_is_route_independent(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    request = _requests()[0]
    prompts = [
        g._repair_instruction_prompt_for(request, _feedback("x", route, unknown=False))
        for route in ("draft", "sketch", "prove")
    ]
    assert _lcp(prompts) >= MIN_PREFIX_CHARS


def test_flag_on_variable_fields_appear_exactly_once(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    request = _requests()[1]  # has a formal statement and no retrieved context
    ctx_request = _requests()[0]
    fb = _feedback("q", "prove", unknown=False)
    prompts = _stage_prompts(request, "q", fb)
    ctx_prompts = _stage_prompts(ctx_request, "q", fb)
    for stage, prompt in prompts.items():
        assert prompt.count("PROBLEM-TWO") == 1, stage
        assert prompt.count("theorem two : True := by sorry") == 1, stage
    for stage, prompt in ctx_prompts.items():
        assert prompt.count("PROBLEM-ONE") == 1, stage
    for stage in ("draft", "sketch", "prove"):  # retrieved Drafts still injected, once each
        assert ctx_prompts[stage].count("note-1") == 1, stage
        assert ctx_prompts[stage].count("step-1") == 1, stage
    assert prompts["sketch"].count("DRAFT-TEXT-q") == 1
    assert prompts["prove"].count("DRAFT-TEXT-q") == 1
    assert prompts["prove"].count("SKETCH-CODE-q") == 1
    for stage, prompt in prompts.items():
        assert prompt.count("FAILED-CODE-q") == 1, stage
        assert prompt.count("MSG-q") == 1, stage
    assert prompts["route"].count("PREV-DRAFT-q") == 1
    assert prompts["route"].count("PREV-SKETCH-q") == 1
    for stage in ("draft", "sketch", "prove", "repair_instruction"):
        assert prompts[stage].count("RATIONALE-q") == 1, stage


def test_flag_on_same_guidance_wording_modulo_the_two_omitted_instructions(monkeypatch):
    """Reordering must not change the set of guidance paragraphs except the dead instructions."""
    request = _requests()[2]  # includes the request-specific reliability block
    off = _stage_prompts(request, "z", _feedback("z", "prove", unknown=True))
    monkeypatch.setenv(FLAG, "true")
    on = _stage_prompts(request, "z", _feedback("z", "prove", unknown=True))
    removed = (
        "Verify the owning modules in the active pinned Mathlib when source information is "
        "available; ",
        "If the required module cannot be established, try `import Mathlib` once and recompile "
        "before changing an otherwise valid proof body. ",
        "Check its owning module in the active pinned source when available. ",
    )
    for stage in off:
        normalized = off[stage]
        for phrase in removed:
            normalized = normalized.replace(phrase, "")
        normalized = normalized.replace("do not infer a module path", "Do not infer a module path")
        # Blank lines are layout only; every non-blank line must survive the reorder.
        def lines(text: str) -> list[str]:
            return sorted(line for line in text.splitlines() if line.strip())

        assert lines(normalized) == lines(on[stage]), stage
    for phrase in ("Verify the owning modules", "try `import Mathlib` once and recompile before"):
        assert all(phrase not in text for text in on.values())
