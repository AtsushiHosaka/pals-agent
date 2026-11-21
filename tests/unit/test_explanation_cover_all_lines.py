"""PALS_EXPLANATION_COVER_ALL_LINES_ENABLED (pals#232): default off, prompt only.

With the flag off the explanation prompt must be byte-identical to the prompt before the flag
existed; the golden digests below were computed from main at 2574cd7 (before this change).
"""

import hashlib

import pytest

from pals_agent.explanations import (
    EXPLANATION_COVER_ALL_LINES_ENV,
    _explanation_prompt,
)

HEADER_LEAN = (
    "import Mathlib\n\ntheorem t (a b : ℕ) (h : a = b) : b = a := by\n"
    "  have hab :\n      a = b := by\n    exact h\n  exact hab.symm"
)
PLAIN_LEAN = "theorem t : True := by\n  trivial"
GOLDEN = {
    "header": "dda4a56e465e93827f2560e0dd57da3a66bb6dda61f76fa644be125848654eef",
    "plain": "14eb3d931793f229036386299b4dffa0d8652af00e52552f2bda7206a1b655da",
}
MARKER = "Coverage of the proof body"


def _prompt(lean: str) -> str:
    return _explanation_prompt(theorem_statement="s", lean_code=lean, language="ja")


@pytest.mark.parametrize("value", [None, "false", "", "0", "TRUE", "yes", "on"])
def test_prompt_is_byte_identical_to_before_the_flag_unless_exactly_true(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(EXPLANATION_COVER_ALL_LINES_ENV, raising=False)
    else:
        monkeypatch.setenv(EXPLANATION_COVER_ALL_LINES_ENV, value)
    for name, lean in (("header", HEADER_LEAN), ("plain", PLAIN_LEAN)):
        prompt = _prompt(lean)
        assert MARKER not in prompt
        assert hashlib.sha256(prompt.encode()).hexdigest() == GOLDEN[name]


def test_enabling_the_flag_only_appends_the_coverage_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EXPLANATION_COVER_ALL_LINES_ENV, raising=False)
    before = {
        name: _prompt(lean) for name, lean in (("header", HEADER_LEAN), ("plain", PLAIN_LEAN))
    }
    monkeypatch.setenv(EXPLANATION_COVER_ALL_LINES_ENV, "true")
    for name, lean in (("header", HEADER_LEAN), ("plain", PLAIN_LEAN)):
        after = _prompt(lean)
        assert after.startswith(before[name])
        assert MARKER in after[len(before[name]) :]
        assert "Never invent an explanation for a line" in after
