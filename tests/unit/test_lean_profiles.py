from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_audit import TRUSTED_AUDIT_SOURCE
from pals_agent.lean_profiles import (
    DEFAULT_PROFILE_NAME,
    IMPORT_VIOLATION_CODE,
    LibraryProfileMismatch,
    UnknownLibraryProfile,
    known_profile_names,
    resolve_profile,
)
from pals_agent.lean_verifier.http_server import pinned_recipe_admission_context
from pals_agent.private_recipe_selection import ToolchainFingerprintV1

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_WORKSPACE = _ROOT / "lean-workspace"
_STACKS_WORKSPACE = _ROOT / "lean-workspaces" / "stacks-4.35"

# Issued before library profiles existed. If any of these change, every admitted Recipe and every
# in-flight verifier request of the default profile would silently stop matching.
_DEFAULT_LAKE_MANIFEST_SHA256 = "290f048c4a499d34a3b21f8db30ade48a2b8d05b0fe79709f1868fa6748944fa"
_DEFAULT_CONTEXT_FINGERPRINT_SHA256 = (
    "ab8dc65a8114f548d3e453ca4000b59a9c0c4b0a338fef2c9df55f0f737939db"
)
_DEFAULT_CONTEXT_COMPILER_COMMAND_SHA256 = (
    "bbb7dccbe35ee121655d2b2c9dbfba64b7244620c989d86ef8534b9e0c8aa74d"
)
_DEFAULT_CLIENT_FINGERPRINT_SHA256 = (
    "6cc0610965c5ef58e3bb7ca05b63393b0249f34ab7a605ebaf3c579414cda47a"
)


def test_default_profile_is_the_historical_workspace_and_adds_no_restriction() -> None:
    profile = resolve_profile(None)

    assert profile is resolve_profile(DEFAULT_PROFILE_NAME)
    assert DEFAULT_PROFILE_NAME == "mathlib-4.32"
    assert profile.is_default
    assert profile.workspace == "lean-workspace"
    assert profile.import_roots is None
    assert profile.fingerprint_name is None
    assert profile.audit_source is TRUSTED_AUDIT_SOURCE
    assert (_ROOT / profile.workspace).resolve() == _DEFAULT_WORKSPACE.resolve()
    assert profile.import_violation("import StacksFrontier.X\nimport Lean\n") is None
    profile.validate_workspace(_DEFAULT_WORKSPACE)


def test_default_profile_pins_match_the_workspace_files() -> None:
    profile = resolve_profile(None)
    manifest = json.loads((_DEFAULT_WORKSPACE / "lake-manifest.json").read_text())

    assert (_DEFAULT_WORKSPACE / "lean-toolchain").read_text().strip() == profile.lean_version
    assert dict(profile.pins)["mathlib"] == _manifest_revs(manifest)["mathlib"]


def test_default_digests_are_byte_identical_to_those_issued_before_profiles() -> None:
    context = pinned_recipe_admission_context(
        project_dir=_DEFAULT_WORKSPACE, verifier_sha256="a" * 64
    )

    assert context.toolchain_fingerprint == {
        "schema_version": "pals.lean-toolchain-fingerprint.v1",
        "lean_version": "leanprover/lean4:v4.32.0-rc1",
        "lake_manifest_sha256": _DEFAULT_LAKE_MANIFEST_SHA256,
        "verifier_sha256": "a" * 64,
        "materializer_version": "pals.recipe-materializer.v1",
    }
    assert context.toolchain_fingerprint_sha256 == _DEFAULT_CONTEXT_FINGERPRINT_SHA256
    assert context.compiler_command_sha256 == _DEFAULT_CONTEXT_COMPILER_COMMAND_SHA256
    # Naming the default explicitly (or not at all) must not change anything either.
    assert pinned_recipe_admission_context(
        project_dir=_DEFAULT_WORKSPACE,
        verifier_sha256="a" * 64,
        library_profile=resolve_profile(DEFAULT_PROFILE_NAME).fingerprint_name,
    ) == context

    client = ToolchainFingerprintV1(
        lean_version="leanprover/lean4:v4.32.0-rc1",
        lake_manifest_sha256="b" * 64,
        verifier_sha256="a" * 64,
        materializer_version="pals.recipe-materializer.v1",
    )
    assert set(client.as_json()) == {
        "schema_version",
        "lean_version",
        "lake_manifest_sha256",
        "verifier_sha256",
        "materializer_version",
    }
    assert client.sha256 == _DEFAULT_CLIENT_FINGERPRINT_SHA256


def test_default_verifier_keeps_the_unrestricted_import_and_audit_path() -> None:
    assert LeanVerifier().library_profile is None


@pytest.mark.parametrize(
    "name",
    ["", "mathlib", "Mathlib-4.32", "mathlib-4.32 ", " stacks-4.35", "stacks-4.36", "stacks_4.35",
     "../stacks-4.35", "stacks-4.35\n", "stacks-4.35\x00", "𝗌tacks-4.35", "a" * 5000],
)
def test_an_unknown_or_malformed_profile_name_is_rejected(name: str) -> None:
    with pytest.raises(UnknownLibraryProfile):
        resolve_profile(name)


def test_a_non_string_profile_name_is_rejected() -> None:
    with pytest.raises(UnknownLibraryProfile):
        resolve_profile(4.35)  # type: ignore[arg-type]


def test_runtime_settings_refuse_an_unknown_profile_and_default_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pals_agent.lean_verifier import http_runtime

    monkeypatch.setenv("PALS_LEAN_LIBRARY_PROFILE", "stacks-9.99")
    with pytest.raises(UnknownLibraryProfile):
        resolve_profile(http_runtime._optional("PALS_LEAN_LIBRARY_PROFILE"))
    monkeypatch.setenv("PALS_LEAN_LIBRARY_PROFILE", "")
    with pytest.raises(ValueError):
        http_runtime._optional("PALS_LEAN_LIBRARY_PROFILE")
    monkeypatch.delenv("PALS_LEAN_LIBRARY_PROFILE")
    assert resolve_profile(http_runtime._optional("PALS_LEAN_LIBRARY_PROFILE")).is_default


def test_stacks_profile_pins_match_its_workspace_files() -> None:
    profile = resolve_profile("stacks-4.35")
    manifest = json.loads((_STACKS_WORKSPACE / "lake-manifest.json").read_text())
    revs = _manifest_revs(manifest)

    assert not profile.is_default
    assert profile.fingerprint_name == "stacks-4.35"
    assert (_ROOT / profile.workspace).resolve() == _STACKS_WORKSPACE.resolve()
    assert (_STACKS_WORKSPACE / "lean-toolchain").read_text() == profile.lean_version
    assert profile.lean_version == "leanprover/lean4:v4.35.0"
    assert dict(profile.pins) == {"mathlib": revs["mathlib"], "stacks": revs["Stacks"]}
    lakefile = (_STACKS_WORKSPACE / "lakefile.lean").read_text()
    for revision in dict(profile.pins).values():
        assert f'"{revision}"' in lakefile
    profile.validate_workspace(_STACKS_WORKSPACE)


def test_stacks_workspace_never_requires_the_unreviewed_frontier() -> None:
    lakefile = _without_lean_comments((_STACKS_WORKSPACE / "lakefile.lean").read_text())
    manifest = json.loads((_STACKS_WORKSPACE / "lake-manifest.json").read_text())

    assert re.findall(r"^require\s+(\S+)", lakefile, re.MULTILINE) == ["mathlib", "Stacks"]
    assert "StacksFrontier" not in lakefile
    assert "StacksFrontier" not in json.dumps(manifest)
    assert [item["name"] for item in manifest["packages"]][:2] == ["Stacks", "mathlib"]
    assert _STACKS_WORKSPACE.joinpath("lakefile.lean").is_file()  # admission contexts read it
    dockerfile = (_ROOT / "docker" / "lean-verifier-stacks.Dockerfile").read_text()
    assert "lake build StacksCore" in dockerfile
    assert "lake build Stacks " not in dockerfile and "lake build Stacks\n" not in dockerfile
    assert "lake update" not in _without_shell_comments(dockerfile)
    assert "PALS_LEAN_LIBRARY_PROFILE=stacks-4.35" in dockerfile


def test_workspace_that_pins_another_toolchain_is_refused(tmp_path: Path) -> None:
    stacks = resolve_profile("stacks-4.35")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(LibraryProfileMismatch):
        stacks.validate_workspace(workspace)  # no lean-toolchain
    (workspace / "lean-toolchain").write_text("leanprover/lean4:v4.32.0-rc1")
    with pytest.raises(LibraryProfileMismatch):
        stacks.validate_workspace(workspace)
    with pytest.raises(LibraryProfileMismatch):
        resolve_profile(None).validate_workspace(_STACKS_WORKSPACE)
    (workspace / "lean-toolchain").write_text("leanprover/lean4:v4.35.0\n")
    stacks.validate_workspace(workspace)


@pytest.mark.parametrize(
    "source",
    [
        "import Mathlib\nexample : True := trivial\n",
        "import Mathlib.Data.Finset.Card\nimport StacksCore.Data.Finset.Card\n",
        "import StacksCore\n",
        "public import StacksCore.Algebra.Algebra.Basic\n",
        "import all StacksCore.Data.Finset.Card\n",
        "example : True := trivial\n",
        "-- import StacksFrontier.X\nimport Mathlib\n",
        '/- import Stacks -/\nimport Mathlib\nexample := "import StacksFrontier"\n',
    ],
)
def test_stacks_profile_allows_only_mathlib_and_stackscore_imports(source: str) -> None:
    assert resolve_profile("stacks-4.35").import_violation(source) is None


@pytest.mark.parametrize(
    "source",
    [
        "import StacksFrontier\n",
        "import StacksFrontier.AlgebraicGeometry.Crystalline.DividedPowerEnvelope.FlatRelation\n",
        "import Mathlib\nimport Stacks\n",  # the umbrella library imports the Frontier
        "import «StacksFrontier».Foo\n",
        "import StacksCoreExtra\n",
        "import Mathlib2\n",
        "import Lean\n",
        "import Batteries\n",
        "public import StacksFrontier.X\n",
        "meta import Stacks\n",
        "import all StacksFrontier.X\n",
        "import Mathlib\n  import StacksFrontier.X\n",
        "import Mathlib.Foo-Bar\n",
    ],
)
def test_stacks_profile_rejects_every_other_import(source: str) -> None:
    violation = resolve_profile("stacks-4.35").import_violation(source)

    assert violation is not None
    assert violation.code == IMPORT_VIOLATION_CODE


def test_the_verifier_enforces_the_profile_before_any_compiler_starts(tmp_path: Path) -> None:
    verifier = LeanVerifier(
        lean_binary="definitely-not-installed-lean",
        project_dir=tmp_path,
        library_profile=resolve_profile("stacks-4.35"),
    )

    rejected = verifier.verify("import StacksFrontier.X\nexample : True := trivial\n")
    reached_compiler = verifier.verify("import StacksCore\nexample : True := trivial\n")

    assert [d.code for d in rejected.diagnostics] == [IMPORT_VIOLATION_CODE]
    # An allowed import passes the profile and fails only because there is no compiler here.
    assert [d.code for d in reached_compiler.diagnostics] == ["lean.not_found"]
    # The sorry/axiom guards are profile independent.
    assert [d.code for d in verifier.verify("import StacksCore\ntheorem t : 1 = 1 := sorry\n")
            .diagnostics] == ["lean.disallowed_placeholder"]
    assert [d.code for d in verifier.verify("import StacksCore\naxiom bad : False\n")
            .diagnostics] == ["lean.disallowed_trusted_declaration"]


def test_default_verifier_still_reaches_the_compiler_for_any_import(tmp_path: Path) -> None:
    verifier = LeanVerifier(lean_binary="definitely-not-installed-lean", project_dir=tmp_path)

    result = verifier.verify("import StacksFrontier.X\nexample : True := trivial\n")

    assert [d.code for d in result.diagnostics] == ["lean.not_found"]


def test_stacks_audit_only_silences_deprecation_warnings() -> None:
    audit = resolve_profile("stacks-4.35").audit_source

    assert audit != TRUSTED_AUDIT_SOURCE
    assert audit.replace("set_option linter.deprecated false\n", "", 1) == TRUSTED_AUDIT_SOURCE
    assert audit.index("import Lean.Util.CollectAxioms") < audit.index("set_option")


def test_profiles_never_share_a_recipe_digest(tmp_path: Path) -> None:
    default = pinned_recipe_admission_context(
        project_dir=_DEFAULT_WORKSPACE, verifier_sha256="a" * 64
    )
    stacks = pinned_recipe_admission_context(
        project_dir=_STACKS_WORKSPACE,
        verifier_sha256="a" * 64,
        library_profile=resolve_profile("stacks-4.35").fingerprint_name,
    )

    assert stacks.toolchain_fingerprint["library_profile"] == "stacks-4.35"
    assert stacks.toolchain_fingerprint["lean_version"] == "leanprover/lean4:v4.35.0"
    assert stacks.toolchain_fingerprint_sha256 != default.toolchain_fingerprint_sha256
    assert stacks.compiler_command_sha256 != default.compiler_command_sha256

    # The name alone separates them, even for byte-identical workspaces and verifiers.
    copy = tmp_path / "copy"
    shutil.copytree(_STACKS_WORKSPACE, copy)
    renamed = pinned_recipe_admission_context(
        project_dir=copy, verifier_sha256="a" * 64, library_profile=None
    )
    assert renamed.toolchain_fingerprint_sha256 != stacks.toolchain_fingerprint_sha256

    client = ToolchainFingerprintV1(
        lean_version="leanprover/lean4:v4.35.0",
        lake_manifest_sha256="b" * 64,
        verifier_sha256="a" * 64,
        materializer_version="pals.recipe-materializer.v1",
    )
    named = ToolchainFingerprintV1(
        lean_version=client.lean_version,
        lake_manifest_sha256=client.lake_manifest_sha256,
        verifier_sha256=client.verifier_sha256,
        materializer_version=client.materializer_version,
        library_profile="stacks-4.35",
    )
    assert named.as_json() == {**client.as_json(), "library_profile": "stacks-4.35"}
    assert named.sha256 != client.sha256


@pytest.mark.parametrize("name", [DEFAULT_PROFILE_NAME, "stacks-9.99", "", "Stacks-4.35"])
def test_a_fingerprint_may_only_name_a_known_non_default_profile(name: str) -> None:
    with pytest.raises(ValueError):
        ToolchainFingerprintV1(
            lean_version="leanprover/lean4:v4.35.0",
            lake_manifest_sha256="b" * 64,
            verifier_sha256="a" * 64,
            materializer_version="pals.recipe-materializer.v1",
            library_profile=name,
        )
    with pytest.raises(ValueError):
        pinned_recipe_admission_context(
            project_dir=_STACKS_WORKSPACE, verifier_sha256="a" * 64, library_profile=name
        )


def test_every_registered_profile_has_a_unique_name_and_workspace() -> None:
    profiles = [resolve_profile(name) for name in known_profile_names()]

    assert known_profile_names()[0] == DEFAULT_PROFILE_NAME
    assert len({p.name for p in profiles}) == len({p.workspace for p in profiles}) == len(profiles)


def _manifest_revs(manifest: dict[str, object]) -> dict[str, str]:
    packages = manifest["packages"]
    assert isinstance(packages, list)
    return {item["name"]: item["rev"] for item in packages}


def _without_lean_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _without_shell_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
