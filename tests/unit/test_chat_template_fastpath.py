"""PALS_CHAT_TEMPLATE_FASTPATH: a plain x² continuity request skips recipe review and the router.

Only the grammar-recognised statement of exactly the continuity of x² takes the shortcut. Every
other request, and every request with history, attachments, a project or a retry, keeps the
established route: the same provider calls as without the flag.
"""

from __future__ import annotations

import contextlib

import pytest

from pals_agent.chat_runtime import ChatRuntime, _template_fastpath_eligible
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_reuse import ProofReuseRuntime
from tests.unit.test_chat_runtime import RecordedResponses, route

X2_STATEMENTS = [
    "State and prove in English that the function f : ℝ → ℝ defined by f(x) = x² "
    "is continuous on ℝ.",
    "実数上の関数 f: ℝ → ℝ を f(x) = x² と定める。f が ℝ 上で連続であることを証明する。"
    "命題と証明はすべて日本語で記述する。",
    "The function f: ℝ → ℝ defined by f(x) = x² is continuous at every real number.",
    "x² が連続であることを説明してください。",
    "f(x)=x² 在实数范围内连续,请证明。请用简体中文回答。",
    "請證明函數 f(x)=x² 在實數上連續。請用繁體中文作答。",
    # Another presentation request inside the original text is split off, not read as the claim.
    "Prove that x² is continuous. Keep the answer short.",
    "x² が連続であることを証明してください。箇条書きで。",
]
OTHER_STATEMENTS = [
    "実数上の関数 f: ℝ → ℝ を f(x)=x² で定める。この関数が不連続であるかどうかを判定せよ。",
    "Explain why x³ is continuous.",
    "Explain why x^2 is not continuous.",
    "Explain why x^2 is differentiable.",
    "Prove that x^2 is continuous on [0, 1].",
    "Solve x+1=2.",
    # Questions keep the router.
    "x² は連続ですか？",
    "Is x² continuous?",
    "x²是连续的吗？",
    "Why is x² continuous?",
    "x² は連続か。",
    # A presentation request outside the closed table is not guessed: the router decides.
    "x² が連続であることを証明してください。回答は短くしてください。",
    "Prove that x² is continuous and also prove that x³ is continuous.",
]


def _request(statement: str, **delta):
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "revision": 1,
        "statement": statement,
        "context_turns": [],
        "output_language": "ja",
        **delta,
    }


def _runtime(outputs, *, fastpath: bool):
    from tests.unit.test_proof_reuse import CatalogBoundary

    provider = RecordedResponses(outputs)
    client = OpenAIResponsesClient(api_key="fixture-no-network", transport=provider)
    runtime = ChatRuntime(
        client, ProofReuseRuntime(client, CatalogBoundary()), template_fastpath=fastpath
    )
    return runtime, provider


@pytest.mark.parametrize("statement", X2_STATEMENTS)
def test_x_squared_request_becomes_a_formal_job_without_any_model_call(statement):
    runtime, provider = _runtime([], fastpath=True)
    result = runtime.answer(_request(statement))
    assert provider.calls == []
    assert result.outcome == "formal"
    assert result.answer is None and result.question is None and result.error_code is None
    assert result.formal_plan == {"kind": "dsp", "statement": statement}
    assert "chat_route" not in result.private_evidence
    assert result.private_evidence["phase"] == "template_fastpath"


@pytest.mark.parametrize("statement", X2_STATEMENTS)
def test_flag_off_keeps_the_router(statement):
    runtime, provider = _runtime([route("lean")], fastpath=False)
    # The router is consulted (and the recorded reply is consumed) exactly as before.
    # The later stages need more fixtures; only the first provider call matters here.
    with contextlib.suppress(Exception):
        runtime.answer(_request(statement), recipe_lookup=lambda items: [])
    assert provider.calls and provider.calls[0]["model"] == "gpt-6.1-sol"


@pytest.mark.parametrize("statement", OTHER_STATEMENTS)
def test_other_requests_keep_the_router_even_with_the_flag_on(statement):
    runtime, provider = _runtime([route("lean")], fastpath=True)
    with contextlib.suppress(Exception):
        runtime.answer(_request(statement), recipe_lookup=lambda items: [])
    assert provider.calls and provider.calls[0]["model"] == "gpt-6.1-sol"
    assert not _template_fastpath_eligible(_request(statement))


@pytest.mark.parametrize(
    "delta",
    [
        {"revision": 2},
        {"retry_count": 1},
        {"formal_job_id": "22222222-2222-4222-8222-222222222222"},
        {"project_id": "33333333-3333-4333-8333-333333333333"},
        {"context_turns": [
            {"question_id": "q", "question": "?", "answer": "a", "attachments": []}]},
        {"chat_history": [
            {"role": "user", "text": "hi", "attachment_ids": [], "context_turns": []}]},
        {"conversation_history": [{"role": "user", "text": "hi"}]},
        {"attachment_ids": ["44444444-4444-4444-8444-444444444444"]},
        {"chat_images": [{"id": "x"}]},
        {"material_context": {"sources": []}},
    ],
)
def test_context_requests_never_take_the_shortcut(delta):
    request = _request(X2_STATEMENTS[2], **delta)
    assert not _template_fastpath_eligible(request)
    assert _template_fastpath_eligible(_request(X2_STATEMENTS[2]))


def test_factory_flag_is_default_on_and_can_be_turned_off(monkeypatch):
    from pals_agent.factory import chat_template_fastpath_enabled

    monkeypatch.delenv("PALS_CHAT_TEMPLATE_FASTPATH_ENABLED", raising=False)
    assert chat_template_fastpath_enabled() is True
    for off in ("off", "false", "0", "FALSE"):
        monkeypatch.setenv("PALS_CHAT_TEMPLATE_FASTPATH_ENABLED", off)
        assert chat_template_fastpath_enabled() is False
    monkeypatch.setenv("PALS_CHAT_TEMPLATE_FASTPATH_ENABLED", "on")
    assert chat_template_fastpath_enabled() is True
