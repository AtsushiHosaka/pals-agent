"""Process-local Lake setup reuse; never stores proof results or compiled modules.

Only verifier-owned, trusted workspaces are supported. Production attests their
read-only mount before enabling this cache. Every request still executes Lean.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Closed vocabulary observed with the pinned Lean 4.32.0-rc1 Lake. An upgrade
# adding keys falls back to the original command until explicitly reviewed.
_LAKE_KEYS = frozenset({
    "ELAN", "ELAN_TOOLCHAIN", "LAKE", "LAKE_ARTIFACT_CACHE", "LAKE_CACHE_DIR",
    "LAKE_CONFIG", "LAKE_HOME", "LAKE_NO_CACHE", "LAKE_PKG_URL_MAP",
    "LAKE_RESTORE_ARTIFACTS", "LEAN", "LEAN_AR", "LEAN_GITHASH", "LEAN_PATH",
    "LEAN_SRC_PATH", "LEAN_SYSROOT", "PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
})
_CONFIG_NAMES = ("lean-toolchain", "lake-manifest.json", "lakefile.lean", "lakefile.toml")
_REQUEST_LAKE_CONFIG = "\x01pals-request-home-lake-config"


@dataclass(frozen=True, slots=True)
class VerificationTiming:
    stage: str
    elapsed_ms: float
    cache_status: str | None = None


def environment_identity(
    project_dir: Path, lean_binary: str, lake_binary: str, base: dict[str, str],
) -> str:
    """Bind setup to config bytes, package topology, executables and platform.

    This is an environment key, not a proof/artifact fingerprint. Source and
    .olean bytes are deliberately never treated as cached verification evidence.
    Arbitrary executable Lake configuration is trusted deployment input and must
    remain immutable in production, even beyond the files listed here.
    """
    root = project_dir.resolve(strict=True)
    manifest = json.loads((root / "lake-manifest.json").read_text())
    packages = manifest["packages"]
    if not isinstance(packages, list):
        raise ValueError("invalid Lake packages")
    packages_dir = root / manifest.get("packagesDir", ".lake/packages")
    if not packages_dir.resolve().is_relative_to(root):
        raise ValueError("external Lake packages are unsupported")
    roots = [root]
    for package in packages:
        name = package["name"]
        if (
            package.get("type") != "git" or not isinstance(name, str)
            or not name or Path(name).name != name or name in {".", ".."}
            or package.get("subDir") is not None
        ):
            raise ValueError("unsupported Lake package topology")
        package_root = packages_dir / name
        resolved = package_root.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("external Lake dependency is unsupported")
        roots.append(resolved)
    digest = hashlib.sha256()
    digest.update(json.dumps({
        "schema": "pals.lake-environment.v1",
        "platform": [platform.system(), platform.machine()],
        "base": {key: value for key, value in base.items() if key not in {"HOME", "TMPDIR"}},
        "roots": [str(path) for path in roots],
    }, sort_keys=True).encode())
    for executable in (lean_binary, lake_binary):
        path = Path(executable).resolve(strict=True)
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    for directory in roots:
        paths = [directory / name for name in _CONFIG_NAMES]
        # Lake's evaluated configuration is itself a trusted executable artifact.
        paths.extend(sorted((directory / ".lake").glob("lakefile.olean*")))
        paths.extend(sorted((directory / ".lake/config").glob("*")))
        for path in paths:
            if not path.resolve().is_relative_to(root):
                raise ValueError("external Lake configuration is unsupported")
            digest.update(str(path).encode())
            digest.update(path.read_bytes() if path.is_file() else b"<absent>")
    return digest.hexdigest()


def parse_lake_environment(raw: str, base: dict[str, str]) -> dict[str, str]:
    if not raw.endswith("\0"):
        raise ValueError("incomplete Lake environment")
    values: dict[str, str] = {}
    for entry in raw[:-1].split("\0"):
        key, separator, value = entry.partition("=")
        if not separator or not key or key in values:
            raise ValueError("invalid Lake environment")
        values[key] = value
    if any(values.get(key) != value for key, value in base.items() if key != "PATH"):
        raise ValueError("Lake changed a fixed child environment key")
    delta = {key: value for key, value in values.items() if base.get(key) != value}
    # Darwin's child Python runtime introduces this key before exec. It is not
    # Lake configuration and must never expand the production Linux vocabulary.
    if sys.platform == "darwin" and re.fullmatch(
        r"0x[0-9A-Fa-f]+:0x[0-9A-Fa-f]+:0x[0-9A-Fa-f]+",
        delta.get("__CF_USER_TEXT_ENCODING", ""),
    ):
        delta.pop("__CF_USER_TEXT_ENCODING")
    if delta.keys() - _LAKE_KEYS:
        raise ValueError("unreviewed Lake environment key")
    if _REQUEST_LAKE_CONFIG in delta.values():
        raise ValueError("reserved environment template")
    # The pinned Lake defaults this key to HOME/.lake/config.toml. Rebind the
    # exact known default to each request; never retain the previous HOME.
    if delta.get("LAKE_CONFIG") == str(Path(base["HOME"]) / ".lake/config.toml"):
        delta["LAKE_CONFIG"] = _REQUEST_LAKE_CONFIG
    # Never retain a prior request's writable scratch paths in a later child.
    for value in delta.values():
        if any(base[key] and base[key] in value for key in ("HOME", "TMPDIR")):
            raise ValueError("Lake environment depends on request scratch")
    return delta


def materialize_lake_environment(base: dict[str, str], delta: dict[str, str]) -> dict[str, str]:
    result = {**base, **delta}
    if result.get("LAKE_CONFIG") == _REQUEST_LAKE_CONFIG:
        result["LAKE_CONFIG"] = str(Path(base["HOME"]) / ".lake/config.toml")
    return result


class LakeEnvironmentCache:
    """One entry per verifier, serialized preparation and explicit lifecycle reset."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: str | None = None
        self._environment: dict[str, str] = {}

    def clear(self) -> None:
        with self._lock:
            self._key = None
            self._environment = {}

    def get_or_prepare(
        self, key: str, prepare: Callable[[], dict[str, str]], *, timeout_seconds: float = 10.0,
    ) -> tuple[dict[str, str], str]:
        if not self._lock.acquire(timeout=timeout_seconds):
            raise TimeoutError("Lake preparation lock deadline expired")
        try:
            if key == self._key:
                return dict(self._environment), "hit"
            self._key = None
            self._environment = {}
            environment = prepare()
            self._environment = dict(environment)
            self._key = key
            return dict(environment), "miss"
        finally:
            self._lock.release()
