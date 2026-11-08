"""Per-request library-profile routing: which verifier a request is checked by."""

import json
from pathlib import Path

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.benchmarks import BENCHMARK_PROBLEMS
from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.lean_profiles import (
    DEFAULT_PROFILE_NAME,
    FRONTIER_FLAG,
    LibraryProfileMismatch,
    LibraryProfileNotEnabled,
    ProfileRoutedVerifier,
    UnknownLibraryProfile,
    build_profile_verifiers,
)
from pals_agent.pipeline import ProofPipeline
from tests.unit.test_pipeline import ContinuousGenerator, FakeVerifier

FRONTIER = "stacks-frontier-4.35"
WORKSPACE = Path(__file__).resolve().parents[2] / "lean-workspaces" / "stacks-4.35"


def _pipeline(tmp_path: Path) -> tuple[ProofPipeline, FakeVerifier, FakeVerifier]:
    default, frontier = FakeVerifier(), FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=default,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=SeedDraftCatalog(),
        profile_verifiers=ProfileRoutedVerifier(
            {DEFAULT_PROFILE_NAME: default, FRONTIER: frontier}
        ),
    )
    return pipeline, default, frontier


def test_no_profile_is_the_unchanged_pipeline(tmp_path: Path) -> None:
    pipeline, default, frontier = _pipeline(tmp_path)

    assert pipeline.for_library_profile(None) is pipeline
    result = pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0])

    assert result.state == "verified"
    assert default.calls and not frontier.calls


def test_a_named_profile_is_verified_only_by_its_own_verifier(tmp_path: Path) -> None:
    pipeline, default, frontier = _pipeline(tmp_path)

    result = pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], library_profile=FRONTIER)

    assert result.state == "verified"
    assert frontier.calls and not default.calls


def test_the_default_profile_can_be_named_explicitly(tmp_path: Path) -> None:
    pipeline, default, frontier = _pipeline(tmp_path)

    pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], library_profile=DEFAULT_PROFILE_NAME)

    assert default.calls and not frontier.calls


def test_an_unserved_profile_is_refused_not_answered_by_the_default(tmp_path: Path) -> None:
    default = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=default,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=SeedDraftCatalog(),
        profile_verifiers=ProfileRoutedVerifier({DEFAULT_PROFILE_NAME: default}),
    )

    with pytest.raises(LibraryProfileNotEnabled):
        pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], library_profile=FRONTIER)
    assert not default.calls


def test_an_unknown_profile_name_is_rejected(tmp_path: Path) -> None:
    pipeline, default, frontier = _pipeline(tmp_path)

    with pytest.raises(UnknownLibraryProfile):
        pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], library_profile="stacks-9.99")
    assert not default.calls and not frontier.calls


def test_a_pipeline_without_a_router_refuses_any_named_profile(tmp_path: Path) -> None:
    verifier = FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=verifier,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=SeedDraftCatalog(),
    )

    with pytest.raises(LibraryProfileNotEnabled):
        pipeline.run_problem(problem=BENCHMARK_PROBLEMS[0], library_profile=DEFAULT_PROFILE_NAME)
    assert not verifier.calls


def test_api_reconcile_mode_cannot_route_profiles_here(tmp_path: Path) -> None:
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=None,
        artifact_store=FileArtifactStore(tmp_path),
        verification_mode="api_reconcile",
        profile_verifiers=ProfileRoutedVerifier({DEFAULT_PROFILE_NAME: FakeVerifier()}),
    )

    with pytest.raises(LibraryProfileNotEnabled):
        pipeline.for_library_profile(DEFAULT_PROFILE_NAME)


def test_the_router_always_serves_the_default_profile() -> None:
    with pytest.raises(ValueError, match="default profile"):
        ProfileRoutedVerifier({FRONTIER: FakeVerifier()})
    with pytest.raises(UnknownLibraryProfile):
        ProfileRoutedVerifier({DEFAULT_PROFILE_NAME: FakeVerifier(), "nope-1.0": FakeVerifier()})


@pytest.mark.parametrize("value", [None, "", "1", "True", "TRUE", "yes", "false"])
def test_frontier_is_not_served_unless_the_flag_is_exactly_true(value: str | None) -> None:
    environ = {} if value is None else {FRONTIER_FLAG: value}

    router = build_profile_verifiers(
        default_verifier=FakeVerifier(), workspaces={FRONTIER: WORKSPACE}, environ=environ
    )

    with pytest.raises(LibraryProfileNotEnabled):
        router.verifier_for(FRONTIER)
    assert router.verifier_for(None) is router.verifiers[DEFAULT_PROFILE_NAME]


def test_frontier_is_served_with_its_profile_when_the_flag_is_true() -> None:
    router = build_profile_verifiers(
        default_verifier=FakeVerifier(),
        workspaces={FRONTIER: WORKSPACE},
        environ={FRONTIER_FLAG: "true"},
    )

    verifier = router.verifier_for(FRONTIER)

    assert verifier.library_profile.name == FRONTIER
    assert verifier.project_dir == WORKSPACE


@pytest.mark.parametrize("revision", ["0" * 40, None])
def test_a_served_profile_must_sit_on_its_pinned_workspace(
    tmp_path: Path, revision: str | None
) -> None:
    (tmp_path / "lean-toolchain").write_text("leanprover/lean4:v4.35.0")
    manifest = json.loads((WORKSPACE / "lake-manifest.json").read_text())
    for package in manifest["packages"]:
        if package["name"] == "Stacks":  # pin names are lower-case
            package["rev"] = revision
    (tmp_path / "lake-manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(LibraryProfileMismatch):
        build_profile_verifiers(
            default_verifier=FakeVerifier(),
            workspaces={FRONTIER: tmp_path},
            environ={FRONTIER_FLAG: "true"},
        )


def test_the_default_verifier_is_never_rebuilt_from_a_workspace_map() -> None:
    with pytest.raises(ValueError, match="default"):
        build_profile_verifiers(
            default_verifier=FakeVerifier(),
            workspaces={DEFAULT_PROFILE_NAME: WORKSPACE},
            environ={},
        )
