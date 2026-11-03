"""Small, source-backed curriculum reference for explanation prompts.

These pinned summaries are guidance, not a complete syllabus or a claim that
every learner has mastered the material at a particular age. No learner data,
network access, or country inference belongs in this registry.
"""

from __future__ import annotations

from dataclasses import dataclass

CURRICULUM_GUIDANCE_VERSION = "2026-11-04.v1"


@dataclass(frozen=True, slots=True)
class CurriculumGuidance:
    id: str
    revision: str
    scope: str
    guidance: str
    sources: tuple[str, ...]


CURRICULUM_GUIDANCE = (
    CurriculumGuidance(
        id="JP-MEXT",
        revision="2017 lower-secondary; 2018 upper-secondary",
        scope="Japan's MEXT school curriculum; not university course ordering.",
        guidance=(
            "Lower-secondary geometry uses degrees. In junior year 2, geometric proofs "
            "build on angle and parallel-line properties and triangle congruence; do not "
            "use a result being proved as a prerequisite. Math I treats triangle ratios; "
            "Math II extends to general angles and introduces radians and trigonometric "
            "functions. Use degrees for elementary/lower-secondary geometry unless the "
            "learner explicitly requests radians; do not impose Math II tools on Math I/A "
            "problems without explanation. A textbook's within-course sequence can vary."
        ),
        sources=(
            "https://www.mext.go.jp/component/a_menu/education/micro_detail/"
            "__icsFiles/afieldfile/2019/03/18/1387018_004.pdf",
            "https://www.mext.go.jp/content/20230217-mxt_kyoiku02-100002620_05.pdf",
        ),
    ),
    CurriculumGuidance(
        id="GB-ENG-NC",
        revision="2014 national curriculum; official HTML updated 2021-09-28",
        scope="England only; do not extend this profile to the whole UK.",
        guidance=(
            "Key stage 2 year 5 measures angles in degrees, including a full turn of "
            "360 degrees and a straight angle of 180 degrees. Key stage 3 builds on "
            "key stage 2 understanding, using angle facts and reasoning about triangles "
            "and polygons. Key stage 4 also specifies trigonometric graph arguments in "
            "degrees. Do not assume high-school trigonometry always requires radians. "
            "Progression depends on secure understanding, not a rigid order of lessons."
        ),
        sources=(
            "https://www.gov.uk/government/publications/national-curriculum-in-england-"
            "mathematics-programmes-of-study/national-curriculum-in-england-mathematics-"
            "programmes-of-study",
        ),
    ),
    CurriculumGuidance(
        id="US-CCSS",
        revision="Common Core State Standards for Mathematics, 2010",
        scope=(
            "Common Core only when that standard is specified; US states and districts "
            "can use other standards and course sequences."
        ),
        guidance=(
            "Grade 4 standards 4.MD.C.5-7 introduce degree measurement, protractors "
            "and addition of angle measures. High-school HSF.TF.A.1-2 introduces "
            "radian measure using arc length on the unit circle and then extends "
            "trigonometric functions to real inputs. Establish angle measure and "
            "unit-circle meaning before using radian identities. The high-school "
            "standards do not assign this topic to a single grade or impose one "
            "national course sequence."
        ),
        sources=(
            "https://www.thecorestandards.org/Math/Content/4/MD/",
            "https://www.thecorestandards.org/Math/Content/HSF/TF/",
        ),
    ),
)


def curriculum_guidance_prompt() -> str:
    """Render trusted reference text; applicability is decided from request context."""
    lines = [
        f"Curriculum reference registry {CURRICULUM_GUIDANCE_VERSION}:",
        "Use a profile only when the request identifies its country/region or curriculum. "
        "Output language is not evidence of country, curriculum, grade, or mastery. "
        "An explicit learner description of studied material takes priority over these "
        "broad summaries. For an unlisted or ambiguous curriculum, do not invent local "
        "requirements or a lesson order; explain needed prerequisites and ask for the "
        "course/textbook if that uncertainty materially affects the solution. These "
        "profiles are partial reference summaries, not globally exhaustive coverage.",
    ]
    for profile in CURRICULUM_GUIDANCE:
        lines.extend(
            (
                f"{profile.id} [{profile.revision}]: {profile.scope} {profile.guidance}",
                "Official sources: " + "; ".join(profile.sources),
            )
        )
    return "\n".join(lines)
