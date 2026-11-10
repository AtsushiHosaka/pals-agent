"""Unverified waiting-screen previews (pals#329): flag-gated, best-effort, size-capped."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from pals_agent.api_client import PalsApiClient, PalsApiError
from pals_agent.openmath import OpenMathStructuringError
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, _progress_preview
from tests.unit.test_worker import ExplainerThatMustNotRun, RecordingApi

_CLAIM = "11111111-1111-4111-8111-111111111111"
# Needs real reasoning (ε-δ continuity of a cubic), not a trivial expansion.
_PLAN = "δ = min(1, ε/19) とおき、|x³−8| = |x−2||x²+2x+4| ≤ 19|x−2| を使う。"
_SKETCH = "theorem t : Continuous (fun x : ℝ => x ^ 3) := by\n  sorry\n"


class PreviewApi(RecordingApi):
    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(output_language="ja")
        self.previews: list[dict[str, Any]] = []
        self.fail = fail

    def put_progress_preview(self, **kwargs: Any) -> dict[str, Any]:
        self.previews.append(kwargs)
        if self.fail:
            raise PalsApiError("boom", status_code=500)
        return {"accepted": True}


class StagePipeline:
    def run_statement(self, *, on_status: Any, **_kwargs: Any) -> Any:
        on_status("drafting", [], None, None, {})
        on_status("sketching", [], None, None, {"generated_draft": {"text": _PLAN}})
        on_status("proving", [], None, _SKETCH, {"generated_sketch": {"lean_code": _SKETCH}})
        raise OpenMathStructuringError("stop after stages")


def _run(*, enabled: bool, fail: bool = False) -> PreviewApi:
    api = PreviewApi(fail=fail)
    worker = SqsProofWorker(
        settings=cast(AgentSettings, SimpleNamespace(progress_preview_enabled=enabled)),
        api_client=cast(Any, api),
        pipeline=cast(Any, StagePipeline()),
        explainer=ExplainerThatMustNotRun(),
    )
    assert worker.process_proof_job(
        "job-1", claim_id=_CLAIM, extend_visibility=lambda _s: None
    ) is True
    return api


def test_flag_off_sends_no_preview() -> None:
    api = _run(enabled=False)
    assert api.previews == []
    assert [u["state"] for u in api.updates][-1] == "failed"


def test_flag_on_sends_draft_then_sketch_preview() -> None:
    api = _run(enabled=True)
    assert [(p["kind"], p["language"], p["text"], p["truncated"]) for p in api.previews] == [
        ("draft_plan", "ja", _PLAN, False),
        ("sketch_lean", "lean", _SKETCH, False),
    ]
    assert all(p["claim_id"] == _CLAIM and p["proof_job_id"] == "job-1" for p in api.previews)


def test_preview_failure_does_not_change_the_job_outcome() -> None:
    ok, failing = _run(enabled=True), _run(enabled=True, fail=True)
    assert [u["state"] for u in failing.updates] == [u["state"] for u in ok.updates]
    assert len(failing.previews) == 2


def test_caps_truncate_at_a_line_boundary_and_flag_it() -> None:
    long_lean = "\n".join(f"-- line {i:05d}" for i in range(4000))
    preview = _progress_preview(status="proving", raw={}, lean_code=long_lean, language="en")
    assert preview is not None and preview["truncated"] is True
    assert len(preview["text"]) <= 30_000 and long_lean.startswith(preview["text"])
    assert not preview["text"].endswith("\n")
    plan = _progress_preview(
        status="sketching", raw={"generated_draft": {"text": "x" * 7000}}, lean_code=None,
        language="en",
    )
    assert plan is not None and len(plan["text"]) == 6000 and plan["truncated"] is True


@pytest.mark.parametrize(
    ("status", "raw", "lean"),
    [
        ("drafting", {"generated_draft": {"text": _PLAN}}, None),
        ("compiling", {}, _SKETCH),
        ("sketching", {}, None),
        ("sketching", {"generated_draft": {"text": "  "}}, None),
        ("sketching", {"generated_draft": {"text": "<script>alert(1)</script>"}}, None),
        ("proving", {}, None),
    ],
)
def test_nothing_is_sent_without_usable_content(
    status: str, raw: dict[str, Any], lean: Any
) -> None:
    assert _progress_preview(status=status, raw=raw, lean_code=lean, language="en") is None


def test_lean_tactic_operators_are_not_mistaken_for_html() -> None:
    lean = "example (a b : ℕ) (h : a < b) : a ≤ b := by\n  omega <;> simp\n"
    assert _progress_preview(status="proving", raw={}, lean_code=lean, language="en") is not None


def test_client_puts_closed_payload_with_short_timeout() -> None:
    seen: dict[str, Any] = {}

    class Transport:
        def request(self, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return SimpleNamespace(status_code=200, body=b'{"accepted": true}')

    client = PalsApiClient(
        base_url="http://api", worker_secret="s", transport=cast(Any, Transport())
    )
    client.put_progress_preview(
        proof_job_id="job-1", claim_id=_CLAIM, kind="draft_plan", language="ja", text="p",
        truncated=False,
    )
    assert seen["method"] == "PUT"
    assert seen["url"] == "http://api/v1/internal/proof-jobs/job-1/progress-preview"
    assert seen["timeout_seconds"] == 2.0
    assert seen["headers"]["X-PALS-Worker-Secret"] == "s"
