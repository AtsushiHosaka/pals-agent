"""Import planning in the verifier: the header rewrite, the retry over the full imports, and the
status codes. No Lean runs here (the real-Lean checks are in ``tests/integration``)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import pals_agent.lean as lean_module
from pals_agent.lean import LeanVerifier
from pals_agent.lean_environment import VerificationTiming
from pals_agent.lean_import_plan import (
    DECLINE_REASONS,
    RETRY_REASONS,
    STATUS_CODES,
    ImportPlanning,
    ImportSuggestion,
)
from pals_agent.lean_profiles import resolve_profile
from pals_agent.models import Diagnostic, VerificationResult
from tests.unit.test_lean_trusted_audit import NONCE, _ok, _report  # noqa: F401

_SOURCE = (
    "import Mathlib\n"
    "import StacksFrontier.Big\n"
    "\n"
    "open Foo\n"
    "theorem t (x : Nat) : x = x := by\n"
    "  rfl\n"
)


class _Suggester:
    def __init__(self, suggestion: ImportSuggestion | Exception) -> None:
        self.suggestion = suggestion
        self.calls = 0

    def suggest(self, source: str) -> ImportSuggestion:
        self.calls += 1
        if isinstance(self.suggestion, Exception):
            raise self.suggestion
        return self.suggestion


def _planning(*imports: str, **kwargs: object) -> ImportPlanning:
    return ImportPlanning(_Suggester(ImportSuggestion(imports=imports, **kwargs)))  # type: ignore[arg-type]


def _result(*errors: str, success: bool = False) -> VerificationResult:
    return VerificationResult(
        success=success,
        diagnostics=[Diagnostic(severity="error", code="lean.error", message=m) for m in errors],
        stdout="",
        stderr="",
        elapsed_ms=1,
    )


# -- the header rewrite --------------------------------------------------------------------


def test_prepare_replaces_the_header_and_moves_no_other_line() -> None:
    planned = _planning("StacksFrontier.Small", "Mathlib.Order").prepare(_SOURCE, None)

    assert planned.status is None
    assert planned.source == (
        "import StacksFrontier.Small import Mathlib.Order\n"
        "\n"
        "\n"
        "open Foo\n"
        "theorem t (x : Nat) : x = x := by\n"
        "  rfl\n"
    )
    assert planned.source.count("\n") == _SOURCE.count("\n")
    # the line of every command after the header is unchanged
    assert planned.source.splitlines()[4] == _SOURCE.splitlines()[4]


def test_prepare_keeps_comments_and_crlf_and_drops_the_implicit_init() -> None:
    source = (
        "/-! doc\n  more -/\r\n-- note\r\nimport A\r\nimport B -- why\r\n\r\n"
        "theorem t : True := trivial\r\n"
    )
    planned = _planning("Init.Core", "C", "C").prepare(source, None)

    assert planned.source == (
        "/-! doc\n  more -/\r\n-- note\r\nimport C\r\n\r\n\r\ntheorem t : True := trivial\r\n"
    )


@pytest.mark.parametrize(
    ("source", "status"),
    [
        ("theorem t : True := trivial\n", "declined.no_imports"),
        ("-- only a comment\ntheorem t : True := trivial\n", "declined.no_imports"),
        ("module\nimport A\ntheorem t : True := trivial\n", "declined.header_unsupported"),
        ("prelude\nimport A\n", "declined.header_unsupported"),
        ("public import A\ntheorem t : True := trivial\n", "declined.header_unsupported"),
        ("import all A\ntheorem t : True := trivial\n", "declined.header_unsupported"),
        ("/- c -/ import A\ntheorem t : True := trivial\n", "declined.header_unsupported"),
    ],
)
def test_headers_that_cannot_be_rewritten_are_left_alone(source: str, status: str) -> None:
    suggester = _Suggester(ImportSuggestion(imports=("X",)))

    planned = ImportPlanning(suggester).prepare(source, None)

    assert (planned.source, planned.status) == (None, status)
    assert suggester.calls == 0  # nothing to rewrite, so nothing was asked


def test_a_command_ends_the_header() -> None:
    source = "import A\ntheorem t : True := trivial\nimport B\n"

    planned = _planning("C").prepare(source, None)

    assert planned.source == "import C\ntheorem t : True := trivial\nimport B\n"


@pytest.mark.parametrize(
    ("suggestion", "status"),
    [
        (ImportSuggestion(imports=()), "declined.plan_empty"),
        (ImportSuggestion(imports=("Init.Core", "Init")), "declined.plan_empty"),
        (ImportSuggestion(imports=("Bad Name",)), "declined.plan_error"),
        (ImportSuggestion(imports=("A;B",)), "declined.plan_error"),
        (ImportSuggestion(declined="plan_unresolved"), "declined.plan_unresolved"),
        (ImportSuggestion(declined="not_a_reason"), "declined.plan_error"),
        (ImportSuggestion(imports=("Mathlib", "StacksFrontier.Big")), "declined.same_imports"),
    ],
)
def test_prepare_declines_instead_of_guessing(suggestion: ImportSuggestion, status: str) -> None:
    planned = ImportPlanning(_Suggester(suggestion)).prepare(_SOURCE, None)

    assert (planned.source, planned.status) == (None, status)


def test_a_failing_suggester_declines_and_does_not_raise() -> None:
    planned = ImportPlanning(_Suggester(RuntimeError("secret statement text"))).prepare(
        _SOURCE, None
    )

    assert (planned.source, planned.status) == (None, "declined.plan_error")


def test_the_profile_allow_list_applies_to_the_planned_header() -> None:
    stacks = resolve_profile("stacks-4.35")  # Mathlib and StacksCore only
    frontier = resolve_profile("stacks-frontier-defs-4.35")

    refused = _planning("StacksFrontier.Small").prepare(_SOURCE, stacks)
    allowed = _planning("StacksFrontier.Small").prepare(_SOURCE, frontier)

    assert (refused.source, refused.status) == (None, "declined.plan_import_not_allowed")
    assert allowed.source is not None and allowed.status is None


# -- which failures deserve a retry --------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Unknown identifier `Foo.bar`", "unknown_identifier"),
        ("unknown namespace `Foo`", "unknown_namespace"),
        ("Unknown constant `Foo.bar`", "unknown_constant"),
        ("unknown tactic", "unknown_tactic"),
        ("unknown module prefix 'StacksFrontier'", "import_unavailable"),
        ("object file '/x/Foo.olean' of module Foo does not exist", "import_unavailable"),
    ],
)
def test_import_shaped_errors_are_retried(message: str, reason: str) -> None:
    assert ImportPlanning.retry_reason(_result(message)) == reason
    assert reason in RETRY_REASONS


def test_other_failures_and_successes_are_not_retried() -> None:
    assert ImportPlanning.retry_reason(_result("type mismatch")) is None
    assert ImportPlanning.retry_reason(_result("failed to synthesize Foo")) is None
    assert ImportPlanning.retry_reason(_result("Lean timed out")) is None
    assert ImportPlanning.retry_reason(_result("Unknown identifier `x`", success=True)) is None
    warning = VerificationResult(
        success=False,
        diagnostics=[Diagnostic(severity="warning", code="lean.warning", message="unknown tactic")],
        stdout="",
        stderr="",
        elapsed_ms=1,
    )
    assert ImportPlanning.retry_reason(warning) is None


def test_status_codes_are_a_closed_content_free_vocabulary() -> None:
    assert len(STATUS_CODES) == 1 + len(DECLINE_REASONS) + len(RETRY_REASONS)
    assert all(re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)?", code) for code in STATUS_CODES)


# -- the verifier with a mocked compiler ---------------------------------------------------------


class _Compiler:
    """Fake compile and audit processes; ``fail_when`` picks the sources that fail to compile."""

    def __init__(self, fail_when: dict[str, str] | None = None) -> None:
        self.fail_when = fail_when or {}
        self.compiled: list[str] = []
        self.references: list[str] = []
        self.timeouts: list[float] = []

    def __call__(self, command: list[str], **kwargs: object) -> lean_module._ProcessResult:
        self.timeouts.append(float(kwargs["timeout_seconds"]))  # type: ignore[arg-type]
        if "--run" in command:
            run = command.index("--run")
            self.references.append(Path(command[run + 4]).read_text(encoding="utf-8"))
            return _ok(_report("theorem t", "axiom propext", "bound t", nonce=command[run + 2]))
        source = Path(command[-1]).read_text(encoding="utf-8")
        self.compiled.append(source)
        for marker, message in self.fail_when.items():
            if marker in source:
                stderr = f"Main.lean:5:2: error: {message}\n"
                return lean_module._ProcessResult(1, "", stderr, False, False)
        if "-o" in command:
            Path(command[command.index("-o") + 1]).write_bytes(b"olean")
        return _ok()


@pytest.fixture
def events() -> list[VerificationTiming]:
    return []


def _verifier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compiler: _Compiler,
    events: list[VerificationTiming],
    planning: ImportPlanning | None,
    **options: object,
) -> LeanVerifier:
    monkeypatch.setattr("pals_agent.lean.shutil.which", lambda binary, **_kw: f"/usr/bin/{binary}")
    monkeypatch.setattr(lean_module, "_run_limited_process", compiler)
    return LeanVerifier(
        scratch_dir=tmp_path,
        timing_observer=events.append,
        import_planning=planning,
        **options,  # type: ignore[arg-type]
    )


def _plan_events(events: list[VerificationTiming]) -> list[tuple[str | None, int | None]]:
    return [(e.import_plan, e.import_plan_modules) for e in events if e.stage == "import_plan"]


def test_planning_is_off_by_default_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler()

    result = _verifier(tmp_path, monkeypatch, compiler, events, None).verify(_SOURCE)

    assert result.success
    assert compiler.compiled == [_SOURCE]
    assert _plan_events(events) == []


def test_a_plan_is_compiled_and_audited_instead_of_the_written_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler()
    planning = _planning("StacksFrontier.Small", loaded_modules=77)

    result = _verifier(tmp_path, monkeypatch, compiler, events, planning).verify(_SOURCE)

    assert result.success
    assert len(compiler.compiled) == 1
    assert compiler.compiled[0].startswith("import StacksFrontier.Small\n")
    assert "StacksFrontier.Big" not in compiler.compiled[0]
    # the trusted audit elaborates the statements over the plan's imports, too
    assert compiler.references and "StacksFrontier.Big" not in compiler.references[0]
    assert _plan_events(events) == [("applied", 77)]


def test_an_import_shaped_failure_is_verified_once_more_over_every_written_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler(fail_when={"import StacksFrontier.Small": "Unknown identifier `Foo.bar`"})
    planning = _planning("StacksFrontier.Small", loaded_modules=77)

    result = _verifier(tmp_path, monkeypatch, compiler, events, planning).verify(_SOURCE)

    assert result.success
    assert compiler.compiled == [
        _SOURCE.replace(
            "import Mathlib\nimport StacksFrontier.Big\n", "import StacksFrontier.Small\n\n"
        ),
        _SOURCE,
    ]
    assert _plan_events(events) == [("retried.unknown_identifier", 77)]
    # the retry runs inside what is left of the one deadline, not a fresh one
    assert compiler.timeouts[-1] < compiler.timeouts[0] or compiler.timeouts[-1] <= 300.0


def test_the_retry_happens_once_even_if_the_full_imports_fail_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler(fail_when={"theorem t": "unknown namespace `Foo`"})

    result = _verifier(
        tmp_path, monkeypatch, compiler, events, _planning("StacksFrontier.Small")
    ).verify(_SOURCE)

    assert not result.success
    assert len(compiler.compiled) == 2
    assert _plan_events(events) == [("retried.unknown_namespace", None)]


def test_an_ordinary_failure_over_a_plan_is_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler(fail_when={"import StacksFrontier.Small": "type mismatch"})

    result = _verifier(
        tmp_path, monkeypatch, compiler, events, _planning("StacksFrontier.Small")
    ).verify(_SOURCE)

    assert not result.success
    assert len(compiler.compiled) == 1
    assert _plan_events(events) == [("applied", None)]


def test_without_a_plan_the_original_is_verified_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler()

    result = _verifier(tmp_path, monkeypatch, compiler, events, _planning()).verify(_SOURCE)

    assert result.success
    assert compiler.compiled == [_SOURCE]
    assert _plan_events(events) == [("declined.plan_empty", None)]


def test_sketches_use_the_plan_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler()
    sketch = _SOURCE.replace("rfl", "sorry")

    result = _verifier(
        tmp_path, monkeypatch, compiler, events, _planning("StacksFrontier.Small")
    ).verify_sketch(sketch)

    assert result.success
    assert compiler.compiled[0].startswith("import StacksFrontier.Small\n")


def test_a_plan_can_never_hide_an_import_the_profile_forbids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler()
    forbidden = "import Lake\n" + _SOURCE
    verifier = _verifier(
        tmp_path, monkeypatch, compiler, events, _planning("Mathlib.Order"),
        library_profile=resolve_profile("stacks-4.35"),
    )

    result = verifier.verify(forbidden)

    assert not result.success
    assert [d.code for d in result.diagnostics] == ["lean.disallowed_import"]
    assert compiler.compiled == []


def test_a_plan_outside_the_profile_falls_back_without_compiling_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    compiler = _Compiler()
    source = _SOURCE.replace("StacksFrontier.Big", "Mathlib.Order")
    verifier = _verifier(
        tmp_path, monkeypatch, compiler, events, _planning("StacksFrontier.Small"),
        library_profile=resolve_profile("stacks-4.35"),
    )

    assert verifier.verify(source).success
    assert compiler.compiled == [source]
    assert _plan_events(events) == [("declined.plan_import_not_allowed", None)]


def test_every_reported_status_is_in_the_closed_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[VerificationTiming]
) -> None:
    for suggestion in (
        ImportSuggestion(imports=("A",)),
        ImportSuggestion(declined="plan_conflict"),
    ):
        _verifier(
            tmp_path, monkeypatch, _Compiler(), events, ImportPlanning(_Suggester(suggestion))
        ).verify(_SOURCE)

    statuses = [status for status, _ in _plan_events(events)]
    assert statuses and set(statuses) <= STATUS_CODES
