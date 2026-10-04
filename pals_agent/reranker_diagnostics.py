"""Closed metadata for private reranker failures; never retain provider prose."""

from __future__ import annotations

import json
from typing import Any

_STAGES = frozenset(
    {
        "json",
        "envelope",
        "status",
        "model",
        "usage",
        "output",
        "message",
        "content",
        "selection",
        "selection_ids",
    }
)
_STATUSES = frozenset({"completed", "incomplete", "failed", "queued", "in_progress", "cancelled"})
_REASONS = frozenset({"max_output_tokens", "content_filter"})
_TYPES = frozenset(
    {
        "message",
        "reasoning",
        "function_call",
        "computer_call",
        "file_search_call",
        "web_search_call",
        "code_interpreter_call",
        "image_generation_call",
        "custom_tool_call",
        "local_shell_call",
        "shell_call",
        "mcp_call",
        "mcp_list_tools",
        "mcp_approval_request",
    }
)
_COUNTS = frozenset(
    {
        "output_item_count",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
    }
)


def sanitize_reranker_diagnostics(value: object) -> dict[str, Any]:
    """Recheck at every serialization boundary, including caller-created errors."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    stage = value.get("parse_stage")
    if isinstance(stage, str) and stage in _STAGES:
        result["parse_stage"] = stage
    for key, allowed in (("response_status", _STATUSES), ("incomplete_reason", _REASONS)):
        if key in value:
            raw = value[key]
            result[key] = raw if isinstance(raw, str) and raw in allowed else "unknown"
    for key in _COUNTS:
        raw = value.get(key)
        if type(raw) is int and 0 <= raw <= 9_223_372_036_854_775_807:
            result[key] = raw
    raw_types = value.get("output_item_types")
    if isinstance(raw_types, list):
        result["output_item_types"] = [
            v if isinstance(v, str) and v in _TYPES else "unknown" for v in raw_types[:16]
        ]
    return result


def response_diagnostics(body: bytes, stage: str) -> dict[str, Any]:
    result: dict[str, Any] = {"parse_stage": stage}
    try:
        root = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return sanitize_reranker_diagnostics(result)
    if not isinstance(root, dict):
        return sanitize_reranker_diagnostics(result)
    result["response_status"] = root.get("status")
    incomplete = root.get("incomplete_details")
    if isinstance(incomplete, dict):
        result["incomplete_reason"] = incomplete.get("reason")
    output = root.get("output")
    if isinstance(output, list):
        result["output_item_count"] = len(output)
        result["output_item_types"] = [
            v.get("type") if isinstance(v, dict) else None for v in output[:16]
        ]
    usage = root.get("usage")
    if isinstance(usage, dict):
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            result[key] = usage.get(key)
        for name, group, field in (
            ("cached_input_tokens", "input_tokens_details", "cached_tokens"),
            ("reasoning_output_tokens", "output_tokens_details", "reasoning_tokens"),
        ):
            detail = usage.get(group)
            if isinstance(detail, dict):
                result[name] = detail.get(field)
    return sanitize_reranker_diagnostics(result)
