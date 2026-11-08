"""A fixed explanation for the exact x² template proof: text, grounding and worker wiring.

The text is only a *candidate*. These tests pin that it is the proof the template really contains,
that it is rejected for anything that is not the template, and that the worker still reviews it
and writes it with that review's evidence (never without one).
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.explanations import ExplanationGenerationError, ProofOutputReviewError
from pals_agent.lean_templates import XSquaredBindings, render_x_squared_epsilon_delta
from pals_agent.settings import AgentSettings
from pals_agent.template_explanation import (
    FIXED_EXPLANATION_MODEL,
    SUPPORTED_LANGUAGES,
    bindings_of_template_proof,
    fixed_explanation_for,
)
from pals_agent.worker import SqsProofWorker
from tests.unit.test_worker_claim_spec import (
    RecordingExplainer,
    RecordingOutputReviewer,
    _envelope,
)

STATEMENT = "x² は連続であることを証明せよ"
CLAIM = "55555555-5555-4555-8555-555555555555"
JOB = "job-fixed"
NAMED = [
    XSquaredBindings(),
    XSquaredBindings(variable="t", moving="s"),
    XSquaredBindings(variable="u", point="c", moving="v", theorem="u2_continuous"),
    XSquaredBindings(point="p"),
]


def _lines(code: str) -> list[str]:
    return code.splitlines()


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
@pytest.mark.parametrize("bindings", NAMED)
def test_every_language_yields_a_grounded_explanation_for_every_naming(
    language: str, bindings: XSquaredBindings
) -> None:
    code = render_x_squared_epsilon_delta(bindings)
    explanation = fixed_explanation_for(code, language)

    assert explanation is not None
    assert explanation.model == FIXED_EXPLANATION_MODEL
    assert explanation.prompt == "" and explanation.raw_model_output == ""
    lines = _lines(code)
    for section in explanation.sections:
        assert section.references
        for reference in section.references:
            assert reference.excerpt == "\n".join(
                lines[reference.start_line - 1 : reference.end_line]
            )
    visible = " ".join(
        [explanation.overview, *(s.summary for s in explanation.sections), explanation.conclusion]
    )
    # The names of the proof appear in the prose and no placeholder survives.
    assert "@" not in visible
    assert f"|{bindings.moving}-{bindings.point}|" in visible
    assert f"{bindings.variable}^2" in visible


def test_the_text_is_the_proof_the_template_contains() -> None:
    code = render_x_squared_epsilon_delta(XSquaredBindings())
    lines = _lines(code)
    # The sections cite the lines that carry the step they describe.
    assert "min 1 (ε / (2 * |a| + 1))" in lines[7]
    assert lines[13].strip().startswith("· intro x hy")
    assert "hfactor" in lines[25]
    assert lines[51].strip().startswith("simpa")

    explanation = fixed_explanation_for(code, "en")
    assert explanation is not None
    delta, near, estimate = (section.summary for section in explanation.sections)
    # delta = min(1, ε / (2|a|+1)), as in the source
    assert r"\delta=\min\!\left(1,\ \dfrac{\varepsilon}{2|a|+1}\right)" in delta
    # |x-a| < 1, |x| ≤ |a|+1, |x+a| ≤ 2|a|+1: hy1, hyabs, hyplus
    assert r"|x-a|<1" in near and r"\le|a|+1" in near and r"\le 2|a|+1" in near
    # factorisation, bound with 2|a|+1, cancellation (ε / C) * C = ε
    assert r"(x-a)(x+a)" in estimate
    assert r"|x-a|\,(2|a|+1)" in estimate
    assert r"\dfrac{\varepsilon}{2|a|+1}\,(2|a|+1)=\varepsilon" in estimate
    # the three sections cover the template without a gap: 8-13, 14-25, 26-52
    spans = [
        (s.references[0].start_line, s.references[0].end_line) for s in explanation.sections
    ]
    assert spans == [(8, 13), (14, 25), (26, 52)]


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_every_mathematical_expression_is_in_delimiters(language: str) -> None:
    explanation = fixed_explanation_for(render_x_squared_epsilon_delta(), language)
    assert explanation is not None
    for text in [explanation.overview, *(s.summary for s in explanation.sections),
                 explanation.conclusion]:
        outside = re.sub(r"\$[^$]*\$", " ", text)
        assert not re.search(r"[|\\^=<≤]|\d", outside), outside


@pytest.mark.parametrize(
    "code",
    [
        "theorem sample : True := by\n  trivial",
        render_x_squared_epsilon_delta().replace("min 1 (", "min 2 ("),
        render_x_squared_epsilon_delta().replace("ring_nf", "ring"),
        render_x_squared_epsilon_delta() + "\n#eval 1\n",
        render_x_squared_epsilon_delta().replace("x ^ 2", "x ^ 3", 1),
        render_x_squared_epsilon_delta().replace("Continuous", "ContinuousOn"),
        "",
    ],
)
def test_only_the_exact_template_gets_the_fixed_text(code: str) -> None:
    assert bindings_of_template_proof(code) is None
    for language in SUPPORTED_LANGUAGES:
        assert fixed_explanation_for(code, language) is None


def test_an_unknown_language_gets_nothing() -> None:
    assert fixed_explanation_for(render_x_squared_epsilon_delta(), "fr") is None


def test_trailing_newline_does_not_matter_but_bindings_round_trip() -> None:
    for bindings in NAMED:
        code = render_x_squared_epsilon_delta(bindings)
        assert bindings_of_template_proof(code + "\n") == bindings


# --- worker wiring ---------------------------------------------------------------------------


class _Api:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def upsert_proof_explanation(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        if kwargs["state"] == "generating":
            return _envelope("acquired", 3_000_000, resource_id=kwargs["proof_job_id"])
        return _envelope("terminal", None, resource_id=kwargs["proof_job_id"])


class _RejectingOnce(RecordingOutputReviewer):
    def review_explanation(self, **kwargs: Any) -> Any:
        if not self.explanation_calls:
            self.explanation_calls.append(kwargs)
            raise ProofOutputReviewError("rejected", category="rejected", rationale="no")
        return super().review_explanation(**kwargs)


def _worker(
    *, enabled: bool | None, explainer: Any, reviewer: Any, api: _Api
) -> SqsProofWorker:
    values: dict[str, Any] = {"explanation_model_timeout_seconds": 17}
    if enabled is not None:
        values["template_fixed_explanation_enabled"] = enabled
    return SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(**values)),
        api_client=cast(Any, api),
        pipeline=None,
        explainer=cast(Any, explainer),
        output_reviewer=cast(Any, reviewer),
        proof_reviewer=cast(Any, object()),
    )


def _ensure(worker: SqsProofWorker, code: str, language: str = "en") -> bool:
    return worker._ensure_summary_explanation(
        proof_job_id=JOB,
        theorem_statement=STATEMENT,
        lean_code=code,
        claim_id=CLAIM,
        extend_visibility=lambda seconds: None,
        language=language,
    )


@pytest.mark.parametrize("enabled", [None, False])
def test_flag_off_or_absent_keeps_the_model_explainer(enabled: bool | None) -> None:
    api, explainer, reviewer = _Api(), RecordingExplainer(), RecordingOutputReviewer()
    code = render_x_squared_epsilon_delta()

    _ensure(_worker(enabled=enabled, explainer=explainer, reviewer=reviewer, api=api), code)

    assert len(explainer.explain_calls) == 1


def test_flag_on_uses_the_fixed_text_but_still_reviews_and_writes_with_the_review() -> None:
    api, explainer, reviewer = _Api(), RecordingExplainer(), RecordingOutputReviewer()
    code = render_x_squared_epsilon_delta(XSquaredBindings(variable="t", moving="s"))

    assert _ensure(
        _worker(enabled=True, explainer=explainer, reviewer=reviewer, api=api), code, "ja"
    )

    assert explainer.explain_calls == []
    assert len(reviewer.explanation_calls) == 1
    reviewed = reviewer.explanation_calls[0]
    assert reviewed["lean_code"] == code and reviewed["language"] == "ja"
    assert reviewed["explanation"].model == FIXED_EXPLANATION_MODEL
    completed = api.updates[-1]
    assert completed["state"] == "completed"
    assert completed["content"]["model"] == FIXED_EXPLANATION_MODEL
    assert completed["review_evidence"] is not None
    # The review's own identity is the evidence; the fixed text never supplies one.
    assert completed["review_evidence"]["reviewer"]["model"] == "review-model"


def test_flag_on_leaves_every_other_proof_to_the_model() -> None:
    api, explainer, reviewer = _Api(), RecordingExplainer(), RecordingOutputReviewer()
    code = "theorem sample : True := by\n  trivial"

    _ensure(_worker(enabled=True, explainer=explainer, reviewer=reviewer, api=api), code)

    assert len(explainer.explain_calls) == 1
    assert reviewer.explanation_calls[0]["explanation"].model == "explain-model"


def test_a_rejected_fixed_text_falls_back_to_one_model_correction() -> None:
    api, explainer, reviewer = _Api(), RecordingExplainer(), _RejectingOnce()
    code = render_x_squared_epsilon_delta()

    _ensure(_worker(enabled=True, explainer=explainer, reviewer=reviewer, api=api), code)

    assert len(explainer.explain_calls) == 1
    assert explainer.explain_calls[0]["review_feedback"]["rationale"] == "no"
    assert api.updates[-1]["state"] == "completed"


def test_a_model_failure_after_rejection_is_still_a_failure() -> None:
    api = _Api()
    explainer = RecordingExplainer(error=ExplanationGenerationError("invalid JSON"))
    worker = _worker(enabled=True, explainer=explainer, reviewer=_RejectingOnce(), api=api)

    _ensure(worker, render_x_squared_epsilon_delta())

    assert api.updates[-1]["state"] == "failed"


def test_the_switch_is_off_by_default_and_must_be_turned_on_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = "PALS_TEMPLATE_FIXED_EXPLANATION_ENABLED"
    assert AgentSettings.__dataclass_fields__["template_fixed_explanation_enabled"].default is False
    monkeypatch.delenv(name, raising=False)
    from pals_agent import settings as settings_module

    assert settings_module._strict_bool_env_default(name, False) is False
    monkeypatch.setenv(name, "true")
    assert settings_module._strict_bool_env_default(name, False) is True
