"""Library profiles: which pinned Lean workspace a proof is verified against.

A profile names one immutable (Lean toolchain, library set, workspace) triple. Profiles are not
defined here: each library has a manifest (``pals_agent/lean_libraries/*.toml``, see
``pals_agent.lean_library_manifest``) and this module derives its profiles from them. The default
profile is the workspace PALS has always verified against; its behaviour and every digest derived
from it are unchanged. A non-default profile adds a source ``import`` allow-list, because the
library behind it is only partly trusted (Stacks: ``StacksCore`` is reviewed, ``StacksFrontier`` is not).

One verifier process serves exactly one profile. Routing a request to a profile is the caller's job
(it picks the verifier deployment); the verifier never accepts a profile from the request body, so a
request cannot widen the libraries its own proof may import.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pals_agent.lean_audit import ALLOWED_AXIOMS, TRUSTED_AUDIT_SOURCE
from pals_agent.lean_library_manifest import (
    LibraryManifest,
    LibraryManifestError,
    ProfileSpec,
    load_manifests,
)
from pals_agent.lean_source_policy import SourceViolation, strip_lean_comments_and_strings

DEFAULT_PROFILE_NAME: Final = "mathlib-4.32"
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
    # Set only on a profile whose STATEMENTS may reach an unreviewed library. A constant whose home
    # module is under one of these roots is recorded (with the proof's own library use and any
    # Frontier definition that resembles a reviewed one) instead of rejected. Constants from a root
    # that is neither trusted nor recorded are still rejected.
    statement_recorded_roots: tuple[str, ...] | None = None

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
        if self.statement_recorded_roots is not None:
            if self.statement_trusted_roots is None or not self.statement_recorded_roots:
                raise ValueError("recorded statement roots need trusted statement roots")
            if any(_ROOT_RE.fullmatch(root) is None for root in self.statement_recorded_roots):
                raise ValueError("recorded statement roots are malformed")
            if set(self.statement_recorded_roots) & set(self.statement_trusted_roots):
                raise ValueError("a root cannot be both trusted and recorded")

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
        if self.statement_recorded_roots is not None:
            recorded = ", ".join(f'"{root}"' for root in self.statement_recorded_roots)
            return _recording_audit_source(source, roots, recorded)
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


# The recording variant of the origin check: nothing under a recorded root is rejected. It lists
# every imported constant a statement reaches (stopping at the first imported constant on each
# path), the library roots a proof's value reaches through file-local constants only, and Frontier
# definitions that look like a Lean/Mathlib/StacksCore one. The meaning of a recorded constant is
# unreviewed; this program only makes the dependency visible.
_RECORD_HELPER: Final = """\
-- `ConstantInfo.value?` skips theorems, whose proofs are what a proof-side walk must read.
def valueOf : ConstantInfo → Option Expr
  | .defnInfo v => some v.value
  | .thmInfo v => some v.value
  | .opaqueInfo v => some v.value
  | _ => none

def statementOrigins (env restated : Environment) (start : List Name) :
    Array (Name × Name) × Bool := Id.run do
  let mut seen : NameSet := {}
  let mut todo := start
  let mut reached : Array (Name × Name) := #[]
  for _ in [0:200000] do
    match todo with
    | [] => return (reached, false)
    | c :: rest =>
      todo := rest
      if seen.contains c then continue
      seen := seen.insert c
      match env.getModuleIdxFor? c with
      | some idx => reached := reached.push (c, env.header.moduleNames[idx.toNat]!)
      | none =>
        if let some info := restated.find? c then
          let valueConstants := ((valueOf info).map (·.getUsedConstants.toList)).getD []
          todo := info.type.getUsedConstants.toList ++ valueConstants ++ todo
  return (reached, true)

def proofRoots (env : Environment) (locals : Std.HashMap Name ConstantInfo) (start : Name) :
    Array Name := Id.run do
  let mut seen : NameSet := {}
  let mut roots : Array Name := #[]
  let mut todo : List Name := [start]
  for _ in [0:200000] do
    match todo with
    | [] => return roots
    | c :: rest =>
      todo := rest
      if seen.contains c then continue
      seen := seen.insert c
      if let some idx := env.getModuleIdxFor? c then
        let root := (env.header.moduleNames[idx.toNat]!).getRoot
        if !roots.contains root then roots := roots.push root
      else if let some info := locals[c]? then
        todo := ((valueOf info).map (·.getUsedConstants.toList)).getD [] ++ todo
  return roots.push `exhausted

def lastComponent : Name → String
  | .str _ s => s
  | _ => ""

def constantKind : ConstantInfo → Nat
  | .defnInfo _ => 1
  | .inductInfo _ => 2
  | _ => 0

-- 0: same type and value (or constructor names); 1: same last name component and kind.
def duplicateReason (target other : ConstantInfo) : Option (Nat × String) :=
  if constantKind target == 0 || constantKind target != constantKind other then none else
  -- Same universe parameter names keep this a plain structural comparison, with no allocation.
  let sameType := target.levelParams == other.levelParams && other.type == target.type
  let sameBody := match target, other with
    | .defnInfo l, .defnInfo r => sameType && r.value == l.value
    | .inductInfo l, .inductInfo r =>
      sameType && l.ctors.map lastComponent == r.ctors.map lastComponent
    | _, _ => false
  if sameBody then
    some (0, if constantKind target == 1 then "same_value" else "same_shape")
  else if lastComponent target.name == lastComponent other.name && target.name != other.name then
    some (1, "same_name")
  else none

def frontierDuplicates (env : Environment) (roots : List String) (targets : List Name) :
    List String := Id.run do
  let infos := (targets.filterMap fun t => (env.find? t).map fun i => (t, i)).filter
    fun (_, i) => constantKind i != 0
  if infos.isEmpty then return []
  let found : Array (String × Nat × String × String) := env.constants.fold (init := #[])
    fun acc n i =>
      if constantKind i == 0 then acc else
      -- The cheap comparison first; the module lookup only for the rare constant that matches.
      infos.foldl (init := acc) fun acc (t, ti) =>
        if t == n then acc else
        match duplicateReason ti i with
        | none => acc
        | some (rank, reason) =>
          match env.getModuleIdxFor? n with
          | some idx =>
            if roots.contains (env.header.moduleNames[idx.toNat]!).getRoot.toString then
              acc.push (t.toString, rank, n.toString, reason)
            else acc
          | none => acc
  let sorted := found.qsort fun a b =>
    a.1 < b.1 || (a.1 == b.1 && (a.2.1 < b.2.1 || (a.2.1 == b.2.1 && a.2.2.1 < b.2.2.1)))
  let mut lines : Array String := #[]
  let mut perTarget := 0
  let mut previous := ""
  for (t, _, n, reason) in sorted do
    if t != previous then
      previous := t
      perTarget := 0
    if perTarget < 5 && lines.size < 24 then
      lines := lines.push s!"frontier_duplicate {t} {n} {reason}"
      perTarget := perTarget + 1
  return lines.toList
"""

_RECORD_STATEMENT_BLOCK: Final = """\
      let (reached, exhausted) := statementOrigins env restated other.type.getUsedConstants.toList
      if exhausted then IO.println s!"untrusted_statement {name} exhausted exhausted"
      let mut statementRoots : Array Name := #[]
      let mut shown := 0
      let mut rejected := 0
      for (used, home) in reached do
        let root := home.getRoot
        if !statementRoots.contains root then
          statementRoots := statementRoots.push root
          IO.println s!"statement_root {name} {root}"
        if recordedStatementRoots.contains root.toString then
          if !frontierSeen.contains used then
            frontierSeen := frontierSeen.insert used
            frontierOrder := frontierOrder.push used
          if shown < 32 then
            IO.println s!"frontier_statement {name} {used} {home}"
            shown := shown + 1
        else if !trustedStatementRoots.contains root.toString && rejected < 4 then
          IO.println s!"untrusted_statement {name} {used} {home}"
          rejected := rejected + 1
"""

_RECORD_TAIL: Final = """\
  for (name, info) in names do
    if info.isTheorem then
      for root in proofRoots env constants name do
        IO.println s!"proof_root {name} {root}"
  for line in frontierDuplicates env trustedStatementRoots frontierOrder.toList do
    IO.println line
  IO.println "trust_recorded"
"""


def _recording_audit_source(source: str, trusted: str, recorded: str) -> str:
    source = _replace_once(
        source,
        "unsafe def main",
        f"def trustedStatementRoots : List String := [{trusted}]\n\n"
        f"def recordedStatementRoots : List String := [{recorded}]\n\n"
        + _RECORD_HELPER
        + "\nunsafe def main",
    )
    source = _replace_once(
        source,
        "  for (name, info) in names do\n    if let some other := restated.find?",
        "  let mut frontierSeen : NameSet := {}\n"
        "  let mut frontierOrder : Array Name := #[]\n"
        "  for (name, info) in names do\n    if let some other := restated.find?",
    )
    source = _replace_once(
        source,
        '      IO.println s!"{if sameType && sameValue then "bound" else "unbound"} {name}"\n',
        _RECORD_STATEMENT_BLOCK
        + '      IO.println s!"{if sameType && sameValue then "bound" else "unbound"} {name}"\n',
    )
    complete = '  IO.println s!"complete {nonce}"\n'
    return _replace_once(source, complete, _RECORD_TAIL + complete)


def _profile_from_spec(manifest: LibraryManifest, spec: ProfileSpec) -> LibraryProfile:
    trusted, recorded = manifest.statement_roots(spec.statements)
    return LibraryProfile(
        name=spec.name,
        lean_version=manifest.lean_version,
        workspace=manifest.workspace,
        pins=manifest.pins,
        import_roots=spec.imports,
        silence_audit_deprecations=manifest.silence_audit_deprecations,
        statement_trusted_roots=trusted,
        requires_flag=spec.requires_flag,
        statement_recorded_roots=recorded,
    )


def _build_profiles(manifests: Sequence[LibraryManifest]) -> dict[str, LibraryProfile]:
    profiles = {
        spec.name: _profile_from_spec(manifest, spec)
        for manifest in manifests
        for spec in manifest.profiles
    }
    if DEFAULT_PROFILE_NAME not in profiles or next(iter(profiles)) != DEFAULT_PROFILE_NAME:
        raise LibraryManifestError("the default profile must come from the first manifest")
    return profiles


MANIFESTS: Final = load_manifests(standard_axioms=ALLOWED_AXIOMS)
_PROFILES: Final = _build_profiles(MANIFESTS)


def _flag_of(profile_name: str) -> str:
    flag = _PROFILES[profile_name].requires_flag
    if flag is None:
        raise LibraryManifestError(f"profile {profile_name} has no enabling flag")
    return flag


# Kept as names because verifier startup and tests refer to them; the values come from the manifest.
FRONTIER_FLAG: Final = _flag_of("stacks-frontier-4.35")
FRONTIER_STATEMENTS_FLAG: Final = _flag_of("stacks-frontier-defs-4.35")


def manifest_for_profile(name: str) -> LibraryManifest:
    """The manifest that yields profile ``name`` (an unknown name is rejected)."""
    profile = resolve_profile(name)
    return next(m for m in MANIFESTS if any(s.name == profile.name for s in m.profiles))


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
