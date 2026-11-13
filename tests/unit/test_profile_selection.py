from dataclasses import replace
from pathlib import Path

import pytest

from pals_agent.artifacts import FileArtifactStore
from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.lean_profiles import (
    DEFAULT_PROFILE_NAME,
    LibraryProfileNotEnabled,
    ProfileRoutedVerifier,
)
from pals_agent.pipeline import ProofPipeline
from pals_agent.profile_selection import (
    FRONTIER_DEFS_PROFILE,
    FRONTIER_PROOF_PROFILE,
    select_library_profile,
)
from tests.unit.test_pipeline import ContinuousGenerator, FakeVerifier


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Show that if f is an affine morphism and F is quasi-coherent, the higher direct "
            "images R^n f_* F vanish for n > 0.",
            FRONTIER_PROOF_PROFILE,
        ),
        ("Compute the sheaf cohomology of the projective line.", FRONTIER_PROOF_PROFILE),
        ("アフィン射の高次順像は消える", FRONTIER_PROOF_PROFILE),
        (
            "Show that the Picard group of Spec R is trivial for a local ring R.",
            FRONTIER_DEFS_PROFILE,
        ),
        ("Show that an ample line bundle has a power that is very ample.", FRONTIER_DEFS_PROFILE),
        ("Show that Spec R is quasi-compact.", None),
        ("Show that a closed immersion is separated.", None),
        ("Show that a numerical scheme for the heat equation is stable.", None),
        ("", None),
    ],
)
def test_selection(text: str, expected: str | None) -> None:
    assert select_library_profile(text) == expected


def test_pipeline_routes_only_when_enabled_and_never_falls_back(tmp_path: Path) -> None:
    default, frontier = FakeVerifier(), FakeVerifier()
    pipeline = ProofPipeline(
        generator=ContinuousGenerator(),
        verifier=default,
        artifact_store=FileArtifactStore(tmp_path),
        draft_catalog=SeedDraftCatalog(),
        profile_verifiers=ProfileRoutedVerifier(
            {DEFAULT_PROFILE_NAME: default, FRONTIER_PROOF_PROFILE: frontier}
        ),
        route_library_profile=True,
    )
    cohomology = "Show that the higher direct images R^n f_* F of an affine morphism vanish."
    # A needed and served profile selects its own verifier (the pipeline is rebound to it).
    assert pipeline.for_library_profile(select_library_profile(cohomology)).verifier is frontier
    # Picard needs a profile that is not served: refused, never answered by the default library.
    with pytest.raises(LibraryProfileNotEnabled):
        pipeline.run_statement(
            statement="Show that the Picard group of Spec R is trivial for a local ring R.",
            proof_job_id="job-1",
        )
    # Disabled routing (the default) never consults the text.
    off = replace(pipeline, route_library_profile=False)
    assert off.route_library_profile is False
