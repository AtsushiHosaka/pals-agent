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

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pals_agent.lean_audit import TRUSTED_AUDIT_SOURCE
from pals_agent.lean_source_policy import SourceViolation, strip_lean_comments_and_strings

DEFAULT_PROFILE_NAME: Final = "mathlib-4.32"
FRONTIER_FLAG: Final = "PALS_LEAN_ALLOW_FRONTIER_PROOFS"
# Everything the workspace can contain except `StacksFrontier`: Lean itself, its reviewed
# dependencies, Mathlib and the human-reviewed `StacksCore`.
_LIBRARY_ROOTS: Final = (
    "Init", "Std", "Lean", "Lake", "Batteries", "Aesop", "Qq", "Plausible", "ImportGraph",
    "ProofWidgets", "LeanSearchClient", "Cli", "Mathlib", "StacksCore",
)
IMPORT_VIOLATION_CODE: Final = "lean.disallowed_import"

_PROFILE_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-[0-9]+\.[0-9]+$")
# Lean's header: `import Foo.Bar`, `public import ...`, `meta import ...`, `import all Foo`.
_IMPORT_RE: Final = re.compile(
    r"^[ \t]*(?:(?:public|meta)[ \t]+)*import[ \t]+(?:all[ \t]+)?(?P<module>[^\s]+)",
    re.MULTILINE,
)
_ROOT_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_MODULE_NAME_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")


class UnknownLibraryProfile(ValueError):
    """The requested profile is not one this build defines."""


class LibraryProfileMismatch(ValueError):
    """A workspace on disk is not the one its profile pins."""


class LibraryProfileNotEnabled(ValueError):
    """A request asked for a profile this deployment does not serve (fail closed, no fallback)."""


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
    # Set only on a profile whose proofs may use an unreviewed library: every constant a statement
    # reaches (through the user's own definitions too) must come from a module under one of these
    # roots, or the audit rejects it. ``None`` (all other profiles) adds no such check.
    statement_trusted_roots: tuple[str, ...] | None = None
    # Environment variable that must equal ``true`` for a verifier to start with this profile.
    requires_flag: str | None = None

    def __post_init__(self) -> None:
        if _PROFILE_NAME_RE.fullmatch(self.name) is None:
            raise ValueError("library profile name is malformed")
        if not self.lean_version.startswith("leanprover/lean4:v"):
            raise ValueError("library profile Lean version is malformed")
        if self.import_roots is not None and not self.import_roots:
            raise ValueError("an import allow-list must not be empty")
        if self.statement_trusted_roots is not None and (
            not self.statement_trusted_roots
            or any(_ROOT_RE.fullmatch(root) is None for root in self.statement_trusted_roots)
        ):
            raise ValueError("statement trusted roots are malformed")
        if self.statement_trusted_roots is not None and not self.silence_audit_deprecations:
            raise ValueError("origin checking needs the Lean 4.33+ audit variant")

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
        source = _replace_once(
            TRUSTED_AUDIT_SOURCE, "open Lean\n", "set_option linter.deprecated false\nopen Lean\n"
        )
        if self.statement_trusted_roots is None:
            return source
        roots = ", ".join(f'"{root}"' for root in self.statement_trusted_roots)
        source = _replace_once(
            source,
            "unsafe def main",
            f"def trustedStatementRoots : List String := [{roots}]\n\n"
            + _ORIGIN_HELPER
            + "\nunsafe def main",
        )
        return _replace_once(
            source,
            '      IO.println s!"{if sameType && sameValue then "bound" else "unbound"} {name}"\n',
            "      if let some (used, home) := untrustedOrigin env restated trustedStatementRoots\n"
            "          other.type.getUsedConstants.toList then\n"
            '        IO.println s!"untrusted_statement {name} {used} {home}"\n'
            '      IO.println s!"{if sameType && sameValue then "bound" else "unbound"} {name}"\n',
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
        """Refuse a workspace whose toolchain or package revisions are not this profile's."""
        toolchain = project_dir / "lean-toolchain"
        try:
            pinned = toolchain.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as error:
            raise LibraryProfileMismatch("profile lean-toolchain is unreadable") from error
        if pinned != self.lean_version:
            raise LibraryProfileMismatch(
                f"profile {self.name} pins {self.lean_version}, workspace pins {pinned}"
            )
        try:
            manifest = json.loads((project_dir / "lake-manifest.json").read_text("utf-8"))
            packages = manifest["packages"]
            revisions = {package["name"].lower(): package.get("rev") for package in packages}
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
            raise LibraryProfileMismatch("profile lake-manifest.json is unreadable") from error
        for name, revision in self.pins:
            if revisions.get(name) != revision:
                raise LibraryProfileMismatch(f"profile {self.name} pins {name} at {revision}")


# Walks from a statement's constants through the user's own (module-less) definitions and returns
# the first imported constant whose module is outside the trusted roots.
_ORIGIN_HELPER: Final = """\
def untrustedOrigin (env restated : Environment) (roots : List String)
    (start : List Name) : Option (Name × Name) := Id.run do
  let mut seen : NameSet := {}
  let mut todo := start
  for _ in [0:200000] do
    match todo with
    | [] => return none
    | c :: rest =>
      todo := rest
      if seen.contains c then continue
      seen := seen.insert c
      match env.getModuleIdxFor? c with
      | some idx =>
        let moduleName := env.header.moduleNames[idx.toNat]!
        if !roots.contains moduleName.getRoot.toString then return some (c, moduleName)
      | none =>
        if let some info := restated.find? c then
          let valueConstants := (info.value?.map (·.getUsedConstants.toList)).getD []
          todo := info.type.getUsedConstants.toList ++ valueConstants ++ todo
  return some (`exhausted, `exhausted)
"""


def _replace_once(text: str, marker: str, replacement: str) -> str:
    if text.count(marker) != 1:
        raise AssertionError("trusted audit source layout changed")
    return text.replace(marker, replacement, 1)


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
        # Proofs may use `StacksFrontier` lemmas (the kernel checks them); statements may not
        # mention a Frontier constant, because its meaning has not been reviewed. Disabled unless
        # the verifier is started with PALS_LEAN_ALLOW_FRONTIER_PROOFS=true, and only the Frontier
        # modules built into the image are importable at all.
        LibraryProfile(
            name="stacks-frontier-4.35",
            lean_version="leanprover/lean4:v4.35.0",
            workspace="lean-workspaces/stacks-4.35",
            pins=(
                ("mathlib", "56a005855ea17e0b0958f73ec801ae140b0a1679"),
                ("stacks", "5ed82d14634e8d9576bb844c7bd4e3da66d450e7"),
            ),
            import_roots=("Mathlib", "StacksCore", "StacksFrontier"),
            silence_audit_deprecations=True,
            statement_trusted_roots=_LIBRARY_ROOTS,
            requires_flag=FRONTIER_FLAG,
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


@dataclass(frozen=True, slots=True)
class ProfileRoutedVerifier:
    """The verifiers one deployment serves, keyed by profile name.

    Selecting a profile happens here, at the caller, never inside a verifier: each verifier is bound
    to one profile when it is built. A request for a profile with no verifier is refused rather than
    answered by the default one, because verifying against a different library than the one asked
    for would turn a refusal into a silent, wrong ``verified``.
    """

    verifiers: Mapping[str, Any]

    def __post_init__(self) -> None:
        if DEFAULT_PROFILE_NAME not in self.verifiers:
            raise ValueError("the default profile must always be served")
        for name in self.verifiers:
            resolve_profile(name)

    def verifier_for(self, name: str | None) -> Any:
        profile = resolve_profile(name)
        verifier = self.verifiers.get(profile.name)
        if verifier is None:
            raise LibraryProfileNotEnabled(f"library profile is not enabled: {profile.name}")
        return verifier


def build_profile_verifiers(
    *,
    default_verifier: Any,
    workspaces: Mapping[str, Path],
    environ: Mapping[str, str] | None = None,
    **verifier_options: Any,
) -> ProfileRoutedVerifier:
    """Serve the default verifier plus every non-default profile whose gate is open.

    ``workspaces`` maps a profile name to its absolute, pinned workspace. A profile is served only
    when it is listed there and, if it has a ``requires_flag``, that variable is exactly ``"true"``;
    its workspace is validated against the profile's pins before use. Everything else stays
    unserved, so a request for it is refused by ``ProfileRoutedVerifier.verifier_for``.
    """
    from pals_agent.lean import LeanVerifier  # lean imports this module

    env = os.environ if environ is None else environ
    verifiers: dict[str, Any] = {DEFAULT_PROFILE_NAME: default_verifier}
    for name, workspace in workspaces.items():
        profile = resolve_profile(name)
        if profile.is_default:
            raise ValueError("the default profile's verifier is passed as default_verifier")
        if profile.requires_flag is not None and env.get(profile.requires_flag) != "true":
            continue
        profile.validate_workspace(workspace)
        verifiers[name] = LeanVerifier(
            project_dir=workspace, library_profile=profile, **verifier_options
        )
    return ProfileRoutedVerifier(verifiers)
