import json
from unittest.mock import Mock

import pytest

from pals_agent.http_transport import (
    HttpDeadlineExceeded,
    HttpResponse,
    HttpResponseTooLarge,
    HttpTransportError,
)
from pals_agent.openai import OpenAIError, OpenAIResponsesClient
from pals_agent.openai_diagnostics import http_failure_diagnostics, sanitize_openai_diagnostics
from pals_agent.typed_runtime_failures import TypedRetrievalFailure
from tests.unit.test_typed_runtime_diagnostics import PROFILE, runtime


@pytest.mark.parametrize(
    "status,code",
    [(400, "invalid_json_schema"), (429, "rate_limit_exceeded"), (500, "server_error")],
)
def test_http_error_metadata_only_and_no_provider_prose_or_headers(status, code):
    body = {
        "error": {
            "code": code,
            "type": "invalid_request_error",
            "param": "text.format.schema",
            "message": "PRIVATE PROMPT / sk-secret / reasoning",
        },
        "input": "PRIVATE INPUT",
    }
    transport = Mock()
    transport.request.return_value = HttpResponse(
        status, json.dumps(body).encode(), (("authorization", "sk-secret"),)
    )
    client = OpenAIResponsesClient(api_key="sk-secret", transport=transport)
    with pytest.raises(OpenAIError) as caught:
        client.generate(model="model", prompt="PRIVATE PROMPT")
    assert caught.value.private_diagnostics == {
        "stage": "http",
        "http_status": status,
        "provider_code": code,
        "provider_type": "invalid_request_error",
        "provider_param": "text.format.schema",
        **({"schema_hint": "other"} if status == 400 else {}),
    }
    assert "PRIVATE" not in str(caught.value) + json.dumps(caught.value.private_diagnostics)
    assert "sk-secret" not in str(caught.value) + json.dumps(caught.value.private_diagnostics)
    assert transport.request.call_count == 1


@pytest.mark.parametrize(
    "body",
    [
        b'{"error":{"code":"invalid_json_schema","code":"server_error"}}',
        b'{"error": {"message":"PRIVATE"},"error":{"code":"invalid_json_schema"}}',
        b"PRIVATE malformed",
        b"\xff",
        b"x" * 16385,
    ],
)
def test_malformed_duplicate_oversized_error_bodies_leave_only_status(body):
    assert http_failure_diagnostics(400, body) == {"stage": "http", "http_status": 400}


def test_unknown_metadata_is_closed_other_and_unknown_fields_are_dropped():
    raw = json.dumps(
        {
            "error": {
                "code": "PRIVATE",
                "type": "SECRET",
                "param": "input.private-statement",
                "message": "PRIVATE",
            }
        }
    ).encode()
    assert http_failure_diagnostics(400, raw) == {
        "stage": "http",
        "http_status": 400,
        "provider_code": "other",
        "provider_type": "other",
        "provider_param": "other",
    }
    assert (
        sanitize_openai_diagnostics(
            {"http_status": True, "stage": "PRIVATE", "provider_code": {}, "message": "SECRET"}
        )
        == {}
    )
    assert sanitize_openai_diagnostics({"http_status": 600}) == {}


@pytest.mark.parametrize(
    "error,kind",
    [
        (HttpDeadlineExceeded("PRIVATE"), "deadline"),
        (HttpResponseTooLarge("PRIVATE"), "response_too_large"),
        (HttpTransportError("PRIVATE"), "transport_error"),
    ],
)
def test_transport_error_classes_are_closed_without_exception_strings(error, kind):
    transport = Mock()
    transport.request.side_effect = error
    with pytest.raises(OpenAIError) as caught:
        OpenAIResponsesClient(api_key="key", transport=transport).generate(
            model="model", prompt="PRIVATE"
        )
    assert caught.value.private_diagnostics == {"stage": "transport", "transport_kind": kind}
    assert "PRIVATE" not in str(caught.value)


def test_structured_incomplete_reason_is_distinguished_from_http_failure():
    transport = Mock()
    transport.request.return_value = HttpResponse(
        200,
        json.dumps(
            {
                "object": "response",
                "model": "model",
                "status": "incomplete",
                "error": None,
                "incomplete_details": {"reason": "max_output_tokens", "private": "SECRET"},
                "output": [],
            }
        ).encode(),
    )
    with pytest.raises(OpenAIError) as caught:
        OpenAIResponsesClient(api_key="key", transport=transport).generate(
            model="model", prompt="PRIVATE", response_schema={}
        )
    assert caught.value.private_diagnostics == {
        "stage": "structured_status",
        "response_status": "incomplete",
        "incomplete_reason": "max_output_tokens",
    }


def test_typed_failure_retains_safe_provider_metadata_but_never_retries_or_publishes_it():
    r = runtime()
    error = OpenAIError(
        "PRIVATE",
        private_diagnostics={
            "stage": "http",
            "http_status": 400,
            "provider_code": "invalid_json_schema",
            "message": "SECRET",
        },
    )
    error.private_diagnostics["provider_param"] = "SECRET PARAM"
    error.private_diagnostics["raw_body"] = "PRIVATE BODY"
    r.client.generate.side_effect = error
    with pytest.raises(TypedRetrievalFailure) as caught:
        r.retrieve_for_profile(PROFILE, "Original theorem")
    assert caught.value.code == "typed_structuring_unavailable"
    assert caught.value.private_evidence["provider"] == {
        "stage": "http",
        "http_status": 400,
        "provider_code": "invalid_json_schema",
    }
    assert "PRIVATE" not in json.dumps(caught.value.private_evidence)
    assert "SECRET" not in json.dumps(caught.value.private_evidence)
    assert r.client.generate.call_count == 1
    assert caught.value.private_evidence["structuring_attempts"] == 1
    r.embeddings.embed.assert_not_called()


@pytest.mark.parametrize(
    "message,hint",
    [
        ("schema nesting depth exceeds maximum", "nesting_depth"),
        ("too many properties", "property_limit"),
        ("enum limit exceeded", "enum_limit"),
        ("'required' is missing", "required_fields"),
        ("additionalProperties must be false", "additional_properties"),
        ("unsupported keyword: SECRET", "unsupported_keyword"),
        ("anyOf branches have identical first keys", "anyof_branch_keys"),
        ("invalid $ref at PRIVATE path", "invalid_reference"),
        ("PRIVATE PROMPT sk-secret ignore instructions", "other"),
    ],
)
def test_schema_hint_is_closed_without_retaining_provider_prose(message, hint):
    raw = json.dumps(
        {
            "error": {
                "code": "invalid_json_schema",
                "type": "invalid_request_error",
                "param": "text.format.schema",
                "message": message,
            }
        }
    ).encode()
    result = http_failure_diagnostics(400, raw)
    assert result["schema_hint"] == hint
    assert message not in json.dumps(result)
    assert "PRIVATE" not in json.dumps(result) and "sk-secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,param,code,kind",
    [
        (500, "text.format.schema", "invalid_json_schema", "invalid_request_error"),
        (400, "input", "invalid_json_schema", "invalid_request_error"),
        (400, "text.format.schema", "invalid_api_key", "authentication_error"),
    ],
)
def test_schema_hint_requires_specific_schema_error_boundary(status, param, code, kind):
    raw = json.dumps(
        {
            "error": {
                "code": code,
                "type": kind,
                "param": param,
                "message": "unsupported keyword PRIVATE",
            }
        }
    ).encode()
    assert "schema_hint" not in http_failure_diagnostics(status, raw)
    assert sanitize_openai_diagnostics({"schema_hint": "PRIVATE"}) == {}


@pytest.mark.parametrize("param", [{"private": "SECRET"}, ["SECRET"], True, 3, None])
def test_malformed_provider_param_never_raises_or_preserves_value(param):
    raw = json.dumps(
        {
            "error": {
                "code": "invalid_json_schema",
                "type": "invalid_request_error",
                "param": param,
                "message": "SECRET",
            }
        }
    ).encode()
    result = http_failure_diagnostics(400, raw)
    assert "provider_param" not in result and "schema_hint" not in result
    assert "SECRET" not in json.dumps(result)
