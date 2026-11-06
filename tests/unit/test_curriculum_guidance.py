from dataclasses import FrozenInstanceError

import pytest

from pals_agent.curriculum_guidance import (
    CURRICULUM_GUIDANCE,
    CURRICULUM_GUIDANCE_VERSION,
    curriculum_guidance_prompt,
)


def test_profiles_are_versioned_scoped_and_immutable():
    assert {profile.id for profile in CURRICULUM_GUIDANCE} == {
        "JP-MEXT", "GB-ENG-NC", "US-CCSS"
    }
    assert isinstance(CURRICULUM_GUIDANCE, tuple)
    for profile in CURRICULUM_GUIDANCE:
        assert profile.revision
        assert profile.scope
        assert profile.sources
        assert isinstance(profile.sources, tuple)
        assert all(source.startswith("https://") for source in profile.sources)
        with pytest.raises(FrozenInstanceError):
            profile.id = "changed"  # type: ignore[misc]


def test_prompt_preserves_applicability_limits_and_traceable_sources():
    prompt = curriculum_guidance_prompt()
    assert CURRICULUM_GUIDANCE_VERSION in prompt
    assert "Output language is not evidence of country" in prompt
    assert "unlisted or ambiguous curriculum" in prompt
    assert "course/textbook" in prompt
    for profile in CURRICULUM_GUIDANCE:
        assert profile.scope in prompt
        assert profile.guidance in prompt
        assert all(source in prompt for source in profile.sources)


def test_school_angle_guidance_does_not_flatten_curricula():
    profiles = {profile.id: profile for profile in CURRICULUM_GUIDANCE}
    assert "Math II" in profiles["JP-MEXT"].guidance
    assert "Key stage 4" in profiles["GB-ENG-NC"].guidance
    assert "degrees" in profiles["GB-ENG-NC"].guidance
    assert "whole UK" in profiles["GB-ENG-NC"].scope
    assert "HSF.TF.A.1-2" in profiles["US-CCSS"].guidance
    assert "single grade" in profiles["US-CCSS"].guidance
    assert "other standards" in profiles["US-CCSS"].scope
