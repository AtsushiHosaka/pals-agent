"""Deterministic lemma-name repair: table, patch, pipeline hook and the real compiler."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.lean import parse_lean_diagnostics
from pals_agent.lemma_repair import (
    MAX_PATCH_ROUNDS,
    SCHEMA_VERSION,
    LemmaAliasTableError,
    default_lemma_alias_table,
    parse_lemma_alias_table,
    patch_unknown_lemmas,
    repair_unknown_lemmas,
    unknown_names,
)
from pals_agent.models import (
    Diagnostic,
    GeneratedProof,
    GenerationFeedback,
    ProofRequest,
    RepairRouteDecision,
    VerificationResult,
)
from pals_agent.pipeline import ApiRepairSeed, ProofPipeline
from pals_agent.settings import AgentSettings, _strict_bool_env_default

REPO = Path(__file__).parents[2]
PINNED_LEAN = "4.32.0-rc1"
PINNED_MATHLIB = "8b62164d808cd0f23b7d8cc28190a6c1a1bb483a"
STATEMENT = "theorem tri (a b : ℝ) : |a + b| ≤ |a| + |b|"
ABS_ADD_PROOF = f"import Mathlib\n\n{STATEMENT} := by\n  exact abs_add a b\n"
ABS_ADD_PATCHED = f"import Mathlib\n\n{STATEMENT} := by\n  exact abs_add_le a b\n"


def _entry(wrong: str = "foo_bar", right: Any = "foo_baz", **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "wrong": wrong,
        "right": right,
        "note": "n",
        "example": "example : True := trivial",
        "verified_with": {"lean": PINNED_LEAN, "mathlib": PINNED_MATHLIB},
    }
    entry.update(overrides)
    return entry


def _table(*entries: dict[str, Any]) -> Any:
    return parse_lemma_alias_table({"schema_version": SCHEMA_VERSION, "entries": list(entries)})


def _unknown(name: str, code: str = "lean.unknownIdentifier") -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=f"Unknown identifier `{name}`")


def _failure(*diagnostics: Diagnostic) -> VerificationResult:
    return VerificationResult(
        success=False, diagnostics=list(diagnostics), stdout="", stderr="", elapsed_ms=1
    )


SUCCESS = VerificationResult(success=True, diagnostics=[], stdout="", stderr="", elapsed_ms=1)
TABLE = _table(_entry("abs_add", "abs_add_le"), _entry("sub_eq_zero_iff_eq", "sub_eq_zero"))


# --- the packaged table -------------------------------------------------------------------------


def test_packaged_table_loads_and_starts_with_abs_add() -> None:
    table = default_lemma_alias_table()
    assert (table.aliases[0].wrong, table.aliases[0].right) == ("abs_add", "abs_add_le")
    assert len(table.aliases) == len({alias.wrong for alias in table.aliases})


def test_every_row_is_verified_with_the_pinned_toolchain() -> None:
    toolchain = (REPO / "lean-workspace" / "lean-toolchain").read_text().strip()
    manifest = json.loads((REPO / "lean-workspace" / "lake-manifest.json").read_text())
    mathlib = next(p["rev"] for p in manifest["packages"] if p["name"] == "mathlib")
    assert toolchain == f"leanprover/lean4:v{PINNED_LEAN}"
    assert mathlib == PINNED_MATHLIB
    for alias in default_lemma_alias_table().aliases:
        assert (alias.lean, alias.mathlib) == (PINNED_LEAN, PINNED_MATHLIB), alias.wrong


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p.update(schema_version="other"), id="schema-version"),
        pytest.param(lambda p: p.update(extra=1), id="extra-top-level-key"),
        pytest.param(lambda p: p.update(entries={}), id="entries-not-a-list"),
        pytest.param(lambda p: p["entries"].append(_entry()), id="duplicate-wrong"),
        pytest.param(lambda p: p["entries"].append(_entry("a", "a")), id="wrong-equals-right"),
        pytest.param(lambda p: p["entries"].append(_entry("a b", "c")), id="space-in-wrong"),
        pytest.param(lambda p: p["entries"].append(_entry("1abc", "c")), id="digit-first"),
        pytest.param(lambda p: p["entries"].append(_entry("a..b", "c")), id="empty-segment"),
        pytest.param(lambda p: p["entries"].append(_entry("a.", "c")), id="trailing-dot"),
        pytest.param(lambda p: p["entries"].append(_entry("a", "")), id="empty-right"),
        pytest.param(lambda p: p["entries"].append(_entry("a", "b`c")), id="backtick-right"),
        pytest.param(lambda p: p["entries"].append(_entry("a", "foo_bar")), id="chain"),
        pytest.param(lambda p: p["entries"].append(_entry("a", 7)), id="non-string"),
        pytest.param(lambda p: p["entries"][0].pop("note"), id="missing-note"),
        pytest.param(lambda p: p["entries"][0].pop("example"), id="missing-example"),
        pytest.param(lambda p: p["entries"][0].update(extra=1), id="extra-entry-key"),
        pytest.param(lambda p: p["entries"][0].update(note=" "), id="blank-note"),
        pytest.param(lambda p: p["entries"][0].pop("verified_with"), id="missing-verified"),
        pytest.param(
            lambda p: p["entries"][0]["verified_with"].update(mathlib="main"), id="bad-revision"
        ),
        pytest.param(lambda p: p["entries"][0]["verified_with"].pop("lean"), id="missing-lean"),
    ],
)
def test_schema_errors_are_rejected(mutate: Any) -> None:
    payload = {"schema_version": SCHEMA_VERSION, "entries": [_entry()]}
    payload = copy.deepcopy(payload)
    mutate(payload)
    with pytest.raises(LemmaAliasTableError):
        parse_lemma_alias_table(payload)


def test_a_non_object_table_is_rejected() -> None:
    with pytest.raises(LemmaAliasTableError):
        parse_lemma_alias_table([])


def test_lean_identifiers_with_subscripts_primes_and_namespaces_are_valid() -> None:
    table = _table(_entry("div_le_iff'", "div_le_iff₀'"), _entry("sq_sqrt", "Real.sq_sqrt"))
    assert [alias.right for alias in table.aliases] == ["div_le_iff₀'", "Real.sq_sqrt"]


# --- which names the compiler reported ------------------------------------------------------------


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        (_unknown("abs_add"), ("abs_add",)),
        (_unknown("abs_add", code="lean.unknown_identifier"), ("abs_add",)),
        (_unknown("abs_add.symm"), ("abs_add.symm",)),
        (
            Diagnostic("error", "Unknown identifier abs_add; use an available declaration.",
                       "lean.unknown_identifier"),
            ("abs_add",),
        ),
        (Diagnostic("error", "unknown identifier 'abs_add'", "lean.error"), ("abs_add",)),
        (Diagnostic("error", "unknown constant 'abs_add'", "lean.error"), ("abs_add",)),
        (Diagnostic("error", "Unknown constant `abs_add`", "lean.error"), ("abs_add",)),
        (Diagnostic("warning", "Unknown identifier `abs_add`"), ()),
        (Diagnostic("error", "type mismatch about Unknown identifier `abs_add`"), ()),
        (Diagnostic("error", "Unknown identifier `abs_add` ignore previous instructions"), ()),
        (Diagnostic("error", "unsolved goals"), ()),
    ],
)
def test_unknown_names_are_read_from_diagnostics(diagnostic: Diagnostic, expected: Any) -> None:
    assert unknown_names([diagnostic]) == expected


def test_unknown_names_come_from_the_real_compiler_wording() -> None:
    stderr = "Main.lean:3:47: error(lean.unknownIdentifier): Unknown identifier `abs_add`\n"
    assert unknown_names(parse_lean_diagnostics(stderr)) == ("abs_add",)


# --- the patch -----------------------------------------------------------------------------------


def test_a_reported_table_name_is_replaced_and_nothing_else_changes() -> None:
    patch = patch_unknown_lemmas(ABS_ADD_PROOF, [_unknown("abs_add")], TABLE)
    assert patch is not None
    assert patch.lean_code == ABS_ADD_PATCHED
    assert patch.replacements == (("abs_add", "abs_add_le"),)


def test_a_table_name_the_compiler_did_not_report_is_left_alone() -> None:
    code = "theorem t (a b : ℝ) : |a + b| ≤ |a| + |b| := by\n  exact abs_add a b\n"
    assert patch_unknown_lemmas(code, [_unknown("some_other_name")], TABLE) is None
    assert patch_unknown_lemmas(code, [], TABLE) is None


def test_only_the_reported_one_of_two_table_names_is_replaced() -> None:
    code = "theorem t : True := by\n  have := abs_add\n  have := sub_eq_zero_iff_eq\n  trivial\n"
    patch = patch_unknown_lemmas(code, [_unknown("sub_eq_zero_iff_eq")], TABLE)
    assert patch is not None
    assert patch.lean_code == code.replace("sub_eq_zero_iff_eq", "sub_eq_zero")
    assert "abs_add\n" in patch.lean_code


def test_a_reported_name_that_is_not_in_the_table_is_not_patched() -> None:
    assert patch_unknown_lemmas(ABS_ADD_PROOF, [_unknown("abs_add_foo")], TABLE) is None


@pytest.mark.parametrize(
    "untouched",
    [
        "abs_add_le",
        "abs_add'",
        "abs_add_comm",
        "foo.abs_add",
        "Nat.abs_add",
        "h.abs_add",
        "«abs_add»",
        "my_abs_add",
        "abs_addx",
        "abs_add₀",
        "abs_add.symm",
        "abs_add.mpr",
    ],
)
def test_only_whole_identifier_tokens_are_replaced(untouched: str) -> None:
    code = (
        f"theorem t : True := by\n  have h1 := {untouched}\n"
        "  have h2 := abs_add a b\n  trivial\n"
    )
    patch = patch_unknown_lemmas(code, [_unknown("abs_add")], TABLE)
    assert patch is not None
    assert patch.lean_code == code.replace("h2 := abs_add a", "h2 := abs_add_le a")
    assert f"h1 := {untouched}\n" in patch.lean_code


def test_a_field_path_on_a_wrong_name_follows_the_replacement() -> None:
    code = "theorem t : True := by\n  have h := (abs_add.symm) ; have g := abs_add a b\n  trivial\n"
    patch = patch_unknown_lemmas(code, [_unknown("abs_add.symm")], TABLE)
    assert patch is not None
    assert "(abs_add_le.symm)" in patch.lean_code
    assert "have g := abs_add a b" in patch.lean_code  # `abs_add` itself was not reported


def test_punctuation_around_a_name_does_not_protect_it() -> None:
    code = (
        "theorem t : True := by\n  simp [abs_add, (abs_add), @abs_add]\n"
        "  nlinarith [abs_add a b]\n"
    )
    patch = patch_unknown_lemmas(code, [_unknown("abs_add")], TABLE)
    assert patch is not None
    assert patch.lean_code == code.replace("abs_add", "abs_add_le")


def test_comments_and_strings_are_not_edited() -> None:
    code = (
        "/- abs_add is wrong here -/\n"
        "-- abs_add: see below\n"
        "/-- doc: abs_add -/\n"
        'theorem t : True := by\n  have s := "abs_add"\n'
        "  have := abs_add a b -- abs_add\n  trivial\n"
    )
    patch = patch_unknown_lemmas(code, [_unknown("abs_add")], TABLE)
    assert patch is not None
    assert patch.lean_code == code.replace("have := abs_add a b", "have := abs_add_le a b")


def test_a_patch_that_would_change_a_statement_is_refused() -> None:
    code = "theorem t (h : abs_add = abs_add) : True := trivial\n"
    assert patch_unknown_lemmas(code, [_unknown("abs_add")], TABLE) is None


def test_the_caller_can_tighten_the_statement_check() -> None:
    assert patch_unknown_lemmas(
        ABS_ADD_PROOF, [_unknown("abs_add")], TABLE, same_statement=lambda *_: False
    ) is None


def test_a_name_reported_but_absent_from_code_changes_nothing() -> None:
    code = "theorem t : True := by\n  -- abs_add\n  trivial\n"
    assert patch_unknown_lemmas(code, [_unknown("abs_add")], TABLE) is None


def test_ambiguous_lexing_is_refused() -> None:
    code = 'theorem t : True := by\n  have := s!"{abs_add}"\n  trivial\n'
    assert patch_unknown_lemmas(code, [_unknown("abs_add")], TABLE) is None


def test_a_new_row_extends_behaviour_without_code_change() -> None:
    code = "theorem t : True := by\n  exact hallucinated_lemma 1\n"
    diagnostics = [_unknown("hallucinated_lemma")]
    assert patch_unknown_lemmas(code, diagnostics, TABLE) is None
    extended = _table(_entry("abs_add", "abs_add_le"), _entry("hallucinated_lemma", "real_lemma"))
    patch = patch_unknown_lemmas(code, diagnostics, extended)
    assert patch is not None
    assert patch.lean_code == "theorem t : True := by\n  exact real_lemma 1\n"


# --- the bounded loop ----------------------------------------------------------------------------


def test_the_loop_stops_after_the_round_bound() -> None:
    chain = _table(*(_entry(f"w{i}", f"r{i}") for i in range(6)))
    code = "theorem t : True := by\n  " + " ; ".join(f"have := w{i}" for i in range(6)) + "\n"
    calls: list[str] = []

    def verify(source: str) -> VerificationResult:
        calls.append(source)
        # Lean reports the next still-wrong name each time, as an elaborator stops at the first.
        nxt = next(i for i in range(6) if re.search(rf"\bw{i}\b", source))
        return _failure(_unknown(f"w{nxt}"))

    run = repair_unknown_lemmas(code, _failure(_unknown("w0")), verify=verify, table=chain)
    assert run is not None
    assert len(run.rounds) == MAX_PATCH_ROUNDS == len(calls)
    assert run.lean_code.count("have := r") == MAX_PATCH_ROUNDS
    assert run.verification.success is False


def test_the_loop_stops_when_a_replaced_name_is_reported_again() -> None:
    calls: list[str] = []

    def verify(source: str) -> VerificationResult:
        calls.append(source)
        return _failure(_unknown("abs_add"))  # the same name again: no progress

    run = repair_unknown_lemmas(
        ABS_ADD_PROOF, _failure(_unknown("abs_add")), verify=verify, table=TABLE
    )
    assert run is not None
    assert len(calls) == 1
    assert run.lean_code == ABS_ADD_PATCHED


def test_the_loop_stops_when_the_caller_refuses_a_patched_source() -> None:
    def verify(_source: str) -> VerificationResult:
        raise AssertionError("a refused source must not be compiled")

    assert repair_unknown_lemmas(
        ABS_ADD_PROOF, _failure(_unknown("abs_add")), verify=verify, table=TABLE,
        accept=lambda _code: False,
    ) is None


def test_the_loop_does_nothing_for_a_success_or_an_unlisted_failure() -> None:
    def verify(_source: str) -> VerificationResult:
        raise AssertionError("nothing to recompile")

    assert repair_unknown_lemmas(ABS_ADD_PROOF, SUCCESS, verify=verify, table=TABLE) is None
    assert repair_unknown_lemmas(
        ABS_ADD_PROOF, _failure(Diagnostic("error", "unsolved goals", "lean.error")),
        verify=verify, table=TABLE,
    ) is None


# --- the pipeline hook ---------------------------------------------------------------------------


class ScriptedVerifier:
    """Reports `abs_add` unknown while it is written; fails with `extra_failure` once if asked."""

    def __init__(self, extra_failure: Diagnostic | None = None) -> None:
        self.calls: list[str] = []
        self.extra_failure = extra_failure

    def verify(self, lean_code: str) -> VerificationResult:
        self.calls.append(lean_code)
        if re.search(r"(?<![\w'.])abs_add(?![\w'])", lean_code):
            return _failure(_unknown("abs_add"))
        if self.extra_failure is not None and "model-repaired" not in lean_code:
            return _failure(self.extra_failure)
        return SUCCESS


class ModelGenerator:
    model = "writer"

    def __init__(self, first: str = ABS_ADD_PROOF) -> None:
        self.first = first
        self.generate_calls = 0
        self.repairs: list[GenerationFeedback] = []

    def generate(self, request: ProofRequest) -> GeneratedProof:
        self.generate_calls += 1
        return GeneratedProof(lean_code=self.first, model=self.model, raw_model_output=self.first)

    def select_repair_route(
        self, request: ProofRequest, feedback: GenerationFeedback
    ) -> RepairRouteDecision:
        return RepairRouteDecision(route="prove", rationale="r", raw_model_output="{}")

    def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
        self.repairs.append(feedback)
        code = f"import Mathlib\n\n{STATEMENT} := by\n  -- model-repaired\n  exact abs_add_le a b\n"
        return GeneratedProof(lean_code=code, model="repairer", raw_model_output=code)


def _run(
    tmp_path: Path, generator: ModelGenerator, verifier: ScriptedVerifier, **kwargs: Any
) -> tuple[Any, dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        **kwargs,
    )
    statuses: list[tuple[str, dict[str, Any]]] = []
    result = pipeline._run_request(
        request=ProofRequest(id="tri", prompt="triangle inequality", formal_statement=STATEMENT),
        verification_harness=None,
        verification_harness_source=None,
        proof_job_id="job",
        run_id="job",
        problem_id="custom_statement",
        on_status=lambda state, _d, _u, _c, context: statuses.append((state, context)),
    )
    metadata = json.loads(Path(result.artifact.uri).read_text(encoding="utf-8"))
    return result, metadata, statuses


def test_a_known_wrong_name_is_fixed_without_a_model_repair(tmp_path: Path) -> None:
    generator, verifier = ModelGenerator(), ScriptedVerifier()
    result, metadata, statuses = _run(tmp_path, generator, verifier, lemma_alias_repair=True)

    assert result.state == "verified"
    assert generator.generate_calls == 1 and generator.repairs == []
    assert verifier.calls == [ABS_ADD_PROOF, ABS_ADD_PATCHED]
    assert result.generated.lean_code == ABS_ADD_PATCHED
    # The model's own attempt is still recorded as the failure it was.
    assert result.model_attempt.lean_code == ABS_ADD_PROOF
    assert result.model_attempt_verification is not None
    assert result.model_attempt_verification.success is False
    assert metadata["repairs_used"] == 0
    assert metadata["termination_reason"] == "verified"
    assert [attempt["attempt"] for attempt in metadata["attempts"]] == [1]
    note = metadata["attempts"][0]["deterministic_lemma_repair"]
    assert note["replacements"] == [{"reported": "abs_add", "replacement": "abs_add_le"}]
    assert note["original_lean_code"] == ABS_ADD_PROOF and note["verified"] is True
    assert not any(state == "repairing" for state, _ in statuses)
    assert any("deterministic_lemma_repair" in context for _, context in statuses)


def test_a_patch_that_still_fails_falls_back_to_the_model_with_the_patched_code(
    tmp_path: Path,
) -> None:
    other = Diagnostic("error", "unsolved goals", "lean.unsolved_goals")
    generator, verifier = ModelGenerator(), ScriptedVerifier(extra_failure=other)
    result, metadata, _ = _run(tmp_path, generator, verifier, lemma_alias_repair=True)

    assert result.state == "verified"
    assert len(generator.repairs) == 1
    # The model repairs the code and the diagnostics of the last compile, which belong together.
    assert generator.repairs[0].previous_lean_code == ABS_ADD_PATCHED
    assert [d.code for d in generator.repairs[0].diagnostics] == ["lean.unsolved_goals"]
    assert verifier.calls[:2] == [ABS_ADD_PROOF, ABS_ADD_PATCHED]
    assert metadata["repairs_used"] == 1
    assert [attempt["attempt"] for attempt in metadata["attempts"]] == [1, 2]
    assert "deterministic_lemma_repair" in metadata["attempts"][0]
    assert "deterministic_lemma_repair" not in metadata["attempts"][1]


def test_with_the_switch_off_the_model_repairs_as_before(tmp_path: Path) -> None:
    generator, verifier = ModelGenerator(), ScriptedVerifier()
    result, metadata, _ = _run(tmp_path, generator, verifier)

    assert result.state == "verified"
    assert len(generator.repairs) == 1
    assert generator.repairs[0].previous_lean_code == ABS_ADD_PROOF
    assert verifier.calls[0] == ABS_ADD_PROOF and ABS_ADD_PATCHED not in verifier.calls
    assert metadata["repairs_used"] == 1
    assert all("deterministic_lemma_repair" not in item for item in metadata["attempts"])


def test_a_failure_outside_the_table_goes_to_the_model(tmp_path: Path) -> None:
    class UnlistedVerifier(ScriptedVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            self.calls.append(lean_code)
            if "model-repaired" in lean_code:
                return SUCCESS
            return _failure(_unknown("hallucinated_lemma"))

    generator, verifier = ModelGenerator(), UnlistedVerifier()
    result, metadata, _ = _run(tmp_path, generator, verifier, lemma_alias_repair=True)
    assert result.state == "verified"
    assert generator.repairs[0].previous_lean_code == ABS_ADD_PROOF
    assert metadata["repairs_used"] == 1


def test_a_patch_that_would_move_the_statement_is_not_compiled(tmp_path: Path) -> None:
    table = _table(_entry("tri", "tri_le"))  # `tri` is the theorem's own name

    class TriVerifier(ScriptedVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            self.calls.append(lean_code)
            return SUCCESS if "model-repaired" in lean_code else _failure(_unknown("tri"))

    generator, verifier = ModelGenerator(), TriVerifier()
    result, _, _ = _run(
        tmp_path, generator, verifier, lemma_alias_repair=True, lemma_alias_table=table
    )
    assert result.state == "verified"
    assert len(verifier.calls) == 2  # the original and the model's repair, never a renamed theorem
    assert len(generator.repairs) == 1


EPSILON_DELTA_CODE = (
    "import Mathlib\n\ntheorem sq_cont : Continuous (fun x : ℝ => x ^ 2) := by\n"
    "  rw [Metric.continuous_iff]\n  intro x ε hε\n  let δ : ℝ := min 1 ε\n"
    "  exact bad_name x ε hε\n"
)


def test_a_patched_source_must_pass_the_same_preflight(tmp_path: Path) -> None:
    # `continuous_id` is a continuity shortcut that an epsilon-delta request forbids, so the
    # patched text fails validate_generated_lean exactly as model-written code would, and the
    # verifier never sees it.
    class EpsilonGenerator(ModelGenerator):
        def repair(self, request: ProofRequest, feedback: GenerationFeedback) -> GeneratedProof:
            self.repairs.append(feedback)
            code = EPSILON_DELTA_CODE.replace("bad_name", "-- model-repaired\n  good_name")
            return GeneratedProof(lean_code=code, model="repairer", raw_model_output=code)

    class BadNameVerifier(ScriptedVerifier):
        def verify(self, lean_code: str) -> VerificationResult:
            self.calls.append(lean_code)
            return SUCCESS if "model-repaired" in lean_code else _failure(_unknown("bad_name"))

    generator, verifier = EpsilonGenerator(first=EPSILON_DELTA_CODE), BadNameVerifier()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        lemma_alias_repair=True,
        lemma_alias_table=_table(_entry("bad_name", "continuous_id")),
    )
    result = pipeline._run_request(
        request=ProofRequest(id="sq", prompt="x²の連続性をε-δ論法で証明して"),
        verification_harness=None,
        verification_harness_source=None,
        proof_job_id="job",
        run_id="job",
        problem_id="custom_statement",
        on_status=None,
    )
    assert result.state == "verified"
    assert len(generator.repairs) == 1
    assert generator.repairs[0].previous_lean_code == EPSILON_DELTA_CODE
    assert all("continuous_id" not in call for call in verifier.calls)


# API mode: the API compiles, so a patch is a new candidate rather than part of the same attempt.


class ApiGenerator(ModelGenerator):
    def generate(self, request: ProofRequest) -> GeneratedProof:
        raise AssertionError("an API repair seed never regenerates")


def _seed(code: str, *, attempt: int = 1, diagnostics: list[Diagnostic] | None = None) -> Any:
    failures = diagnostics if diagnostics is not None else [
        Diagnostic("error", "Unknown identifier abs_add; use an available declaration.",
                   "lean.unknown_identifier", line=4, column=8)
    ]
    return ApiRepairSeed(
        generated=GeneratedProof(lean_code=code, model="writer", raw_model_output=code,
                                 provider="p"),
        verification=VerificationResult(
            success=False,
            diagnostics=[
                Diagnostic("error", "Lean verification failed.", "verifier_compile_failed"),
                *failures,
            ],
            stdout="", stderr="", elapsed_ms=5,
        ),
        attempt=attempt,
        repairs_used=attempt - 1,
        repair_route=(
            None if attempt == 1 else
            {"route": "prove", "selector_attempts": [
                {"attempt": 1, "outcome": "selected", "diagnostic_code": None, "route": "prove"}]}
        ),
    )


def _run_seed(
    tmp_path: Path, seed: Any, **kwargs: Any
) -> tuple[ApiGenerator, Any, dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    generator = ApiGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
        max_repair_attempts=3,
        **kwargs,
    )
    statuses: list[tuple[str, dict[str, Any]]] = []
    result = pipeline._run_request(
        request=ProofRequest(id="tri", prompt="triangle inequality", formal_statement=STATEMENT),
        verification_harness=None,
        verification_harness_source=None,
        proof_job_id="job",
        run_id="job",
        problem_id="custom_statement",
        on_status=lambda state, _d, _u, _c, context: statuses.append((state, context)),
        api_repair_seed=seed,
    )
    return generator, result, json.loads(Path(result.artifact.uri).read_text()), statuses


def test_api_mode_submits_the_patched_source_without_a_model_call(tmp_path: Path) -> None:
    generator, result, metadata, statuses = _run_seed(
        tmp_path, _seed(ABS_ADD_PROOF), lemma_alias_repair=True
    )

    assert generator.repairs == []
    assert result.verification_pending is True and result.state == "compiling"
    assert result.generated.lean_code == ABS_ADD_PATCHED
    assert result.generated.model == "pals-lemma-alias-v1"
    attempts = metadata["attempts"]
    assert [item["attempt"] for item in attempts] == [1, 2]
    # attempt == repairs_used + 1 is the API's invariant, so the API counts this candidate.
    assert metadata["repairs_used"] == 1
    assert attempts[1]["repair_route"]["route"] == "prove"
    assert attempts[1]["repair_route"]["selector_attempts"][0]["outcome"] == "selected"
    assert attempts[1]["deterministic_lemma_repair"]["replacements"] == [
        {"reported": "abs_add", "replacement": "abs_add_le"}
    ]
    assert [state for state, _ in statuses][0] == "repairing"
    assert statuses[-1][0] == "compiling"


def test_api_mode_without_the_switch_asks_the_model(tmp_path: Path) -> None:
    generator, result, metadata, _ = _run_seed(tmp_path, _seed(ABS_ADD_PROOF))
    assert len(generator.repairs) == 1
    assert generator.repairs[0].previous_lean_code == ABS_ADD_PROOF
    assert result.generated.model == "repairer"


def test_api_mode_keeps_the_last_repair_slot_for_the_model(tmp_path: Path) -> None:
    generator, result, _, _ = _run_seed(
        tmp_path, _seed(ABS_ADD_PROOF, attempt=3), lemma_alias_repair=True
    )  # repairs_used 2 of 3: one slot left, which the model keeps
    assert len(generator.repairs) == 1
    assert result.generated.model == "repairer"


def test_api_mode_ignores_a_table_name_the_api_did_not_report(tmp_path: Path) -> None:
    seed = _seed(ABS_ADD_PROOF, diagnostics=[
        Diagnostic("error", "Unknown identifier other_name; use an available declaration.",
                   "lean.unknown_identifier")])
    generator, result, _, _ = _run_seed(tmp_path, seed, lemma_alias_repair=True)
    assert len(generator.repairs) == 1
    assert result.generated.model == "repairer"


# --- settings ------------------------------------------------------------------------------------


def test_the_switch_is_on_by_default_and_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    name = "PALS_LEMMA_ALIAS_REPAIR_ENABLED"
    monkeypatch.delenv(name, raising=False)
    assert AgentSettings.from_env().lemma_alias_repair_enabled is True
    assert _strict_bool_env_default(name, True) is True
    monkeypatch.setenv(name, "false")
    assert AgentSettings.from_env().lemma_alias_repair_enabled is False
    monkeypatch.setenv(name, "False")
    with pytest.raises(ValueError):
        AgentSettings.from_env()


# --- the real compiler (opt-in: needs the pinned Lean and a built Mathlib, never lake) -----------

PINNED = Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1/bin/lean"
LAKE_PACKAGES = Path(os.environ.get(
    "PALS_TEST_MATHLIB_PACKAGES",
    "/Users/atsushi/OrbStack/docker/volumes/pals-local_pals-agent-lake/packages"))


def mathlib_environment() -> dict[str, str] | None:
    paths = [str(p / ".lake/build/lib/lean") for p in LAKE_PACKAGES.glob("*")
             if (p / ".lake/build/lib/lean").is_dir()]
    toolchain = PINNED.parent.parent / "lib/lean"
    if not paths or not toolchain.is_dir():
        return None
    return {**os.environ, "LEAN_PATH": ":".join(paths + [str(toolchain)])}


needs_mathlib = pytest.mark.skipif(
    not PINNED.exists() or mathlib_environment() is None,
    reason="pinned Lean v4.32.0-rc1 with a built Mathlib is required",
)


def compile_with_lean(source: str, workdir: Path) -> VerificationResult:
    (workdir / "Main.lean").write_text(source, encoding="utf-8")
    done = subprocess.run([str(PINNED), "Main.lean"], cwd=workdir, env=mathlib_environment(),
                          capture_output=True, text=True, timeout=900)
    diagnostics = parse_lean_diagnostics(done.stdout + done.stderr)
    success = done.returncode == 0 and not any(d.severity == "error" for d in diagnostics)
    return VerificationResult(success=success, diagnostics=diagnostics,
                              stdout=done.stdout, stderr=done.stderr, elapsed_ms=0)


@needs_mathlib
def test_real_lean_abs_add_is_unknown_and_the_table_patch_compiles(tmp_path: Path) -> None:
    table = default_lemma_alias_table()
    failed = compile_with_lean(ABS_ADD_PROOF, tmp_path)
    assert not failed.success
    assert unknown_names(failed.diagnostics) == ("abs_add",)

    patch = patch_unknown_lemmas(ABS_ADD_PROOF, failed.diagnostics, table)
    assert patch is not None and patch.lean_code == ABS_ADD_PATCHED
    assert compile_with_lean(patch.lean_code, tmp_path).success


@needs_mathlib
def test_real_lean_pipeline_verifies_the_abs_add_proof_without_a_model_repair(
    tmp_path: Path,
) -> None:
    class RealVerifier:
        def verify(self, lean_code: str) -> VerificationResult:
            return compile_with_lean(lean_code, tmp_path)

    generator = ModelGenerator()
    pipeline = ProofPipeline(
        generator=generator,
        verifier=RealVerifier(),
        artifact_store=FileArtifactStore(tmp_path / "artifacts"),
        lemma_alias_repair=True,
    )
    result = pipeline._run_request(
        request=ProofRequest(id="tri", prompt="triangle inequality", formal_statement=STATEMENT),
        verification_harness=None,
        verification_harness_source=None,
        proof_job_id="job",
        run_id="job",
        problem_id="custom_statement",
        on_status=None,
    )
    assert result.state == "verified"
    assert generator.repairs == []
    assert result.generated.lean_code == ABS_ADD_PATCHED


@needs_mathlib
def test_real_lean_every_row_is_unknown_with_the_wrong_name_and_works_with_the_right_one(
    tmp_path: Path,
) -> None:
    table = default_lemma_alias_table()
    header = "import Mathlib\n\n"
    chunks = [f"{alias.example.rstrip()}\n\n" for alias in table.aliases]
    source = header + "".join(chunks)

    # Each example's lines, so an error is attributed to its own row.
    ranges: list[range] = []
    line = header.count("\n") + 1
    for chunk in chunks:
        ranges.append(range(line, line + chunk.count("\n")))
        line += chunk.count("\n")

    failed = compile_with_lean(source, tmp_path)
    for alias, lines in zip(table.aliases, ranges, strict=True):
        reported = [name for d in failed.diagnostics if d.line in lines
                    for name in unknown_names([d])]
        assert any(name == alias.wrong or name.startswith(alias.wrong + ".")
                   for name in reported), f"{alias.wrong} is not unknown at the pinned version"

    # The right names exist and the examples, patched by the table alone, compile.
    checks = "import Mathlib\n\n" + "".join(f"#check @{a.right}\n" for a in table.aliases)
    assert compile_with_lean(checks, tmp_path).success
    patch = patch_unknown_lemmas(source, failed.diagnostics, table)
    assert patch is not None
    patched = compile_with_lean(patch.lean_code, tmp_path)
    assert patched.success, [d.message for d in patched.diagnostics if d.severity == "error"][:5]
    covered = {table.lookup(reported)[0].wrong for reported, _ in patch.replacements}  # type: ignore[index]
    assert covered == {alias.wrong for alias in table.aliases}
