"""``stacks-frontier-defs-4.35``: statements may use unreviewed Frontier definitions, in the open.

No Lean runs here. The profile never hides the dependency: the audit records which Frontier
constants a statement reaches, which library roots the proof uses and which Frontier definitions
resemble a reviewed one; a result carries a trust level. Everything else stays forbidden.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import pals_agent.lean as lean_module
from pals_agent.lean import LeanVerifier
from pals_agent.lean_audit import (
    FRONTIER_DUPLICATE_DIAGNOSTIC,
    TRUST_LEVEL_DIAGNOSTIC,
    UNTRUSTED_STATEMENT_LIBRARY,
    AuditReport,
    audit_diagnostics,
    parse_audit_report,
    trust_level,
)
from pals_agent.lean_profiles import (
    FRONTIER_FLAG,
    FRONTIER_STATEMENTS_FLAG,
    LibraryProfile,
    LibraryProfileNotEnabled,
    build_profile_verifiers,
    known_profile_names,
    resolve_profile,
)
from pals_agent.private_recipe_selection import ToolchainFingerprintV1
from tests.unit.test_lean_trusted_audit import _Compiler, _report
from tests.unit.test_pipeline import FakeVerifier

NAME = "stacks-frontier-defs-4.35"
ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "lean-workspaces" / "stacks-4.35"
NONCE = "ab" * 32
_FRONTIER_MODULE = "StacksFrontier.AlgebraicGeometry.Etale.FiniteEtaleIrreducibleCover0551b"
_FRONTIER_DEF = "AlgebraicGeometry.IsAffineOpen.residueFieldIso"


def _parse(*lines: str) -> AuditReport:
    report = parse_audit_report(_report("theorem t", "axiom propext", *lines, nonce=NONCE), NONCE)
    assert report is not None
    return report


def test_profile_is_a_distinct_opt_in_on_the_same_pins() -> None:
    profile = resolve_profile(NAME)
    existing = resolve_profile("stacks-frontier-4.35")

    assert NAME in known_profile_names()
    assert profile.requires_flag == FRONTIER_STATEMENTS_FLAG != FRONTIER_FLAG
    assert (profile.workspace, profile.pins, profile.lean_version) == (
        existing.workspace,
        existing.pins,
        existing.lean_version,
    )
    assert profile.import_roots == ("Mathlib", "StacksCore", "StacksFrontier")
    assert profile.statement_recorded_roots == ("StacksFrontier",)
    assert "StacksFrontier" not in (profile.statement_trusted_roots or ())
    assert profile.fingerprint_name == NAME
    profile.validate_workspace(WORKSPACE)
    # The earlier profiles keep rejecting, and do not record.
    assert existing.statement_recorded_roots is None
    assert "frontier_statement" not in existing.audit_source
    assert "frontier_statement" not in resolve_profile("stacks-4.35").audit_source


def test_profile_has_its_own_recipe_digest() -> None:
    def fingerprint(name: str) -> str:
        return ToolchainFingerprintV1(
            lean_version="leanprover/lean4:v4.35.0",
            lake_manifest_sha256="b" * 64,
            verifier_sha256="a" * 64,
            materializer_version="pals.recipe-materializer.v1",
            library_profile=name,
        ).sha256

    assert len({fingerprint(n) for n in ("stacks-4.35", "stacks-frontier-4.35", NAME)}) == 3


def test_audit_program_records_instead_of_rejecting_and_still_replays() -> None:
    audit = resolve_profile(NAME).audit_source

    assert 'recordedStatementRoots : List String := ["StacksFrontier"]' in audit
    for line in ("statement_root", "frontier_statement", "proof_root", "frontier_duplicate"):
        assert line in audit
    assert audit.count("trust_recorded") == 1
    assert "env.replay" in audit  # the kernel check is the unchanged default program
    # Only an unreviewed root OUTSIDE the recorded ones is still reported as untrusted.
    assert "else if !trustedStatementRoots.contains root.toString" in audit
    assert audit.index("def trustedStatementRoots") < audit.index("unsafe def main")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"statement_trusted_roots": None},  # nothing to compare the recorded roots with
        {"statement_recorded_roots": ()},
        {"statement_recorded_roots": ("Mathlib",)},  # trusted and recorded at once
        {"statement_recorded_roots": ("bad root",)},
    ],
)
def test_recorded_roots_must_be_well_formed_and_disjoint_from_trusted_ones(
    kwargs: dict[str, object],
) -> None:
    base: dict[str, object] = {
        "name": "x-1.0",
        "lean_version": "leanprover/lean4:v4.35.0",
        "workspace": "w",
        "pins": (),
        "silence_audit_deprecations": True,
        "statement_trusted_roots": ("Mathlib",),
        "statement_recorded_roots": ("StacksFrontier",),
    }
    with pytest.raises(ValueError):
        LibraryProfile(**{**base, **kwargs})  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, "", "1", "True", "yes", "false"])
def test_profile_is_served_only_when_its_own_flag_is_exactly_true(value: str | None) -> None:
    # The proof-side flag does not open it, nor does a near-miss of its own.
    for environ in (
        {FRONTIER_FLAG: "true"},
        {} if value is None else {FRONTIER_STATEMENTS_FLAG: value},
    ):
        router = build_profile_verifiers(
            default_verifier=FakeVerifier(), workspaces={NAME: WORKSPACE}, environ=environ
        )
        with pytest.raises(LibraryProfileNotEnabled):
            router.verifier_for(NAME)


def test_profile_is_served_with_its_flag_and_both_flags_are_independent() -> None:
    router = build_profile_verifiers(
        default_verifier=FakeVerifier(),
        workspaces={NAME: WORKSPACE, "stacks-frontier-4.35": WORKSPACE},
        environ={FRONTIER_STATEMENTS_FLAG: "true"},
    )

    assert router.verifier_for(NAME).library_profile.name == NAME
    with pytest.raises(LibraryProfileNotEnabled):
        router.verifier_for("stacks-frontier-4.35")


@pytest.mark.parametrize(
    ("source", "allowed"),
    [
        (f"import {_FRONTIER_MODULE}\n", True),
        ("import Mathlib\nimport StacksCore\n", True),
        ("import Stacks\n", False),
        ("import Lean\n", False),
        ("import Batteries\n", False),
    ],
)
def test_import_allow_list(source: str, allowed: bool) -> None:
    assert (resolve_profile(NAME).import_violation(source) is None) is allowed


# --- the audit report -------------------------------------------------------------------------


def test_report_parses_the_recorded_lines() -> None:
    report = _parse(
        "trust_recorded",
        "statement_root t Mathlib",
        "statement_root t StacksFrontier",
        f"frontier_statement t {_FRONTIER_DEF} {_FRONTIER_MODULE}",
        "proof_root t StacksFrontier",
        f"frontier_duplicate {_FRONTIER_DEF} AlgebraicGeometry.Scheme.Spec.residueFieldIso "
        "same_name",
        "bound t",
    )

    assert report.trust_recorded is True
    assert report.frontier_statements == (f"t {_FRONTIER_DEF} {_FRONTIER_MODULE}",)
    assert report.frontier_duplicates[0].endswith("same_name")
    assert trust_level(report) == "frontier_statement"


@pytest.mark.parametrize(
    ("lines", "level"),
    [
        (["statement_root t Init", "statement_root t Mathlib", "proof_root t Mathlib"], "mathlib"),
        (["statement_root t Mathlib", "proof_root t StacksCore"], "core"),
        (["statement_root t StacksCore", "proof_root t Mathlib"], "core"),
        (["statement_root t Mathlib", "proof_root t StacksFrontier"], "frontier_proof"),
        (
            [
                "statement_root t StacksFrontier",
                f"frontier_statement t {_FRONTIER_DEF} {_FRONTIER_MODULE}",
            ],
            "frontier_statement",
        ),
        # A statement-side Frontier use outranks everything else, even with a Core proof.
        (["statement_root t StacksFrontier", "proof_root t StacksCore"], "frontier_statement"),
    ],
)
def test_trust_level_is_the_weakest_claim_that_applies(lines: list[str], level: str) -> None:
    report = _parse("trust_recorded", *lines, "bound t")

    assert trust_level(report) == level
    diagnostics = audit_diagnostics(report, ("t",))
    assert [d.code for d in diagnostics] == [TRUST_LEVEL_DIAGNOSTIC]
    assert diagnostics[0].metadata is not None and diagnostics[0].metadata["trust_level"] == level
    assert diagnostics[0].severity == ("warning" if level.startswith("frontier") else "info")
    assert "error" not in {d.severity for d in diagnostics}


def test_frontier_statement_diagnostic_says_it_is_unreviewed_and_lists_what_it_reached() -> None:
    report = _parse(
        "trust_recorded",
        "statement_root t StacksFrontier",
        f"frontier_statement t {_FRONTIER_DEF} {_FRONTIER_MODULE}",
        "bound t",
    )

    diagnostic = audit_diagnostics(report, ("t",))[0]

    assert "Frontier (human-unreviewed)" in diagnostic.message
    assert _FRONTIER_DEF in diagnostic.message
    assert diagnostic.metadata is not None
    assert diagnostic.metadata["frontier_statement_constants"] == [_FRONTIER_DEF]
    assert diagnostic.metadata["frontier_modules"] == [_FRONTIER_MODULE]


def test_a_duplicate_is_recorded_and_never_rejects() -> None:
    report = _parse(
        "trust_recorded",
        "statement_root t StacksFrontier",
        f"frontier_statement t {_FRONTIER_DEF} {_FRONTIER_MODULE}",
        f"frontier_duplicate {_FRONTIER_DEF} Mathlib.Foo.bar same_value",
        "bound t",
    )

    diagnostics = audit_diagnostics(report, ("t",))

    assert [d.code for d in diagnostics] == [TRUST_LEVEL_DIAGNOSTIC, FRONTIER_DUPLICATE_DIAGNOSTIC]
    assert diagnostics[1].severity == "warning"
    assert diagnostics[1].metadata == {
        "duplicates": [
            {"frontier": _FRONTIER_DEF, "other": "Mathlib.Foo.bar", "reason": "same_value"}
        ]
    }


def test_a_constant_from_another_unreviewed_root_is_still_rejected() -> None:
    report = _parse(
        "trust_recorded",
        "statement_root t SomethingElse",
        "untrusted_statement t Foo.bar SomethingElse.Mod",
        "bound t",
    )

    diagnostics = audit_diagnostics(report, ("t",))

    assert [d.code for d in diagnostics] == [UNTRUSTED_STATEMENT_LIBRARY]


def test_a_proof_whose_library_use_could_not_be_traced_fails_closed() -> None:
    report = _parse(
        "trust_recorded", "statement_root t Mathlib", "proof_root t exhausted", "bound t"
    )

    diagnostics = audit_diagnostics(report, ("t",))

    assert [d.code for d in diagnostics] == ["lean.trusted_audit_failed"]


def test_axioms_and_missing_statement_binding_still_fail_with_recording_on() -> None:
    nonce_report = parse_audit_report(
        _report(
            "theorem t",
            "axiom Lean.ofReduceBool",
            "axiom sorryAx",
            "trust_recorded",
            "statement_root t Mathlib",
            "unbound t",
            nonce=NONCE,
        ),
        NONCE,
    )
    assert nonce_report is not None

    codes = [d.code for d in audit_diagnostics(nonce_report, ("t",))]

    assert codes == ["lean.disallowed_axiom", "lean.statement_mismatch"]


def test_a_report_without_recording_is_unchanged_and_unknown_lines_stay_malformed() -> None:
    plain = parse_audit_report(_report("theorem t", "bound t", nonce=NONCE), NONCE)
    assert plain is not None and plain.trust_recorded is False
    assert audit_diagnostics(plain, ("t",)) == []
    assert trust_level(plain) is None
    assert parse_audit_report(_report("theorem t", "trust recorded", nonce=NONCE), NONCE) is None
    bad = _report("theorem t", "proof_root_x t Init", nonce=NONCE)
    assert parse_audit_report(bad, NONCE) is None


# --- the verifier -----------------------------------------------------------------------------


def test_a_verified_proof_keeps_the_trust_diagnostics_and_stays_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stdout = _report(
        "theorem t",
        "axiom propext",
        "trust_recorded",
        "statement_root t StacksFrontier",
        f"frontier_statement t {_FRONTIER_DEF} {_FRONTIER_MODULE}",
        "bound t",
        nonce="{nonce}",
    )
    fake = _Compiler()
    monkeypatch.setattr("pals_agent.lean.shutil.which", lambda binary, **_kw: f"/usr/bin/{binary}")
    monkeypatch.setattr(lean_module, "_run_limited_process", _NonceEcho(fake, stdout))
    verifier = LeanVerifier(
        project_dir=WORKSPACE, library_profile=resolve_profile(NAME), scratch_dir=tmp_path
    )

    result = verifier.verify(f"import {_FRONTIER_MODULE}\ntheorem t : True := trivial")

    assert result.success is True
    codes = [d.code for d in result.diagnostics]
    assert codes[0] == "lean.verified"  # the verdict stays first
    assert TRUST_LEVEL_DIAGNOSTIC in codes
    trust = next(d for d in result.diagnostics if d.code == TRUST_LEVEL_DIAGNOSTIC)
    assert trust.to_api()["metadata"]["trust_level"] == "frontier_statement"


class _NonceEcho:
    """The fake compiler, with the audit report closed by the nonce of this request."""

    def __init__(self, fake: _Compiler, template: str) -> None:
        self.fake, self.template = fake, template

    def __call__(self, command: list[str], **kwargs: object) -> lean_module._ProcessResult:
        if "--run" in command:
            nonce = command[command.index("--run") + 2]
            self.fake.audit_stdout = self.template.replace("{nonce}", nonce)
        return self.fake(command, **kwargs)
