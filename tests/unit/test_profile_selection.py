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
        (
            "Show that an ample line bundle on a scheme has a power that is very ample.",
            FRONTIER_DEFS_PROFILE,
        ),
        ("Show that Spec R is quasi-compact.", None),
        ("Show that a closed immersion is separated.", None),
        ("Show that a numerical scheme for the heat equation is stable.", None),
        ("", None),
        ("Show that R^i f_* F = 0 for an affine morphism f of schemes and quasi-coherent F.",
         FRONTIER_PROOF_PROFILE),
        ("Show that a line bundle on a circle is trivial.", None),
        ("Compute the cohomology of groups H^n(G, M).", None),
        ("Show that an acyclic graph has a leaf.", None),
        ("Show that a sample space is an example of a probability space.", None),
        ("Show that a very ample line bundle on a scheme X embeds X in projective space.",
         FRONTIER_DEFS_PROFILE),
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


def test_a_routed_pipeline_verifies_with_the_selected_profile(tmp_path: Path) -> None:
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
    bound = pipeline.for_library_profile(FRONTIER_PROOF_PROFILE)
    assert bound.route_library_profile is False and bound.profile_verifiers is None
    statement = "Show that the sheaf cohomology of a flasque sheaf vanishes in positive degrees."
    # Routed by the text, and the same when the profile is named explicitly: no second routing.
    for job_id, kwargs in (("j1", {}), ("j2", {"library_profile": FRONTIER_PROOF_PROFILE})):
        pipeline.run_statement(statement=statement, proof_job_id=job_id, **kwargs)
    assert frontier.calls and not default.calls
