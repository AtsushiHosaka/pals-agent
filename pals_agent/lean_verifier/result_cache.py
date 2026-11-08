"""In-process, shadow-first result cache for the verifier's x² template sources.

Scope (owner decision, design option 1):

* Only a source that is byte-identical to an entry of an allow-list is ever looked up or stored.
  The verifier builds the allow-list at startup by rendering the x² template itself for every
  binding the worker can produce, so a learner-supplied byte string can never enter the cache.
* Only successes are stored, in process memory only (a restart is the only way to clear it, and
  there is no API to read, write or flush it).  The number of entries is bounded by the size of
  the allow-list.
* SHADOW (``PALS_VERIFIER_RESULT_CACHE_SHADOW``): the verifier always compiles and returns the
  normal result.  For an allow-list hit it also records whether a stored verdict for the same full
  key exists and whether the fresh result agrees with it.  One disagreement is logged at ERROR and
  blocks serving for the rest of the process.
* SERVE (``PALS_VERIFIER_RESULT_CACHE_ENABLED``, requires the shadow flag): an allow-list hit with
  a stored success for the same full key is answered without compiling, unless a disagreement
  was seen.  The HTTP layer marks the response ``Pals-Verification-Source: cache``.

Nothing here logs the source, the key or the job; only counters and the allow-list ordinal (the
templates are public).
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, cast

import rfc8785

SOURCE_HEADER: Final = "Pals-Verification-Source"
SOURCE_COMPILE: Final = "compile"
SOURCE_CACHE: Final = "cache"

# No policy or axiom-audit version existed in code (the design's ``audit_version`` is spec-only),
# so this constant is new.  Bump it whenever the accept/reject rules of the verifier change.  The
# key also carries a hash of the policy modules' bytes, so forgetting to bump it still cannot
# serve an entry across a different build.
VERIFIER_POLICY_VERSION: Final = "pals.verifier-policy.v1"

_KEY_SCHEMA_VERSION: Final = "pals.verifier-result-cache-key.v1"
_ENDPOINT_KIND: Final = "proof_job"
_POLICY_MODULES: Final = (
    "pals_agent.lean",
    "pals_agent.lean_audit",
    "pals_agent.lean_source_policy",
    "pals_agent.lean_supervisor",
)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")

_LOGGER: Final = logging.getLogger("pals_agent.lean_verifier.result_cache")


class ResultCacheMode(Enum):
    OFF = "off"
    SHADOW = "shadow"
    SERVE = "serve"


def result_cache_mode(*, shadow: bool, enabled: bool) -> ResultCacheMode:
    """Both flags default to false; serving is never reachable without the shadow comparison."""
    if enabled and not shadow:
        raise ValueError(
            "PALS_VERIFIER_RESULT_CACHE_ENABLED requires PALS_VERIFIER_RESULT_CACHE_SHADOW"
        )
    if enabled:
        return ResultCacheMode.SERVE
    return ResultCacheMode.SHADOW if shadow else ResultCacheMode.OFF


class FreshOutcome(Enum):
    """What a real compile said about an allow-listed source."""

    SUCCESS = "success"
    # The verifier rejected the source (a verdict).
    FAILURE = "failure"
    # Timeout or an interruption from outside the proof: not a verdict (the API retries these).
    INCONCLUSIVE = "inconclusive"


def build_x_squared_allow_list() -> tuple[str, ...]:
    """Render every x² source the worker can produce, with the real renderer.

    Imported lazily: with both flags off the verifier never loads the template module.
    """
    from pals_agent.lean_templates import (
        render_x_squared_epsilon_delta,
        x_squared_worker_bindings,
    )

    rendered = (render_x_squared_epsilon_delta(b) for b in x_squared_worker_bindings())
    return tuple(dict.fromkeys(rendered))


def policy_modules_sha256() -> str:
    """Hash of the bytes of the modules that decide acceptance, read once at startup."""
    digests: dict[str, str] = {}
    for name in _POLICY_MODULES:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise ValueError("verifier policy module is unavailable")
        digests[name] = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
    return hashlib.sha256(_canonical(digests)).hexdigest()


def lean_verification_options(verifier: object) -> dict[str, object]:
    """The options that can change whether a source verifies; part of the key."""
    from pals_agent import lean as lean_module
    from pals_agent.lean_verifier import boundary

    options: dict[str, object] = {
        "allow_sorry": False,
        "lean_threads": 1,
        "address_space_limit_bytes": lean_module._ADDRESS_SPACE_LIMIT_BYTES,
        "file_size_limit_bytes": lean_module._FILE_SIZE_LIMIT_BYTES,
        "process_limit": lean_module._PROCESS_LIMIT,
        "open_file_limit": lean_module._OPEN_FILE_LIMIT,
        "cgroup_memory_max_bytes": boundary._MAX_MEMORY_BYTES,
        "cgroup_pids_max": boundary._MAX_PIDS,
        "verifier_class": type(verifier).__qualname__,
    }
    if isinstance(verifier, lean_module.LeanVerifier):
        options.update(
            timeout_seconds=float(verifier.timeout_seconds),
            output_limit_bytes=verifier.output_limit_bytes,
            literal_admission_command=verifier.literal_admission_command,
        )
    return options


@dataclass(frozen=True, slots=True)
class CacheKeyComponents:
    """Everything besides the source bytes that a stored verdict depends on."""

    lean_version: str
    lean_toolchain_file_sha256: str
    lake_manifest_sha256: str
    verifier_toolchain_sha256: str
    verifier_image_digest: str
    policy_version: str
    policy_sha256: str
    options: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in (
            "lean_toolchain_file_sha256",
            "lake_manifest_sha256",
            "verifier_toolchain_sha256",
            "policy_sha256",
        ):
            if _SHA256_RE.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256")
        if _IMAGE_DIGEST_RE.fullmatch(self.verifier_image_digest) is None:
            raise ValueError("verifier_image_digest must be a sha256 image digest")
        if not self.lean_version or not self.policy_version:
            raise ValueError("lean_version and policy_version must be nonblank")


@dataclass(frozen=True, slots=True)
class CacheDecision:
    """What the cache decided for one request, computed by the verifier from the received bytes."""

    eligible: bool
    key: str | None = None
    key_index: int | None = None
    serve: bool = False


_NOT_ELIGIBLE: Final = CacheDecision(eligible=False)


class VerifierResultCache:
    """Thread-safe allow-list cache; every method is O(1) and never compiles under its lock."""

    def __init__(
        self,
        *,
        mode: ResultCacheMode,
        allow_list: Sequence[str],
        components: CacheKeyComponents,
        logger: logging.Logger = _LOGGER,
    ) -> None:
        if mode is ResultCacheMode.OFF:
            raise ValueError("an off cache is represented by no cache object")
        entries = tuple(allow_list)
        if not entries or len(set(entries)) != len(entries):
            raise ValueError("allow-list must be a nonempty set of distinct sources")
        self._mode = mode
        self._logger = logger
        self._allow_index: Mapping[str, int] = {source: i for i, source in enumerate(entries)}
        self._keys: tuple[str, ...] = tuple(
            _key_for(hashlib.sha256(source.encode("utf-8")).hexdigest(), components)
            for source in entries
        )
        self._key_set: frozenset[str] = frozenset(self._keys)
        self.max_entries: Final = len(entries)
        self._lock = threading.Lock()
        self._stored: dict[str, str] = {}  # key -> origin id (content free)
        self._blocked = False
        self._counters: dict[str, int] = {}

    @property
    def mode(self) -> ResultCacheMode:
        return self._mode

    @property
    def allow_list_size(self) -> int:
        return len(self._allow_index)

    @property
    def serving_blocked(self) -> bool:
        with self._lock:
            return self._blocked

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {**self._counters, "entries": len(self._stored)}

    def begin(self, source: str) -> CacheDecision:
        """Classify a request.  Anything outside the allow-list is ineligible and untouched."""
        index = self._allow_index.get(source)
        if index is None:
            self._count("ineligible")
            self._log("ineligible")
            return _NOT_ELIGIBLE
        key = self._keys[index]
        with self._lock:
            stored = self._stored.get(key)
            blocked = self._blocked
            serve = self._mode is ResultCacheMode.SERVE and stored is not None and not blocked
            label = "hit" if serve else "eligible_compile"
            self._bump(label)
            if self._mode is ResultCacheMode.SERVE and stored is not None and blocked:
                self._bump("blocked_by_mismatch")
        self._log(label, index=index, origin=stored if serve else None)
        return CacheDecision(eligible=True, key=key, key_index=index, serve=serve)

    def finish_compiled(self, decision: CacheDecision, outcome: FreshOutcome) -> None:
        """Compare a fresh compile with the stored verdict and store a first success."""
        if not decision.eligible or decision.key is None:
            return
        key = decision.key
        if key not in self._key_set:
            # Only ``begin`` hands out decisions; a foreign key can never be stored.
            self._count("foreign_decision")
            self._logger.error("verifier_cache result=foreign_decision mode=%s", self._mode.value)
            return
        log_result: str
        log_level = logging.INFO
        with self._lock:
            stored = self._stored.get(key)
            if outcome is FreshOutcome.SUCCESS:
                if stored is not None:
                    self._bump("shadow_match")
                    log_result = "shadow_match"
                elif len(self._stored) < self.max_entries:
                    self._stored[key] = secrets.token_hex(8)
                    self._bump("stored")
                    self._bump("shadow_no_prior")
                    log_result = "stored"
                else:  # unreachable: keys come only from the allow-list
                    self._bump("store_refused_full")
                    log_result = "store_refused_full"
                    log_level = logging.ERROR
            elif outcome is FreshOutcome.FAILURE:
                if stored is not None:
                    self._blocked = True
                    self._bump("shadow_mismatch")
                    log_result = "shadow_mismatch"
                    log_level = logging.ERROR
                else:
                    self._bump("failure_not_stored")
                    log_result = "failure_not_stored"
            else:
                if stored is not None:
                    self._bump("shadow_inconclusive")
                    log_result = "shadow_inconclusive"
                    log_level = logging.WARNING
                else:
                    self._bump("inconclusive_not_stored")
                    log_result = "inconclusive_not_stored"
            entries = len(self._stored)
            blocked = self._blocked
        self._logger.log(
            log_level,
            "verifier_cache result=%s key_index=%s fresh=%s mode=%s entries=%d "
            "serving_blocked=%s",
            log_result,
            decision.key_index,
            outcome.value,
            self._mode.value,
            entries,
            str(blocked).lower(),
        )

    def _count(self, name: str) -> None:
        with self._lock:
            self._bump(name)

    def _bump(self, name: str) -> None:
        self._counters[name] = self._counters.get(name, 0) + 1

    def _log(self, result: str, *, index: int | None = None, origin: str | None = None) -> None:
        # Content free: no source, no key, no job id.
        self._logger.info(
            "verifier_cache result=%s key_index=%s origin_id=%s mode=%s",
            result,
            index,
            origin,
            self._mode.value,
        )


def build_result_cache(
    *,
    mode: ResultCacheMode,
    verifier: object,
    lean_version: str,
    lean_toolchain_file_sha256: str,
    lake_manifest_sha256: str,
    verifier_toolchain_sha256: str,
    verifier_image_digest: str,
    allow_list: Sequence[str] | None = None,
) -> VerifierResultCache | None:
    """The cache for the running verifier, or ``None`` when both flags are off."""
    if mode is ResultCacheMode.OFF:
        return None
    components = CacheKeyComponents(
        lean_version=lean_version,
        lean_toolchain_file_sha256=lean_toolchain_file_sha256,
        lake_manifest_sha256=lake_manifest_sha256,
        verifier_toolchain_sha256=verifier_toolchain_sha256,
        verifier_image_digest=verifier_image_digest,
        policy_version=VERIFIER_POLICY_VERSION,
        policy_sha256=policy_modules_sha256(),
        options=lean_verification_options(verifier),
    )
    return VerifierResultCache(
        mode=mode,
        allow_list=build_x_squared_allow_list() if allow_list is None else allow_list,
        components=components,
    )


def _key_for(source_sha256: str, components: CacheKeyComponents) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "schema": _KEY_SCHEMA_VERSION,
                "endpoint_kind": _ENDPOINT_KIND,
                "source_sha256": source_sha256,
                "toolchain": {
                    "lean_version": components.lean_version,
                    "lean_toolchain_file_sha256": components.lean_toolchain_file_sha256,
                    "lake_manifest_sha256": components.lake_manifest_sha256,
                    "verifier_toolchain_sha256": components.verifier_toolchain_sha256,
                    "verifier_image_digest": components.verifier_image_digest,
                },
                "policy": {
                    "version": components.policy_version,
                    "sha256": components.policy_sha256,
                },
                "options": dict(components.options),
            }
        )
    ).hexdigest()


def _canonical(value: object) -> bytes:
    return rfc8785.dumps(cast(Any, value))
