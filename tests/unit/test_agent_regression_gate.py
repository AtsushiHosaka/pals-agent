"""The worker qualification gate must block every way of turning red into green."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "agent_regression_gate", _ROOT / "scripts" / "agent_regression_gate.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
sys.modules["agent_regression_gate"] = gate
_SPEC.loader.exec_module(gate)

MODULES = {"tests.unit.test_core", "tests.unit.test_other", "tests.unit.test_lean_real"}
MANIFEST = {
    "minimum_cases": 3,
    "core_modules": ["tests/unit/test_core.py"],
    "known_failures": [
        {"id": "tests.unit.test_other::test_known", "cause": "lean_toolchain_unavailable",
         "reason": "needs Lean"},
    ],
    "allowed_skips": [
        {"id": "tests.unit.test_other::test_skip", "reason": "optional"},
        {"id": "tests.unit.test_lean_real::test_x", "reason": "no toolchain"},
    ],
    "allowed_unexecuted_modules": [{"id": "tests.unit.test_lean_real", "reason": "no toolchain"}],
}


def case(outcome: str = "passed", kind: str = "") -> dict[str, str]:
    return {"outcome": outcome, "type": kind}


def baseline() -> tuple[dict, dict]:
    candidate = {
        "tests.unit.test_core::test_a": case(),
        "tests.unit.test_other::test_ok": case(),
        "tests.unit.test_other::test_known": case("failure", "AssertionError"),
        "tests.unit.test_other::test_skip": case("skipped"),
        "tests.unit.test_lean_real::test_x": case("skipped"),
    }
    anchor = {"tests.unit.test_other::test_known": case("failure", "AssertionError")}
    return candidate, anchor


def run(candidate: dict, anchor: dict, manifest: dict | None = None) -> list[str]:
    return gate.evaluate(candidate, anchor, manifest or MANIFEST, MODULES)[0]


def test_the_expected_baseline_qualifies() -> None:
    assert run(*baseline()) == []


def test_a_new_failure_is_blocked() -> None:
    candidate, anchor = baseline()
    candidate["tests.unit.test_other::test_ok"] = case("failure", "AssertionError")
    assert run(candidate, anchor) == ["unlisted_failure:tests.unit.test_other::test_ok"]


def test_a_listed_failure_that_passes_on_the_anchor_is_blocked() -> None:
    candidate, anchor = baseline()
    anchor["tests.unit.test_other::test_known"] = case()
    assert run(candidate, anchor) == [
        "failure_not_present_on_anchor:tests.unit.test_other::test_known"
    ]


def test_a_listed_failure_that_is_absent_on_the_anchor_is_blocked() -> None:
    candidate, _ = baseline()
    assert run(candidate, {}) == ["failure_not_present_on_anchor:tests.unit.test_other::test_known"]


def test_a_listed_failure_that_changes_its_error_type_is_blocked() -> None:
    candidate, anchor = baseline()
    candidate["tests.unit.test_other::test_known"] = case("error", "KeyError")
    problems = run(candidate, anchor)
    assert problems and problems[0].startswith("failure_not_present_on_anchor") is False
    assert problems[0].startswith("failure_changed_from_anchor")


def test_a_failure_in_a_core_module_is_never_excused() -> None:
    candidate, anchor = baseline()
    candidate["tests.unit.test_core::test_a"] = case("failure", "AssertionError")
    anchor["tests.unit.test_core::test_a"] = case("failure", "AssertionError")
    manifest = copy.deepcopy(MANIFEST)
    manifest["known_failures"].append(
        {"id": "tests.unit.test_core::test_a", "cause": "stale_test_double", "reason": "x"}
    )
    assert run(candidate, anchor, manifest) == ["core_module_failure:tests.unit.test_core::test_a"]


def test_an_unlisted_skip_is_blocked() -> None:
    candidate, anchor = baseline()
    candidate["tests.unit.test_other::test_new_skip"] = case("skipped")
    assert run(candidate, anchor) == ["unlisted_skip:tests.unit.test_other::test_new_skip"]


def test_a_skip_in_a_core_module_is_blocked() -> None:
    candidate, anchor = baseline()
    candidate["tests.unit.test_core::test_s"] = case("skipped")  # not in allowed_skips
    assert run(candidate, anchor) == ["core_module_skip:tests.unit.test_core::test_s"]


def test_a_module_that_never_executes_is_blocked() -> None:
    candidate, anchor = baseline()
    del candidate["tests.unit.test_core::test_a"]
    candidate["tests.unit.test_core::test_b"] = case("skipped")
    problems = run(candidate, anchor)
    assert "module_not_executed:tests.unit.test_core" in problems


def test_too_few_cases_are_blocked() -> None:
    manifest = copy.deepcopy(MANIFEST)
    manifest["minimum_cases"] = 10
    assert run(*baseline(), manifest) == ["too_few_cases:5<10"]


def test_a_manifest_entry_needs_a_cause_and_a_reason() -> None:
    manifest = copy.deepcopy(MANIFEST)
    manifest["known_failures"][0]["cause"] = "whatever"
    assert run(*baseline(), manifest) == [
        "manifest_entry_without_cause_or_reason:tests.unit.test_other::test_known"
    ]


def test_a_fixed_baseline_entry_is_reported_but_never_excuses_anything() -> None:
    candidate, anchor = baseline()
    candidate["tests.unit.test_other::test_known"] = case()
    problems, notes = gate.evaluate(candidate, anchor, MANIFEST, MODULES)
    assert problems == []
    assert notes == ["stale_baseline_entry_now_not_failing:tests.unit.test_other::test_known"]


def test_a_collection_error_is_blocked(tmp_path: Path) -> None:
    report = tmp_path / "r.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="" name="tests.unit.test_core">'
        '<error type="ImportError" message="x"/></testcase></testsuite></testsuites>'
    )
    parsed = gate.read_report(report)
    problems = run(parsed, {})
    assert "unlisted_failure:::tests.unit.test_core" in problems


def test_an_unreadable_report_blocks(tmp_path: Path) -> None:
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(MANIFEST))
    code = gate.main(["check", "--candidate", str(tmp_path / "missing.xml"),
                      "--anchor", str(tmp_path / "missing.xml"), "--manifest", str(manifest)])
    assert code == 2


def test_the_committed_manifest_only_uses_known_causes() -> None:
    manifest = json.loads(
        (_ROOT / "tests/qualification/agent_regression_manifest.json").read_text()
    )
    assert all(entry["cause"] in gate.CAUSES and entry["reason"].strip()
               for entry in manifest["known_failures"])
    assert all((_ROOT / path).is_file() for path in manifest["core_modules"])
