"""The real Lean stderr parser projects only closed codes into versioned EMF."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from pals_agent import quality_events as qe
from pals_agent.lean import parse_lean_diagnostics


@pytest.mark.parametrize(("suffix", "code"), [
    ("", "lean.error"),
    ("(lean.unknownIdentifier)", "lean.unknownIdentifier"),
])
def test_actual_parser_output_reaches_the_shared_event_schema(suffix, code):
    diagnostics = parse_lean_diagnostics(
        f"/private/compiler/Main.lean:3:8: error{suffix}: private diagnostic body\n"
    )
    assert [d.code for d in diagnostics] == [code]
    event = qe.build_lean_attempt(
        environment="probe", diagnostic_codes=[d.code for d in diagnostics],
        success=False, duration_ms=1,
    ).emf
    assert event["diagnostic_code"] == code
    assert event["failure_code"] == "verifier.lean_compile_error"
    schema = Path(qe.__file__).parent / "contracts/quality-event-v1.schema.json"
    Draft202012Validator(json.loads(schema.read_text())).validate(event)
    assert "private diagnostic body" not in json.dumps(event)
    assert "/private/compiler" not in json.dumps(event)
