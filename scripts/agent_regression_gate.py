#!/usr/bin/env python3
"""Decide whether a full agent test run qualifies as the `agent-regression` result.

The candidate (worker) run must be at least as good as the retained verifier anchor
on every test, with no unexplained failure, skip or unexecuted module:

* a failing or erroring candidate test must be listed in the reviewed baseline manifest
  with a cause, AND must fail the same way on the anchor in the same environment;
* a skipped test (core modules included) must be listed in the manifest with a reason;
* every test module under tests/ must execute at least one non-skipped case, unless the
  manifest lists it with a reason;
* the declared core runtime modules must execute with no failure and no unlisted skip;
* a missing, unparsable or too-small report blocks.

Manifest entries that now pass are reported as stale but never excuse anything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CAUSES = frozenset({
    "lean_toolchain_unavailable",
    "cross_repository_fixture_missing",
    "stale_catalog_or_profile_expectation",
    "token_claim_expectation_mismatch",
    "stale_test_double",
    "stale_timing_expectation",
})
BAD = ("failure", "error")
_PHASE = re.compile(r'^failed on (?:setup|teardown) with "')
_SIGNATURE = re.compile(r"^([A-Za-z_][\w.]*)(?=:|\s|$)")


def failure_signature(message: str) -> str:
    """Name the exception class from pytest's JUnit message (it has no `type` attribute)."""
    text = _PHASE.sub("", (message or "").strip())
    if text.startswith("assert"):
        return "AssertionError"
    match = _SIGNATURE.match(text)
    return match[1].rsplit(".", 1)[-1] if match else "unknown"


def read_report(path: Path) -> dict[str, dict[str, str]]:
    """Return {test id: {"outcome": ..., "type": ...}} from a pytest junit report."""
    root = ET.parse(path).getroot()
    cases: dict[str, dict[str, str]] = {}
    for case in root.iter("testcase"):
        test_id = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        outcome, kind = "passed", ""
        for tag in BAD:
            node = case.find(tag)
            if node is not None:
                outcome, kind = tag, failure_signature(node.attrib.get("message", ""))
                break
        else:
            if case.find("skipped") is not None:
                outcome = "skipped"
        previous = cases.get(test_id)
        if previous is not None:
            # pytest emits one element per failing phase (call, teardown). Keep every record:
            # failure beats skip beats pass, and all signatures stay part of the comparison.
            rank = {"passed": 0, "skipped": 1, "failure": 2, "error": 2}
            kinds = sorted({*previous["type"].split("+"), *kind.split("+")} - {""})
            if rank[previous["outcome"]] >= rank[outcome]:
                outcome = previous["outcome"]
            kind = "+".join(kinds)
        cases[test_id] = {"outcome": outcome, "type": kind}
    return cases


def module_of(test_id: str, modules: set[str]) -> str:
    """Resolve a junit classname (module[.Class]) to the longest known test module."""
    parts = test_id.split("::", 1)[0].split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in modules:
            return candidate
    return parts[0]


def test_modules(tests_root: Path) -> set[str]:
    return {
        path.with_suffix("").relative_to(tests_root.parent).as_posix().replace("/", ".")
        for path in tests_root.rglob("test_*.py")
    }


def evaluate(
    candidate: dict[str, dict[str, str]],
    anchor: dict[str, dict[str, str]],
    manifest: dict,
    modules: set[str],
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    core = {path.removesuffix(".py").replace("/", ".") for path in manifest["core_modules"]}
    known = {}
    for entry in manifest["known_failures"]:
        if entry.get("cause") not in CAUSES or not entry.get("reason", "").strip():
            problems.append("manifest_entry_without_cause_or_reason:" + entry.get("id", "?"))
        known[entry["id"]] = entry
    skips = {entry["id"]: entry for entry in manifest["allowed_skips"]}
    if any(not entry.get("reason", "").strip() for entry in skips.values()):
        problems.append("manifest_skip_without_reason")
    if len(candidate) < manifest["minimum_cases"]:
        problems.append(f"too_few_cases:{len(candidate)}<{manifest['minimum_cases']}")

    executed: dict[str, int] = {}
    for test_id, result in candidate.items():
        module = module_of(test_id, modules)
        outcome = result["outcome"]
        if outcome != "skipped":
            executed[module] = executed.get(module, 0) + 1
        if outcome in BAD:
            if module in core:
                problems.append("core_module_failure:" + test_id)
            elif test_id not in known:
                problems.append("unlisted_failure:" + test_id)
            elif anchor.get(test_id, {}).get("outcome") not in BAD:
                problems.append("failure_not_present_on_anchor:" + test_id)
            elif anchor[test_id]["type"] != result["type"]:
                problems.append(
                    f"failure_changed_from_anchor:{test_id}:{anchor[test_id]['type']}->{result['type']}"
                )
        elif outcome == "skipped" and test_id not in skips:
            prefix = "core_module_skip:" if module in core else "unlisted_skip:"
            problems.append(prefix + test_id)
    unexecuted = {entry["id"]: entry for entry in manifest["allowed_unexecuted_modules"]}
    if any(not entry.get("reason", "").strip() for entry in unexecuted.values()):
        problems.append("manifest_unexecuted_module_without_reason")
    for module in sorted(modules):
        if not executed.get(module) and module not in unexecuted:
            problems.append("module_not_executed:" + module)
        elif executed.get(module) and module in unexecuted:
            notes.append("stale_unexecuted_entry_now_executes:" + module)
    for module in sorted(core - modules):
        problems.append("core_module_missing:" + module)
    for test_id in sorted(known):
        if candidate.get(test_id, {}).get("outcome") not in BAD:
            notes.append("stale_baseline_entry_now_not_failing:" + test_id)
    for test_id in sorted(skips):
        if candidate.get(test_id, {}).get("outcome") != "skipped":
            notes.append("stale_skip_entry_now_not_skipped:" + test_id)
    return problems, notes


def failing_files(report: Path, tests_root: Path) -> list[str]:
    modules = test_modules(tests_root)
    files = {
        module_of(test_id, modules).replace(".", "/") + ".py"
        for test_id, result in read_report(report).items()
        if result["outcome"] in BAD
    }
    return sorted(files)


SUPPLEMENT_MODULE = "tests.integration.test_general_recipe_stage_real"
SUPPLEMENT_CASES = frozenset(
    (
        "test_a_by_alternative_cannot_hide_the_side_goal_closers",
        "test_cube_continuity_is_answered_from_the_general_power_recipe",
        "test_non_instances_fall_through[(2 : \\u211d) + 2 = 4]",
        "test_non_instances_fall_through[Continuous (fun x : \\u211d => x ^ 2 + 1)]",
        "test_the_api_wrapper_proves_a_hypothesis_instance_the_lane_accepts",
    )
)


def qualified_supplement(
    candidate: dict[str, dict[str, str]],
    report: Path,
    candidate_metadata: Path,
    supplement_metadata: Path,
    source_revision: str,
    workflow_run_id: str,
) -> dict[str, dict[str, str]]:
    """Union original report outcomes only, from disjoint partitions of one source/run."""
    if not re.fullmatch(r"[a-f0-9]{40}", source_revision or "") or not re.fullmatch(
        r"[0-9]+", workflow_run_id or ""
    ):
        raise ValueError("supplement_source_or_run_required")
    for path, partition in (
        (candidate_metadata, "linux"),
        (supplement_metadata, "general_recipe_real"),
    ):
        metadata = json.loads(path.read_text())
        if metadata != {
            "source_revision": source_revision,
            "workflow_run_id": workflow_run_id,
            "partition": partition,
        }:
            raise ValueError("supplement_source_or_run_mismatch")
    cases = list(ET.parse(report).getroot().iter("testcase"))
    identifiers = [f"{case.get('classname', '')}::{case.get('name', '')}" for case in cases]
    if (
        len(cases) != 5
        or len(set(identifiers)) != 5
        or {case.get("name") for case in cases} != SUPPLEMENT_CASES
    ):
        raise ValueError("supplement_requires_five_unique_cases")
    if any(
        case.get("classname") != SUPPLEMENT_MODULE
        or not case.get("name")
        or any(case.find(tag) is not None for tag in (*BAD, "skipped"))
        for case in cases
    ):
        raise ValueError("supplement_scope_or_outcome_invalid")
    if set(candidate) & set(identifiers):
        raise ValueError("supplement_overlaps_primary")
    # read_report preserves each original testcase's actual outcome; none are synthesized.
    return {**candidate, **read_report(report)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    files = sub.add_parser("failing-files", help="list test files holding failures")
    files.add_argument("--report", type=Path, required=True)
    files.add_argument("--tests", type=Path, default=Path("tests"))
    check = sub.add_parser("check", help="apply the qualification rules")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--anchor", type=Path, required=True)
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--tests", type=Path, default=Path("tests"))
    check.add_argument("--supplement", type=Path)
    check.add_argument("--candidate-metadata", type=Path)
    check.add_argument("--supplement-metadata", type=Path)
    check.add_argument("--source-revision")
    check.add_argument("--workflow-run-id")
    args = parser.parse_args(argv)
    if args.command == "failing-files":
        print("\n".join(failing_files(args.report, args.tests)))
        return 0
    try:
        candidate = read_report(args.candidate)
        if args.supplement is not None:
            if args.candidate_metadata is None or args.supplement_metadata is None:
                raise ValueError("supplement_metadata_required")
            candidate = qualified_supplement(
                candidate, args.supplement, args.candidate_metadata, args.supplement_metadata,
                args.source_revision, args.workflow_run_id,
            )
        elif any((args.candidate_metadata, args.supplement_metadata,
                  args.source_revision, args.workflow_run_id)):
            raise ValueError("supplement_required")
        anchor = read_report(args.anchor)
        manifest = json.loads(args.manifest.read_text())
    except (OSError, ET.ParseError, ValueError, KeyError) as error:
        reason = "report_or_manifest_unreadable:" + type(error).__name__
        print(json.dumps({"status": "blocked", "reason": reason}))
        return 2
    problems, notes = evaluate(candidate, anchor, manifest, test_modules(args.tests))
    counts: dict[str, int] = {}
    for result in candidate.values():
        counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
    print(json.dumps({"status": "blocked" if problems else "qualified", "cases": counts,
                      "problems": problems, "notes": notes}, indent=1, sort_keys=True))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
