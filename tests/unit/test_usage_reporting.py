from uuid import UUID

import pytest

from pals_agent.usage import report_usage, usage_scope


def test_usage_payload_has_only_numeric_content_free_fields_and_scope_is_reset():
    records = []
    raw = {
        "input_tokens": 100,
        "output_tokens": 20,
        "input_tokens_details": {"cached_tokens": 4},
        "output_tokens_details": {"reasoning_tokens": 3},
        "prompt": "must never leave this input",
    }
    with usage_scope(records.append):
        report_usage("00000000-0000-4000-8000-000000000001", "gpt-5.4-nano", raw)
    report_usage("ignored", "gpt-5.4-nano", raw)
    assert len(records) == 1
    assert set(records[0]) == {
        "schema_version",
        "call_id",
        "provider",
        "model",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "price_snapshot_id",
    }
    assert "must never" not in str(records)
    assert UUID(records[0]["call_id"]).version == 4


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": 1, "output_tokens": 1, "input_tokens_details": {"cached_tokens": 2}},
    ],
)
def test_bad_or_missing_usage_is_observable_without_breaking_generation(value, caplog):
    records = []
    with usage_scope(records.append):
        report_usage("id", "gpt-5.4-nano", value)
    assert not records
    assert "Provider usage recording failed" in caplog.text


def test_transport_failure_does_not_escape_or_log_private_error(caplog):
    def fail(value):
        raise RuntimeError("secret transport payload")

    with usage_scope(fail):
        report_usage("id", "gpt-5.4-nano", {"input_tokens": 2, "output_tokens": 3})
    assert "Provider usage recording failed" in caplog.text
    assert "secret transport payload" not in caplog.text


@pytest.mark.parametrize("family", ["mini", "nano"])
@pytest.mark.parametrize("suffix", ["", "-2026-03-17"])
def test_configured_model_releases_emit_versioned_usage_without_double_counting(family, suffix):
    records = []
    model = f"gpt-5.4-{family}{suffix}"
    with usage_scope(records.append):
        report_usage(
            "00000000-0000-4000-8000-000000000001",
            model,
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 100},
                "output_tokens_details": {"reasoning_tokens": 20},
            },
        )
    assert len(records) == 1
    assert records[0]["model"] == model
    assert records[0]["price_snapshot_id"] == f"openai-gpt-5.4-{family}-2026-09-29"
    assert records[0]["input_tokens"] == records[0]["cached_input_tokens"] == 100
    assert records[0]["output_tokens"] == records[0]["reasoning_output_tokens"] == 20


@pytest.mark.parametrize("model", ["unknown", "gpt-5.4-mini-2099-01-01", "gpt-5.4-nano-extra"])
def test_unknown_release_does_not_inherit_a_family_price(model, caplog):
    records = []
    with usage_scope(records.append):
        report_usage("id", model, {"input_tokens": 1, "output_tokens": 1})
    assert not records
    assert "Provider usage recording failed" in caplog.text


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-5.6-terra"])
def test_new_aliases_emit_explicit_upper_bound_snapshot_and_original_totals(model):
    records = []
    with usage_scope(records.append):
        report_usage(
            "id",
            model,
            {
                "input_tokens": 300_000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 200_000},
                "output_tokens_details": {"reasoning_tokens": 20},
            },
        )
    assert len(records) == 1
    assert records[0]["price_snapshot_id"] == f"openai-{model}-standard-upper-bound-2026-09-30"
    assert records[0]["input_tokens"] == 300_000
    assert records[0]["cached_input_tokens"] == 200_000
    assert records[0]["output_tokens"] == 100
    assert records[0]["reasoning_output_tokens"] == 20


@pytest.mark.parametrize("model", ["gpt-6-luna-2026-09-30", "gpt-5.6-terra-extra"])
def test_new_unknown_snapshot_is_never_guessed(model, caplog):
    records = []
    with usage_scope(records.append):
        report_usage("id", model, {"input_tokens": 1, "output_tokens": 1})
    assert not records
    assert "Provider usage recording failed" in caplog.text


def test_embedding_usage_emits_actual_input_tokens_with_exact_standard_snapshot():
    records = []
    with usage_scope(records.append):
        report_usage("id", "text-embedding-3-small", {"input_tokens": 51, "output_tokens": 0})
    assert len(records) == 1
    assert records[0]["price_snapshot_id"] == "openai-text-embedding-3-small-standard-2026-09-30"
    assert records[0]["input_tokens"] == 51
    assert records[0]["output_tokens"] == records[0]["cached_input_tokens"] == 0


def test_unregistered_embedding_snapshot_never_inherits_alias_price(caplog):
    records = []
    with usage_scope(records.append):
        report_usage(
            "id", "text-embedding-3-small-2099-01-01", {"input_tokens": 51, "output_tokens": 0}
        )
    assert not records
    assert "Provider usage recording failed" in caplog.text
