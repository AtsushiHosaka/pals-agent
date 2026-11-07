"""Library profiles: which pinned Lean workspace a proof is verified against.

A profile names one immutable (Lean toolchain, library set, workspace) triple. The default profile
is the workspace PALS has always verified against; its behaviour and every digest derived from it
are unchanged. A non-default profile adds a source ``import`` allow-list, because the library behind
it is only partly trusted (Stacks: ``StacksCore`` is reviewed, ``StacksFrontier`` is not).

One verifier process serves exactly one profile. Routing a request to a profile is the caller's job
(it picks the verifier deployment); the verifier never accepts a profile from the request body, so a
request cannot widen the libraries its own proof may import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pals_agent.lean_audit import TRUSTED_AUDIT_SOURCE
from pals_agent.lean_source_policy import SourceViolation, strip_lean_comments_and_strings

DEFAULT_PROFILE_NAME: Final = "mathlib-4.32"
IMPORT_VIOLATION_CODE: Final = "lean.disallowed_import"

_PROFILE_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-[0-9]+\.[0-9]+$")
# Lean's header: `import Foo.Bar`, `public import ...`, `meta import ...`, `import all Foo`.
_IMPORT_RE: Final = re.compile(
    r"^[ \t]*(?:(?:public|meta)[ \t]+)*import[ \t]+(?:all[ \t]+)?(?P<module>[^\s]+)",
    re.MULTILINE,
)
_MODULE_NAME_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")


class UnknownLibraryProfile(ValueError):
    """The requested profile is not one this build defines."""


class LibraryProfileMismatch(ValueError):
    """A workspace on disk is not the one its profile pins."""


@dataclass(frozen=True, slots=True)
class LibraryProfile:
    """One pinned verification environment.

    ``workspace`` is relative to the package root so that the definition is machine independent;
    deployments bind the absolute path through ``PALS_LEAN_PROJECT_DIR``. ``import_roots`` is
    ``None`` for the default profile (no new restriction) and otherwise the only top-level module
    names a source may import.
    """

    name: str
    lean_version: str
    workspace: str
    pins: tuple[tuple[str, str], ...]
    import_roots: tuple[str, ...] | None = None
    # Lean 4.33+ prints a deprecation warning for the audit program's `Environment.replay` on
    # stdout, which the audit parser (correctly) treats as a malformed report. The default profile
    # keeps its audit source byte-identical.
    silence_audit_deprecations: bool = False

    def __post_init__(self) -> None:
        if _PROFILE_NAME_RE.fullmatch(self.name) is None:
            raise ValueError("library profile name is malformed")
        if not self.lean_version.startswith("leanprover/lean4:v"):
            raise ValueError("library profile Lean version is malformed")
        if self.import_roots is not None and not self.import_roots:
            raise ValueError("an import allow-list must not be empty")

    @property
    def is_default(self) -> bool:
        return self.name == DEFAULT_PROFILE_NAME

    @property
    def fingerprint_name(self) -> str | None:
        """The name a toolchain fingerprint records; absent for the default, keeping its digest."""
        return None if self.is_default else self.name

    @property
    def audit_source(self) -> str:
        """The trusted audit program for this profile's Lean version."""
        if not self.silence_audit_deprecations:
            return TRUSTED_AUDIT_SOURCE
        marker = "open Lean\n"
        if TRUSTED_AUDIT_SOURCE.count(marker) != 1:
            raise AssertionError("trusted audit source layout changed")
        return TRUSTED_AUDIT_SOURCE.replace(
            marker, "set_option linter.deprecated false\n" + marker, 1
        )

    def import_violation(self, source: str) -> SourceViolation | None:
        """Return the first ``import`` outside the allow-list, or ``None``."""
        if self.import_roots is None:
            return None
        code = strip_lean_comments_and_strings(source)
        for match in _IMPORT_RE.finditer(code):
            module = match.group("module").replace("«", "").replace("»", "")
            root = module.split(".", 1)[0]
            if _MODULE_NAME_RE.fullmatch(module) is None or root not in self.import_roots:
                return SourceViolation(
                    IMPORT_VIOLATION_CODE,
                    f"Generated Lean code imports `{module}`, which the {self.name} "
                    "library profile does not allow.",
                )
        return None

    def validate_workspace(self, project_dir: Path) -> None:
        """Refuse a workspace whose pinned toolchain is not this profile's."""
        toolchain = project_dir / "lean-toolchain"
        try:
            pinned = toolchain.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as error:
            raise LibraryProfileMismatch("profile lean-toolchain is unreadable") from error
        if pinned != self.lean_version:
            raise LibraryProfileMismatch(
                f"profile {self.name} pins {self.lean_version}, workspace pins {pinned}"
            )


_PROFILES: Final = {
    profile.name: profile
    for profile in (
        LibraryProfile(
            name=DEFAULT_PROFILE_NAME,
            lean_version="leanprover/lean4:v4.32.0-rc1",
            workspace="lean-workspace",
            pins=(("mathlib", "8b62164d808cd0f23b7d8cc28190a6c1a1bb483a"),),
        ),
        LibraryProfile(
            name="stacks-4.35",
            lean_version="leanprover/lean4:v4.35.0",
            workspace="lean-workspaces/stacks-4.35",
            pins=(
                ("mathlib", "56a005855ea17e0b0958f73ec801ae140b0a1679"),
                ("stacks", "5ed82d14634e8d9576bb844c7bd4e3da66d450e7"),
            ),
            # `StacksFrontier` is AI-generated and unreviewed, and the umbrella `Stacks` library
            # imports it. Neither is built into the workspace; this keeps it that way by policy.
            import_roots=("Mathlib", "StacksCore"),
            silence_audit_deprecations=True,
        ),
    )
}


def known_profile_names() -> tuple[str, ...]:
    return tuple(_PROFILES)


def resolve_profile(name: str | None = None) -> LibraryProfile:
    """Return the named profile; ``None`` is the default. An unknown name is rejected."""
    if name is None:
        return _PROFILES[DEFAULT_PROFILE_NAME]
    profile = _PROFILES.get(name) if isinstance(name, str) else None
    if profile is None:
        raise UnknownLibraryProfile(f"unknown library profile: {str(name)[:64]!r}")
    return profile
