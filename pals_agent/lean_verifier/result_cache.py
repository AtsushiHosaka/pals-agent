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
* REVALIDATE (``PALS_VERIFIER_RESULT_CACHE_REVALIDATE``, required by the serve flag): a served hit
  does not compile, so a stored success could silently go stale.  After the response is written, a
  thinned subset of hits triggers one background compile of the allow-list entry (never on the
  request path, one at a time, only with a free compile slot).  A conclusive disagreement blocks
  serving like a shadow mismatch; a timeout or interruption is only counted.

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
import time
from collections.abc import Callable, Mapping, Sequence
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
# Revalidation thinning: every N-th serve of an entry (and its first serve) triggers one compile.
REVALIDATE_EVERY_DEFAULT: Final = 20
REVALIDATE_EVERY_MIN: Final = 1
REVALIDATE_EVERY_MAX: Final = 10_000
# A revalidation holds a compile slot, so it gets its own, shorter deadline than a real request's
# 300 s: a normal compile takes ~10-18 s, a page-cache-cold one up to ~50 s.  Hitting the cap is
# inconclusive (never a mismatch) and frees the slot for real requests.
REVALIDATION_DEADLINE_SECONDS: Final = 60.0
_REVALIDATION_COUNTERS: Final = (
    "revalidations_started",
    "revalidation_match",
    "revalidation_mismatch",
    "revalidation_inconclusive",
    "revalidation_skipped_busy",
    "revalidation_skipped_no_slot",
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


def resolve_result_cache_flags(*, shadow: bool, enabled: bool, revalidate: bool) -> ResultCacheMode:
    """The startup rules over all three flags; any violation refuses to start.

    * ENABLED needs SHADOW (the comparison) and REVALIDATE (the only way a mismatch stays
      observable once hits stop compiling).
    * REVALIDATE needs a cache to revalidate: SHADOW or ENABLED.
    """
    mode = result_cache_mode(shadow=shadow, enabled=enabled)
    if enabled and not revalidate:
        raise ValueError(
            "PALS_VERIFIER_RESULT_CACHE_ENABLED requires PALS_VERIFIER_RESULT_CACHE_REVALIDATE"
        )
    if revalidate and mode is ResultCacheMode.OFF:
        raise ValueError(
            "PALS_VERIFIER_RESULT_CACHE_REVALIDATE requires PALS_VERIFIER_RESULT_CACHE_SHADOW "
            "or PALS_VERIFIER_RESULT_CACHE_ENABLED"
        )
    return mode


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
    # Set only on a served hit that is due for a background revalidation (a pre-check; the real
    # decision is taken again, atomically, by ``start_revalidation``).
    revalidate: bool = False


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
        revalidate_every: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if mode is ResultCacheMode.OFF:
            raise ValueError("an off cache is represented by no cache object")
        if revalidate_every is not None and (
            type(revalidate_every) is not int
            or not REVALIDATE_EVERY_MIN <= revalidate_every <= REVALIDATE_EVERY_MAX
        ):
            raise ValueError("revalidate_every is outside its bound")
        entries = tuple(allow_list)
        if not entries or len(set(entries)) != len(entries):
            raise ValueError("allow-list must be a nonempty set of distinct sources")
        self._mode = mode
        self._logger = logger
        self._sources: tuple[str, ...] = entries
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
        self._counters: dict[str, int] = (
            {} if revalidate_every is None else dict.fromkeys(_REVALIDATION_COUNTERS, 0)
        )
        # Revalidation bookkeeping.  It never touches ``_stored`` and never clears ``_blocked``.
        self._revalidate_every = revalidate_every
        self._clock = clock
        self._served_since: dict[str, int] = {}  # key -> serves since its last revalidation start
        self._revalidation_started_keys: set[str] = set()
        self._revalidation_in_flight = False
        self._last_revalidation_at: float | None = None

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

    @property
    def revalidate_every(self) -> int | None:
        return self._revalidate_every

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            data = {**self._counters, "entries": len(self._stored)}
            if self._revalidate_every is not None:
                data["revalidate_every"] = self._revalidate_every
                data["revalidation_in_flight"] = int(self._revalidation_in_flight)
                if self._last_revalidation_at is not None:
                    data["last_revalidation_age_seconds"] = max(
                        0, int(self._clock() - self._last_revalidation_at)
                    )
            return data

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
            revalidate = False
            if serve and self._revalidate_every is not None:
                since = self._served_since.get(key, 0) + 1
                self._served_since[key] = since
                revalidate = self._revalidation_due(key, since)
            if self._mode is ResultCacheMode.SERVE and stored is not None and blocked:
                self._bump("blocked_by_mismatch")
        self._log(label, index=index, origin=stored if serve else None)
        return CacheDecision(
            eligible=True, key=key, key_index=index, serve=serve, revalidate=revalidate
        )

    def _revalidation_due(self, key: str, served_since: int) -> bool:
        """Per-entry thinning.  Caller holds the lock.

        An entry is due on its first serve, then again once N more serves have happened since the
        revalidation started.  The counter is per entry (not global) so a hot entry cannot starve
        a rarely served one.  A skipped attempt does not reset it, so the entry stays due.
        """
        every = self._revalidate_every
        return every is not None and (
            key not in self._revalidation_started_keys or served_since >= every
        )

    def start_revalidation(
        self,
        decision: CacheDecision,
        *,
        compile_outcome: Callable[[str], FreshOutcome],
        slot: threading.BoundedSemaphore,
    ) -> threading.Thread | None:
        """Start one background compile of a served entry, or skip.  Never blocks, never raises
        into the request path's response (the caller has already written it).

        Skipped when serving is blocked, when the entry is not due any more (another hit handled
        it), when a revalidation is already in flight, or when no compile slot is free.  The slot
        is taken without waiting and held for the whole compile.
        """
        key, index = decision.key, decision.key_index
        if (
            not decision.revalidate
            or key is None
            or index is None
            or self._revalidate_every is None
        ):
            return None
        busy = False
        with self._lock:
            if self._blocked:
                return None
            if not self._revalidation_due(key, self._served_since.get(key, 0)):
                return None
            if self._revalidation_in_flight:
                self._bump("revalidation_skipped_busy")
                busy = True
            else:
                self._revalidation_in_flight = True
        if busy:
            self._log_revalidation(logging.INFO, "revalidation_skipped_busy", key, index)
            return None
        if not slot.acquire(blocking=False):
            with self._lock:
                self._revalidation_in_flight = False
                self._bump("revalidation_skipped_no_slot")
            self._log_revalidation(logging.INFO, "revalidation_skipped_no_slot", key, index)
            return None
        with self._lock:
            served_since = self._served_since.get(key, 0)
            self._served_since[key] = 0
            self._revalidation_started_keys.add(key)
            self._bump("revalidations_started")
        self._log_revalidation(
            logging.INFO, "revalidation_started", key, index, served_since=served_since
        )
        thread = threading.Thread(
            target=self._run_revalidation,
            args=(key, index, served_since, compile_outcome, slot),
            name="verifier-result-cache-revalidation",
            daemon=True,
        )
        try:
            thread.start()
        except BaseException:
            slot.release()
            self._complete_revalidation(
                key, index, served_since, FreshOutcome.INCONCLUSIVE, elapsed_ms=0.0
            )
            raise
        return thread

    def _run_revalidation(
        self,
        key: str,
        index: int,
        served_since: int,
        compile_outcome: Callable[[str], FreshOutcome],
        slot: threading.BoundedSemaphore,
    ) -> None:
        started = self._clock()
        outcome = FreshOutcome.INCONCLUSIVE
        try:
            try:
                outcome = compile_outcome(self._sources[index])
            except Exception:
                # Not a verdict: the compiler did not answer.  Counted as inconclusive.
                outcome = FreshOutcome.INCONCLUSIVE
            finally:
                slot.release()
        finally:
            self._complete_revalidation(
                key, index, served_since, outcome, elapsed_ms=(self._clock() - started) * 1000.0
            )

    def _complete_revalidation(
        self, key: str, index: int, served_since: int, outcome: FreshOutcome, *, elapsed_ms: float
    ) -> None:
        level = logging.INFO
        with self._lock:
            self._revalidation_in_flight = False
            self._last_revalidation_at = self._clock()
            if outcome is FreshOutcome.SUCCESS:
                # The stored verdict is left exactly as it was: a match only refreshes the
                # revalidation bookkeeping above, so it can neither store over nor unblock.
                self._bump("revalidation_match")
                result = "revalidation_match"
            elif outcome is FreshOutcome.FAILURE:
                self._blocked = True
                self._bump("revalidation_mismatch")
                result = "revalidation_mismatch"
                level = logging.ERROR
            else:
                self._bump("revalidation_inconclusive")
                result = "revalidation_inconclusive"
                level = logging.WARNING
        self._log_revalidation(
            level, result, key, index, served_since=served_since, elapsed_ms=elapsed_ms
        )

    def _log_revalidation(
        self,
        level: int,
        result: str,
        key: str,
        index: int,
        *,
        served_since: int | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        # Content free: a short hash OF the key (not the key, not the source) names the entry.
        entry = hashlib.sha256(b"verifier-result-cache-entry:" + key.encode("ascii")).hexdigest()
        with self._lock:
            blocked = self._blocked
        self._logger.log(
            level,
            "verifier_cache result=%s entry=%s key_index=%s elapsed_ms=%s served_since=%s "
            "revalidate_every=%s mode=%s serving_blocked=%s",
            result,
            entry[:12],
            index,
            "-" if elapsed_ms is None else f"{elapsed_ms:.0f}",
            "-" if served_since is None else served_since,
            self._revalidate_every,
            self._mode.value,
            str(blocked).lower(),
        )

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
    revalidate_every: int | None = None,
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
        revalidate_every=revalidate_every,
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
