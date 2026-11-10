"""Declarative description of one external Lean library (``pals_agent/lean_libraries/*.toml``).

A library is added to PALS by writing one manifest, not code. A manifest pins where the library
comes from (repository, exact commit, SPDX licence, attribution), the toolchain and workspace that
verify it, how much of it is trusted (a *layer* per import root, with a generic trust word), which
environment flag opens it, and the library profiles it yields. ``pals_agent.lean_profiles`` turns
the manifests into ``LibraryProfile`` objects; nothing here touches Lean.

Trust words (generic, kernel-checked unless noted):

* ``kernel-checked-reviewed``   -- Lean accepts the proofs and a human reviewed the statements
* ``kernel-checked-unreviewed`` -- Lean accepts the proofs; no human reviewed the statements
* ``statement-only``            -- statements without proofs; never importable, only indexed

Words stored before manifests existed (``core``, ``frontier``) stay readable through
``canonical_trust``.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

MANIFEST_SCHEMA: Final = "pals.lean-library-manifest.v1"
MANIFEST_DIR: Final = Path(__file__).parent / "lean_libraries"

TRUST_REVIEWED: Final = "kernel-checked-reviewed"
TRUST_UNREVIEWED: Final = "kernel-checked-unreviewed"
TRUST_STATEMENT_ONLY: Final = "statement-only"
TRUST_WORDS: Final = (TRUST_REVIEWED, TRUST_UNREVIEWED, TRUST_STATEMENT_ONLY)
# Words written by indexes and results that predate manifests. Reading them stays supported.
TRUST_ALIASES: Final = {"core": TRUST_REVIEWED, "frontier": TRUST_UNREVIEWED}

# How a profile treats the constants its statements reach.
STATEMENTS_UNCHECKED: Final = "unchecked"  # no origin check (the historical default)
STATEMENTS_REVIEWED_ONLY: Final = "reviewed-only"  # every constant must come from a reviewed root
STATEMENTS_RECORD_UNREVIEWED: Final = "record-unreviewed"  # unreviewed roots are recorded
STATEMENT_MODES: Final = (
    STATEMENTS_UNCHECKED, STATEMENTS_REVIEWED_ONLY, STATEMENTS_RECORD_UNREVIEWED,
)

_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-[0-9]+\.[0-9]+$")
_ROOT_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_SPDX_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*(?: (?:AND|OR|WITH) [A-Za-z0-9.+-]+)*$")
_FLAG_RE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")


class LibraryManifestError(ValueError):
    """A library manifest is malformed or inconsistent. Loading fails closed."""


def canonical_trust(word: str) -> str:
    """The generic trust word for ``word``; a legacy word maps, an unknown word is rejected."""
    canonical = TRUST_ALIASES.get(word, word)
    if canonical not in TRUST_WORDS:
        raise LibraryManifestError(f"unknown trust word: {word[:40]!r}")
    return canonical


@dataclass(frozen=True, slots=True)
class Layer:
    root: str
    trust: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """One profile a manifest yields. ``imports`` is ``None`` for an unrestricted profile."""

    name: str
    imports: tuple[str, ...] | None
    statements: str = STATEMENTS_UNCHECKED
    requires_flag: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryManifest:
    name: str
    repo: str
    commit: str
    license_spdx: str
    attribution: str
    lean_version: str
    workspace: str
    pins: tuple[tuple[str, str], ...]
    silence_audit_deprecations: bool
    # Every root a built workspace can contain besides the library's own layers, in the order the
    # trusted audit lists them (the order is part of the audit program, hence of its digest).
    dependency_roots: tuple[str, ...]
    layers: tuple[Layer, ...]
    profiles: tuple[ProfileSpec, ...]
    allowed_axioms: tuple[str, ...]
    # Where the build recipe of the built-module set lives, and the pinned declaration index.
    built_modules_ref: str | None = None
    index_sha256: str | None = None
    index_path: str | None = None
    notes: str = ""
    # A library whose files live inside a dependency another profile already serves (for example
    # Mathlib's own `Archive/`) yields no profile of its own and names the serving profile here.
    host_profile: str | None = None

    def layer(self, root: str) -> Layer | None:
        return next((layer for layer in self.layers if layer.root == root), None)

    def trust_of(self, root: str) -> str | None:
        layer = self.layer(root)
        return None if layer is None else layer.trust

    def statement_roots(self, mode: str) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
        """``(trusted, recorded)`` statement roots a profile in ``mode`` needs."""
        if mode == STATEMENTS_UNCHECKED:
            return None, None
        reviewed = tuple(layer.root for layer in self.layers if layer.trust == TRUST_REVIEWED)
        trusted = tuple(dict.fromkeys((*self.dependency_roots, *reviewed)))
        if mode == STATEMENTS_REVIEWED_ONLY:
            return trusted, None
        recorded = tuple(layer.root for layer in self.layers if layer.trust == TRUST_UNREVIEWED)
        if not recorded:
            raise LibraryManifestError(f"{self.name}: no unreviewed layer to record")
        return trusted, recorded


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LibraryManifestError(message)


def _table(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    _require(isinstance(value, dict), f"[{key}] is missing or not a table")
    return value  # type: ignore[return-value]


def _text(data: Mapping[str, Any], key: str, *, optional: bool = False) -> str | None:
    value = data.get(key)
    if value is None and optional:
        return None
    _require(isinstance(value, str) and bool(value.strip()), f"`{key}` must be non-empty text")
    return value


def _roots(values: Any, what: str) -> tuple[str, ...]:
    _require(isinstance(values, list) and bool(values), f"{what} must be a non-empty list")
    _require(all(isinstance(v, str) and _ROOT_RE.fullmatch(v) for v in values), f"{what} malformed")
    _require(len(set(values)) == len(values), f"{what} has duplicates")
    return tuple(values)


def parse_manifest(data: Mapping[str, Any], *, standard_axioms: frozenset[str]) -> LibraryManifest:
    """Validate a decoded manifest. ``standard_axioms`` is the audit's own axiom allow-list."""
    _require(data.get("schema") == MANIFEST_SCHEMA, "unsupported manifest schema")
    library = _table(data, "library")
    toolchain = _table(data, "toolchain")
    name = _text(library, "name")
    _require(_NAME_RE.fullmatch(name or "") is not None, "library name is malformed")
    commit = _text(library, "commit")
    _require(_SHA_RE.fullmatch(commit or "") is not None, "library commit must be 40 hex digits")
    spdx = _text(library, "license")
    _require(_SPDX_RE.fullmatch(spdx or "") is not None, "licence must be an SPDX expression")
    repo = _text(library, "repo")
    _require((repo or "").startswith("https://"), "library repo must be an https URL")
    lean_version = _text(toolchain, "lean")
    _require((lean_version or "").startswith("leanprover/lean4:v"), "Lean version is malformed")
    workspace = _text(toolchain, "workspace")
    _require(
        not (workspace or "").startswith("/") and ".." not in (workspace or "").split("/"),
        "workspace must be a relative path inside the package root",
    )
    pins_table = _table(data, "pins")
    _require(bool(pins_table), "[pins] is empty")
    for key, value in pins_table.items():
        _require(_NAME_RE.fullmatch(key) is not None, "pin name malformed")
        _require(
            isinstance(value, str) and _SHA_RE.fullmatch(value) is not None,
            f"pin {key} is not a commit",
        )
    dependency_roots = _roots(toolchain.get("dependency_roots"), "dependency_roots")

    layers: list[Layer] = []
    for raw in data.get("layers", []):
        _require(isinstance(raw, dict), "a layer is not a table")
        root = _text(raw, "root")
        trust = canonical_trust(_text(raw, "trust") or "")
        _require(_ROOT_RE.fullmatch(root or "") is not None, "layer root malformed")
        layers.append(Layer(root or "", trust, str(raw.get("description", ""))))
    layer_roots = [layer.root for layer in layers]
    _require(len(set(layer_roots)) == len(layer_roots), "duplicate layer roots")

    importable = set(dependency_roots) | {
        layer.root for layer in layers if layer.trust != TRUST_STATEMENT_ONLY
    }
    profiles: list[ProfileSpec] = []
    for raw in data.get("profiles", []):
        _require(isinstance(raw, dict), "a profile is not a table")
        profile_name = _text(raw, "name")
        _require(_PROFILE_RE.fullmatch(profile_name or "") is not None, "profile name malformed")
        imports = raw.get("imports")
        if imports is not None:
            imports = _roots(imports, f"{profile_name}.imports")
            _require(set(imports) <= importable, f"{profile_name}: imports an unknown root")
        mode = str(raw.get("statements", STATEMENTS_UNCHECKED))
        _require(mode in STATEMENT_MODES, f"{profile_name}: unknown statements mode")
        flag = raw.get("requires_flag")
        _require(
            flag is None or (isinstance(flag, str) and _FLAG_RE.fullmatch(flag) is not None),
            f"{profile_name}: malformed flag",
        )
        spec = ProfileSpec(profile_name or "", imports, mode, flag)
        if mode != STATEMENTS_UNCHECKED:
            _require(
                bool(layers) and spec.imports is not None,
                f"{profile_name}: statement checks need layers and an import list",
            )
        profiles.append(spec)
    host_profile = library.get("host_profile")
    _require(
        bool(profiles) != (host_profile is not None),
        "a manifest yields profiles or names a host profile, not both and not neither",
    )

    audit = _table(data, "audit")
    axioms = audit.get("allowed_axioms")
    _require(
        isinstance(axioms, list) and all(isinstance(a, str) for a in axioms), "axioms malformed"
    )
    assert isinstance(axioms, list)
    # A manifest may narrow the audit's axiom list, never widen it.
    _require(set(axioms) <= standard_axioms, "a manifest cannot allow axioms the audit rejects")

    build = data.get("build", {})
    index = data.get("index", {})
    index_sha = index.get("sha256")
    _require(
        index_sha is None
        or (isinstance(index_sha, str) and _SHA256_RE.fullmatch(index_sha) is not None),
        "index digest malformed",
    )
    return LibraryManifest(
        name=name or "",
        repo=repo or "",
        commit=commit or "",
        license_spdx=spdx or "",
        attribution=_text(library, "attribution") or "",
        lean_version=lean_version or "",
        workspace=workspace or "",
        pins=tuple(pins_table.items()),
        silence_audit_deprecations=bool(toolchain.get("silence_audit_deprecations", False)),
        dependency_roots=dependency_roots,
        layers=tuple(layers),
        profiles=tuple(profiles),
        allowed_axioms=tuple(axioms),
        built_modules_ref=build.get("modules_ref"),
        index_sha256=index_sha,
        index_path=index.get("path"),
        notes=str(library.get("notes", "")),
        host_profile=host_profile,
    )


def load_manifest(path: Path, *, standard_axioms: frozenset[str]) -> LibraryManifest:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise LibraryManifestError(f"manifest {path.name} is unreadable") from error
    manifest = parse_manifest(data, standard_axioms=standard_axioms)
    _require(path.stem == manifest.name, f"manifest {path.name} does not match its library name")
    return manifest


def load_manifests(
    directory: Path = MANIFEST_DIR, *, standard_axioms: frozenset[str]
) -> tuple[LibraryManifest, ...]:
    """Every manifest in ``directory``, sorted by file name; profile names must be unique."""
    manifests = tuple(
        load_manifest(path, standard_axioms=standard_axioms)
        for path in sorted(directory.glob("*.toml"))
    )
    seen: set[str] = set()
    for manifest in manifests:
        for spec in manifest.profiles:
            _require(spec.name not in seen, f"duplicate profile name {spec.name}")
            seen.add(spec.name)
    for manifest in manifests:
        if manifest.host_profile is not None:
            _require(manifest.host_profile in seen, f"{manifest.name}: unknown host profile")
    return manifests
