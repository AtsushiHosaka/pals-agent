"""Closed provider diagnostics for private artifacts; never retain HTTP prose or headers."""

from __future__ import annotations

import json
from typing import Any

_ENUMS = {
    "schema_hint": {
        "nesting_depth",
        "property_limit",
        "enum_limit",
        "required_fields",
        "additional_properties",
        "unsupported_keyword",
        "anyof_branch_keys",
        "invalid_reference",
        "other",
    },
    "stage": {
        "configuration",
        "transport",
        "http",
        "json",
        "model",
        "structured_status",
        "output",
        "content",
        "empty_text",
    },
    "transport_kind": {"deadline", "response_too_large", "transport_error", "unknown"},
    "provider_code": {
        "invalid_json_schema",
        "invalid_request_error",
        "invalid_value",
        "unsupported_parameter",
        "unsupported_value",
        "missing_required_parameter",
        "context_length_exceeded",
        "rate_limit_exceeded",
        "insufficient_quota",
        "invalid_api_key",
        "model_not_found",
        "server_error",
        "timeout",
        "other",
    },
    "provider_type": {
        "invalid_request_error",
        "authentication_error",
        "permission_error",
        "rate_limit_error",
        "server_error",
        "insufficient_quota",
        "other",
    },
    "provider_param": {
        "text.format",
        "text.format.schema",
        "text.format.name",
        "text.format.type",
        "text.format.strict",
        "model",
        "max_output_tokens",
        "input",
        "other",
    },
    "response_status": {
        "completed",
        "incomplete",
        "failed",
        "cancelled",
        "queued",
        "in_progress",
        "other",
    },
    "incomplete_reason": {"max_output_tokens", "content_filter", "other"},
}


def sanitize_openai_diagnostics(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, allowed in _ENUMS.items():
        item = value.get(key)
        if isinstance(item, str) and item in allowed:
            result[key] = item
    status = value.get("http_status")
    if type(status) is int and 100 <= status <= 599:
        result["http_status"] = status
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate error member")
        result[key] = value
    return result


def http_failure_diagnostics(status: int, raw: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {"stage": "http", "http_status": status}
    if not isinstance(raw, bytes) or len(raw) > 16384:
        return sanitize_openai_diagnostics(result)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError):
        return sanitize_openai_diagnostics(result)
    error = value.get("error") if isinstance(value, dict) else None
    if isinstance(error, dict):
        for field in ("code", "type", "param"):
            item = error.get(field)
            key = "provider_" + field
            if isinstance(item, str):
                result[key] = item if item in _ENUMS[key] else "other"
        if (
            status == 400
            and isinstance(error.get("param"), str)
            and error.get("param") in {"text.format.schema", "text.format"}
            and (
                error.get("code") == "invalid_json_schema"
                or error.get("type") == "invalid_request_error"
            )
        ):
            result["schema_hint"] = _schema_hint(error.get("message"))
    return sanitize_openai_diagnostics(result)


def _schema_hint(message: object) -> str:
    # Inspect only the bounded in-memory error envelope; never retain any prose/path.
    if not isinstance(message, str):
        return "other"
    value = message.lower()
    if "anyof" in value and ("first key" in value or "branch key" in value):
        return "anyof_branch_keys"
    if "additionalproperties" in value or "additional_properties" in value:
        return "additional_properties"
    if "required" in value and (
        "missing" in value
        or "required'" in value
        or 'required"' in value
        or "required fields" in value
    ):
        return "required_fields"
    limit = any(word in value for word in ("limit", "maximum", "too many", "exceed"))
    if ("nesting" in value or "nested" in value) and (limit or "depth" in value):
        return "nesting_depth"
    if "properties" in value and limit:
        return "property_limit"
    if "enum" in value and limit:
        return "enum_limit"
    if ("$ref" in value or "reference" in value) and any(
        word in value for word in ("invalid", "unresolved", "not found", "does not exist")
    ):
        return "invalid_reference"
    if "keyword" in value and any(
        word in value for word in ("unsupported", "not permitted", "not supported")
    ):
        return "unsupported_keyword"
    return "other"


def response_failure_diagnostics(body: dict[str, Any], stage: str) -> dict[str, Any]:
    result = {"stage": stage}
    status = body.get("status")
    if isinstance(status, str):
        result["response_status"] = status if status in _ENUMS["response_status"] else "other"
    details = body.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, dict) else None
    if isinstance(reason, str):
        result["incomplete_reason"] = reason if reason in _ENUMS["incomplete_reason"] else "other"
    return sanitize_openai_diagnostics(result)
