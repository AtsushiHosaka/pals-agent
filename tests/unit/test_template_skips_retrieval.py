"""A wording that selects the x² template does not wait for the Draft retrieval it would not use.

Retrieval is three sequential steps (structure, embed, rerank) whose result only feeds the model
prompts the template replaces. What must not change: the template is the same bytes, it is still
compiled by the API verifier (never marked verified by the worker), and any request the wording
does not select retrieves exactly as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.lean_templates import PROVER_ID, render_x_squared_epsilon_delta
from pals_agent.pipeline import ProofPipeline
from pals_agent.proof_flow_runtime import ProofFlowRetrievalError

PRODUCTION_STATEMENT = (
    "実数上の関数 f: ℝ → ℝ を f(x) = x² と定める。f が ℝ のすべての点で連続であることを証明せよ。"
)
OTHER_STATEMENT = "Prove that the square root of 2 is irrational."


class FailingRetriever:
    """Counts calls and stops the run, so a call is visible without running a model."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def retrieve(self, statement: str) -> Any:
        self.calls.append(statement)
        raise ProofFlowRetrievalError("retrieval_unavailable")


class ForbiddenGenerator:
    model = "forbidden"

    def generate(self, request: Any) -> Any:
        raise AssertionError("the model must not be called for a template request")


def _pipeline(tmp_path: Path, retriever: FailingRetriever, **kwargs: Any) -> ProofPipeline:
    return ProofPipeline(
        generator=ForbiddenGenerator(),  # type: ignore[arg-type]
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
        natural_draft_retriever=retriever,  # type: ignore[arg-type]
        **{"deterministic_templates": True, "template_skips_retrieval": True, **kwargs},
    )


def _run(pipeline: ProofPipeline, statement: str, **kwargs: Any) -> Any:
    statuses: list[tuple[str, dict[str, Any]]] = []
    result = pipeline.run_statement(
        statement=statement,
        proof_job_id="job",
        request_linked=True,
        on_status=lambda state, diagnostics, uri, lean_code, context: statuses.append(
            (state, context)
        ),
        **kwargs,
    )
    return result, statuses


def test_a_template_request_skips_retrieval_and_still_goes_to_the_api_compiler(
    tmp_path: Path,
) -> None:
    retriever = FailingRetriever()

    result, statuses = _run(_pipeline(tmp_path, retriever), PRODUCTION_STATEMENT)

    assert retriever.calls == []
    # The candidate is the template, byte for byte, and only the API may verify it.
    assert result.generated.lean_code == render_x_squared_epsilon_delta()
    assert result.generated.model == PROVER_ID
    assert result.verification_pending is True
    assert result.verification.success is False
    assert result.state != "verified"
    assert any(context.get("deterministic_template") == PROVER_ID for _, context in statuses)
    assert [state for state, _ in statuses if state in {"drafting", "sketching"}] == []


def test_switching_the_skip_off_restores_the_retrieval(tmp_path: Path) -> None:
    skipped, _ = _run(_pipeline(tmp_path / "a", FailingRetriever()), PRODUCTION_STATEMENT)

    assert skipped.generated.lean_code == render_x_squared_epsilon_delta()
    # With the skip off the same statement retrieves first (and this retriever stops the run).
    retriever = FailingRetriever()
    with pytest.raises(ProofFlowRetrievalError):
        _run(
            _pipeline(tmp_path / "b", retriever, template_skips_retrieval=False),
            PRODUCTION_STATEMENT,
        )
    assert retriever.calls == [PRODUCTION_STATEMENT]


def test_a_request_the_wording_does_not_select_still_retrieves(tmp_path: Path) -> None:
    retriever = FailingRetriever()

    with pytest.raises(ProofFlowRetrievalError):
        _run(_pipeline(tmp_path, retriever), OTHER_STATEMENT)

    assert retriever.calls == [OTHER_STATEMENT]


@pytest.mark.parametrize(
    "statement",
    [
        "Prove that x² is continuous on [0, 1].",
        "x²は連続でない理由を教えて",
        "Prove that x² and x³ are continuous.",
    ],
)
def test_near_misses_of_the_wording_still_retrieve(tmp_path: Path, statement: str) -> None:
    retriever = FailingRetriever()

    with pytest.raises(ProofFlowRetrievalError):
        _run(_pipeline(tmp_path, retriever), statement)

    assert retriever.calls == [statement]


def test_a_learner_formal_statement_is_never_replaced_and_still_retrieves(tmp_path: Path) -> None:
    retriever = FailingRetriever()

    with pytest.raises(ProofFlowRetrievalError):
        _run(
            _pipeline(tmp_path, retriever),
            PRODUCTION_STATEMENT,
            formal_statement="theorem t : Continuous (fun x : ℝ => x ^ 2) := by sorry",
        )

    assert retriever.calls == [PRODUCTION_STATEMENT]


def test_without_the_templates_nothing_is_skipped(tmp_path: Path) -> None:
    retriever = FailingRetriever()

    with pytest.raises(ProofFlowRetrievalError):
        _run(
            _pipeline(tmp_path, retriever, deterministic_templates=False),
            PRODUCTION_STATEMENT,
        )

    assert retriever.calls == [PRODUCTION_STATEMENT]


def test_a_missing_retriever_still_fails_closed_before_any_skip(tmp_path: Path) -> None:
    pipeline = ProofPipeline(
        generator=ForbiddenGenerator(),  # type: ignore[arg-type]
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
        deterministic_templates=True,
        template_skips_retrieval=True,
    )

    with pytest.raises(ProofFlowRetrievalError):
        _run(pipeline, PRODUCTION_STATEMENT)
