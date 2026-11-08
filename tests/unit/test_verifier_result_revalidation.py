"""Background revalidation of the verifier result cache (rules, concurrency, flags, HTTP).

The Lean compiler is a fake here: these tests prove the revalidation state machine and the HTTP
contract around it, not a real Lean run (see ``verifier_cache_real_lean.py`` for that).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from threading import Barrier, Event, Lock, Thread
from typing import Any

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_verifier import http_runtime
from pals_agent.lean_verifier import result_cache as result_cache_module
from pals_agent.lean_verifier.http_runtime import HttpVerifierRuntimeSettings
from pals_agent.lean_verifier.result_cache import (
    REVALIDATE_EVERY_DEFAULT,
    REVALIDATE_EVERY_MAX,
    REVALIDATE_EVERY_MIN,
    REVALIDATION_DEADLINE_SECONDS,
    SOURCE_HEADER,
    CacheDecision,
    FreshOutcome,
    ResultCacheMode,
    VerifierResultCache,
    resolve_result_cache_flags,
)
from pals_agent.models import VerificationResult
from tests.unit import test_verifier_result_cache as _base
from tests.unit.test_http_verifier_runtime import _set_required_environment
from tests.unit.test_isolated_verifier_http_server import (
    _failure,
    _interrupted,
    _success,
    _timeout_failure,
)
from tests.unit.test_verifier_result_cache import (
    _BASE_COMPONENTS,
    ALLOW_LIST,
    ATTESTATION_KEYS,
    FIRST,
    SECOND,
    _post,
    _serving,
)

tls_contexts = _base.tls_contexts  # the same mTLS fixture

LOGGER_NAME = result_cache_module._LOGGER.name  # noqa: SLF001


def _cache(
    every: int | None = 3,
    mode: ResultCacheMode = ResultCacheMode.SERVE,
    clock: Callable[[], float] = time.monotonic,
) -> VerifierResultCache:
    return VerifierResultCache(
        mode=mode,
        allow_list=ALLOW_LIST,
        components=_BASE_COMPONENTS,
        revalidate_every=every,
        clock=clock,
    )


def _store(cache: VerifierResultCache, source: str = FIRST) -> None:
    decision = cache.begin(source)
    cache.finish_compiled(decision, FreshOutcome.SUCCESS)


def _slot(size: int = 1) -> threading.BoundedSemaphore:
    return threading.BoundedSemaphore(size)


def _serve_and_revalidate(
    cache: VerifierResultCache,
    source: str,
    outcome: FreshOutcome = FreshOutcome.SUCCESS,
    *,
    slot: threading.BoundedSemaphore | None = None,
) -> threading.Thread | None:
    """One cache hit, then (like the HTTP layer) a revalidation attempt; joins the thread."""
    decision = cache.begin(source)
    assert decision.serve
    thread = cache.start_revalidation(
        decision, compile_outcome=lambda _source: outcome, slot=slot or _slot()
    )
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive()
    return thread


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition was not reached in time"
        time.sleep(0.005)


# --- thinning -----------------------------------------------------------------------------------


def test_the_first_serve_and_then_exactly_every_nth_serve_revalidate() -> None:
    cache = _cache(every=3)
    _store(cache)
    triggered = [serve for serve in range(1, 14) if _serve_and_revalidate(cache, FIRST) is not None]
    # Serve 1 (first-serve rule), then every 3rd serve counted from that revalidation's start.
    assert triggered == [1, 4, 7, 10, 13]
    snapshot = cache.snapshot()
    assert snapshot["revalidations_started"] == 5
    assert snapshot["revalidation_match"] == 5
    assert snapshot["hit"] == 13


def test_every_one_revalidates_every_serve() -> None:
    cache = _cache(every=1)
    _store(cache)
    assert all(_serve_and_revalidate(cache, FIRST) is not None for _ in range(5))


def test_a_cache_miss_is_never_a_serve_and_never_revalidates() -> None:
    cache = _cache(every=1)
    decision = cache.begin(FIRST)  # nothing stored yet: a compile, not a serve
    assert not decision.serve and not decision.revalidate
    assert (
        cache.start_revalidation(
            decision, compile_outcome=lambda _s: FreshOutcome.SUCCESS, slot=_slot()
        )
        is None
    )
    assert cache.snapshot()["revalidations_started"] == 0


def test_counters_are_per_entry_so_a_hot_entry_cannot_starve_a_rare_one() -> None:
    cache = _cache(every=5)
    _store(cache, FIRST)
    _store(cache, SECOND)
    assert _serve_and_revalidate(cache, FIRST) is not None  # first serve of FIRST
    for _ in range(40):  # FIRST is hot
        _serve_and_revalidate(cache, FIRST)
    # SECOND is served once, after 40 serves of FIRST: its own first serve still triggers.
    assert _serve_and_revalidate(cache, SECOND) is not None
    # And not again before five more serves of SECOND.
    assert [_serve_and_revalidate(cache, SECOND) is not None for _ in range(5)] == [
        False,
        False,
        False,
        False,
        True,
    ]


def test_a_skipped_attempt_leaves_the_entry_due_so_the_next_serve_retries() -> None:
    cache = _cache(every=50)
    _store(cache)
    held = _slot()
    assert held.acquire(blocking=False)  # the verifier is busy
    assert _serve_and_revalidate(cache, FIRST, slot=held) is None
    assert cache.snapshot()["revalidation_skipped_no_slot"] == 1
    assert cache.snapshot()["revalidations_started"] == 0
    # Still the "first serve" obligation: the very next serve retries (no 50-serve wait).
    held.release()
    assert _serve_and_revalidate(cache, FIRST, slot=held) is not None
    assert cache.snapshot()["revalidations_started"] == 1


def test_a_revalidation_resets_the_serve_counter_but_not_for_serves_during_it() -> None:
    cache = _cache(every=2)
    _store(cache)
    release = Event()
    started = Event()

    def slow(_source: str) -> FreshOutcome:
        started.set()
        assert release.wait(5)
        return FreshOutcome.SUCCESS

    first = cache.begin(FIRST)
    thread = cache.start_revalidation(first, compile_outcome=slow, slot=_slot())
    assert thread is not None and started.wait(5)
    for _ in range(3):  # three serves while it runs
        cache.begin(FIRST)
    release.set()
    thread.join(timeout=5)
    # Those serves counted toward the next revalidation: it is already due.
    assert cache.begin(FIRST).revalidate


# --- single flight, compile slot ----------------------------------------------------------------


def test_only_one_revalidation_is_in_flight_and_the_other_is_skipped_busy() -> None:
    cache = _cache(every=1)
    _store(cache, FIRST)
    _store(cache, SECOND)
    slot = _slot(2)  # slots are free, so only the single-flight rule can refuse
    release = Event()
    entered = Event()
    calls: list[str] = []

    def slow(source: str) -> FreshOutcome:
        calls.append(source)
        entered.set()
        assert release.wait(5)
        return FreshOutcome.SUCCESS

    a = cache.start_revalidation(cache.begin(FIRST), compile_outcome=slow, slot=slot)
    assert a is not None and entered.wait(5)
    b = cache.start_revalidation(cache.begin(SECOND), compile_outcome=slow, slot=slot)
    assert b is None
    snapshot = cache.snapshot()
    assert snapshot["revalidation_skipped_busy"] == 1 and snapshot["revalidation_in_flight"] == 1
    assert calls == [FIRST]
    release.set()
    a.join(timeout=5)
    assert cache.snapshot()["revalidation_in_flight"] == 0
    # The compile slot taken for the revalidation is back, and the second entry is still due.
    assert slot.acquire(blocking=False) and slot.acquire(blocking=False)
    assert cache.begin(SECOND).revalidate


def test_a_busy_verifier_means_the_slot_is_not_waited_for_and_not_released_by_us() -> None:
    cache = _cache(every=1)
    _store(cache)
    slot = _slot(1)
    assert slot.acquire(blocking=False)  # a real request is compiling
    started = time.monotonic()
    result = cache.start_revalidation(
        cache.begin(FIRST),
        compile_outcome=lambda _s: pytest.fail("must not compile without a slot"),
        slot=slot,
    )
    assert result is None and time.monotonic() - started < 0.5  # non-blocking
    assert cache.snapshot()["revalidation_skipped_no_slot"] == 1
    assert cache.snapshot()["revalidation_in_flight"] == 0
    # We never owned that slot, so we must not have released it (a BoundedSemaphore would raise).
    assert not slot.acquire(blocking=False)
    slot.release()


def test_the_slot_is_held_for_the_whole_compile_and_released_after() -> None:
    cache = _cache(every=1)
    _store(cache)
    slot = _slot(1)
    inside = Event()
    release = Event()

    def compile_outcome(_source: str) -> FreshOutcome:
        inside.set()
        assert release.wait(5)
        return FreshOutcome.SUCCESS

    thread = cache.start_revalidation(
        cache.begin(FIRST), compile_outcome=compile_outcome, slot=slot
    )
    assert thread is not None and inside.wait(5)
    assert not slot.acquire(blocking=False)  # held while compiling
    release.set()
    thread.join(timeout=5)
    assert slot.acquire(blocking=False)


def _race_two_hits() -> tuple[int, int, dict[str, int]]:
    cache = _cache(every=1)
    _store(cache)
    slot = _slot(2)
    gate = Event()
    compiles: list[str] = []
    threads: list[threading.Thread | None] = []
    out_lock = Lock()
    barrier = Barrier(2)

    def compile_outcome(source: str) -> FreshOutcome:
        compiles.append(source)
        gate.wait(5)
        return FreshOutcome.SUCCESS

    def hit() -> None:
        barrier.wait(timeout=5)
        decision = cache.begin(FIRST)
        thread = cache.start_revalidation(decision, compile_outcome=compile_outcome, slot=slot)
        with out_lock:
            threads.append(thread)

    hitters = [Thread(target=hit) for _ in range(2)]
    for hitter in hitters:
        hitter.start()
    for hitter in hitters:
        hitter.join(timeout=5)
    gate.set()
    started = [t for t in threads if t is not None]
    for thread in started:
        thread.join(timeout=5)
    return len(started), len(compiles), cache.snapshot()


def test_two_simultaneous_hits_start_at_most_one_revalidation() -> None:
    for _ in range(40):
        started, compiles, snapshot = _race_two_hits()
        assert started == 1 and compiles == 1
        assert snapshot["revalidations_started"] == 1
        assert snapshot["hit"] == 2


def test_a_revalidation_during_many_serves_neither_deadlocks_nor_tears() -> None:
    cache = _cache(every=4)
    _store(cache, FIRST)
    _store(cache, SECOND)
    slot = _slot(1)
    stop = Event()
    errors: list[BaseException] = []
    served = [0]
    served_lock = Lock()

    def compile_outcome(_source: str) -> FreshOutcome:
        time.sleep(0.002)
        return FreshOutcome.SUCCESS

    def worker(source: str) -> None:
        try:
            while not stop.is_set():
                decision = cache.begin(source)
                assert decision.eligible and decision.serve
                cache.start_revalidation(decision, compile_outcome=compile_outcome, slot=slot)
                with served_lock:
                    served[0] += 1
                snapshot = cache.snapshot()  # a consistent copy, never a torn one
                assert snapshot["entries"] == 2
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [Thread(target=worker, args=(s,)) for s in (FIRST, SECOND, FIRST, SECOND)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    _wait_for(lambda: cache.snapshot()["revalidation_in_flight"] == 0)
    assert not errors
    snapshot = cache.snapshot()
    assert snapshot["hit"] == served[0]
    assert snapshot["revalidations_started"] == snapshot["revalidation_match"] > 0
    assert slot.acquire(blocking=False)
    assert not cache.serving_blocked


# --- outcomes -----------------------------------------------------------------------------------


def test_a_mismatch_logs_error_counts_and_blocks_serving_for_every_entry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(every=1)
    _store(cache, FIRST)
    _store(cache, SECOND)
    stored_before = dict(cache._stored)  # noqa: SLF001
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _serve_and_revalidate(cache, FIRST, FreshOutcome.FAILURE)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "result=revalidation_mismatch" in message and "serving_blocked=true" in message
    snapshot = cache.snapshot()
    assert snapshot["revalidation_mismatch"] == 1 and snapshot["revalidation_match"] == 0
    assert cache.serving_blocked
    # The next request for any entry must compile.
    assert not cache.begin(FIRST).serve and not cache.begin(SECOND).serve
    assert cache.snapshot()["blocked_by_mismatch"] >= 2
    # The stored verdicts were not edited (the block is the only effect).
    assert dict(cache._stored) == stored_before  # noqa: SLF001


def test_nothing_unblocks_after_a_mismatch_neither_a_match_nor_a_new_store() -> None:
    cache = _cache(every=1)
    _store(cache, FIRST)
    _serve_and_revalidate(cache, FIRST, FreshOutcome.FAILURE)
    assert cache.serving_blocked
    # A later successful compile (shadow comparison / first store of another entry) ...
    _store(cache, SECOND)
    assert cache.serving_blocked
    # ... a late successful revalidation that was already in flight ...
    cache._complete_revalidation(  # noqa: SLF001
        cache._keys[0],
        0,
        1,
        FreshOutcome.SUCCESS,
        elapsed_ms=1.0,  # noqa: SLF001
    )
    assert cache.serving_blocked
    # ... and no new revalidation starts while blocked.
    decision = CacheDecision(
        eligible=True,
        key=cache._keys[0],
        key_index=0,
        serve=True,
        revalidate=True,  # noqa: SLF001
    )
    assert (
        cache.start_revalidation(
            decision, compile_outcome=lambda _s: FreshOutcome.SUCCESS, slot=_slot()
        )
        is None
    )
    assert not cache.begin(FIRST).serve and not cache.begin(SECOND).serve


def test_a_mismatch_found_while_serves_continue_blocks_the_next_one() -> None:
    cache = _cache(every=1)
    _store(cache)
    release = Event()
    entered = Event()

    def slow_failure(_source: str) -> FreshOutcome:
        entered.set()
        assert release.wait(5)
        return FreshOutcome.FAILURE

    thread = cache.start_revalidation(
        cache.begin(FIRST), compile_outcome=slow_failure, slot=_slot()
    )
    assert thread is not None and entered.wait(5)
    during = [cache.begin(FIRST).serve for _ in range(20)]  # still served: nothing is known yet
    assert all(during)
    release.set()
    thread.join(timeout=5)
    assert not cache.begin(FIRST).serve


def test_a_match_leaves_the_stored_verdict_untouched_and_only_updates_bookkeeping() -> None:
    now = [100.0]
    cache = _cache(every=1, clock=lambda: now[0])
    _store(cache)
    stored_before = dict(cache._stored)  # noqa: SLF001
    assert "last_revalidation_age_seconds" not in cache.snapshot()
    now[0] = 110.0
    _serve_and_revalidate(cache, FIRST, FreshOutcome.SUCCESS)
    now[0] = 135.0
    snapshot = cache.snapshot()
    assert dict(cache._stored) == stored_before  # noqa: SLF001
    assert snapshot["entries"] == 1 and snapshot["stored"] == 1
    assert snapshot["revalidation_match"] == 1
    assert snapshot["last_revalidation_age_seconds"] == 25
    assert not cache.serving_blocked and cache.begin(FIRST).serve


def test_a_timeout_or_interruption_is_inconclusive_never_a_mismatch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(every=1)
    _store(cache)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        _serve_and_revalidate(cache, FIRST, FreshOutcome.INCONCLUSIVE)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "result=revalidation_inconclusive" in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    snapshot = cache.snapshot()
    assert snapshot["revalidation_inconclusive"] == 1
    assert snapshot["revalidation_mismatch"] == 0 and snapshot["revalidation_match"] == 0
    assert not cache.serving_blocked
    assert cache.begin(FIRST).serve  # serving continues


def test_a_compiler_exception_is_inconclusive_and_frees_the_slot_and_the_flight() -> None:
    cache = _cache(every=1)
    _store(cache)
    slot = _slot(1)

    def broken(_source: str) -> FreshOutcome:
        raise RuntimeError("compiler bug")

    decision = cache.begin(FIRST)
    thread = cache.start_revalidation(decision, compile_outcome=broken, slot=slot)
    assert thread is not None
    thread.join(timeout=5)
    snapshot = cache.snapshot()
    assert snapshot["revalidation_inconclusive"] == 1 and snapshot["revalidation_in_flight"] == 0
    assert slot.acquire(blocking=False) and not cache.serving_blocked
    # and a new revalidation can start afterwards
    assert _serve_and_revalidate(cache, FIRST) is not None


def test_the_revalidation_compiles_the_allow_list_entry_not_request_bytes() -> None:
    cache = _cache(every=1)
    _store(cache, SECOND)
    seen: list[str] = []

    def compile_outcome(source: str) -> FreshOutcome:
        seen.append(source)
        return FreshOutcome.SUCCESS

    thread = cache.start_revalidation(
        cache.begin(SECOND), compile_outcome=compile_outcome, slot=_slot()
    )
    assert thread is not None
    thread.join(timeout=5)
    assert seen == [SECOND]


def test_a_decision_that_is_not_marked_for_revalidation_never_compiles() -> None:
    cache = _cache(every=50)
    _store(cache)
    _serve_and_revalidate(cache, FIRST)  # consumes the first-serve obligation
    decision = cache.begin(FIRST)
    assert decision.serve and not decision.revalidate
    assert (
        cache.start_revalidation(
            decision, compile_outcome=lambda _s: pytest.fail("not due"), slot=_slot()
        )
        is None
    )
    # A forged "revalidate" on a not-due entry is re-checked under the lock.
    forged = replace(decision, revalidate=True)
    assert (
        cache.start_revalidation(
            forged, compile_outcome=lambda _s: pytest.fail("not due"), slot=_slot()
        )
        is None
    )


def test_without_a_revalidation_interval_nothing_is_ever_revalidated() -> None:
    cache = _cache(every=None)
    _store(cache)
    decision = cache.begin(FIRST)
    assert decision.serve and not decision.revalidate
    assert "revalidate_every" not in cache.snapshot()
    assert (
        cache.start_revalidation(
            replace(decision, revalidate=True),
            compile_outcome=lambda _s: pytest.fail("revalidation is off"),
            slot=_slot(),
        )
        is None
    )


@pytest.mark.parametrize("bad", [0, -1, 10_001, True, 2.0, "3"])
def test_the_interval_is_validated_by_the_cache(bad: Any) -> None:
    with pytest.raises(ValueError, match="revalidate_every"):
        _cache(every=bad)


# --- counters and logs --------------------------------------------------------------------------


def test_snapshot_exposes_counters_interval_in_flight_and_age() -> None:
    cache = _cache(every=7)
    snapshot = cache.snapshot()
    for name in (
        "revalidations_started",
        "revalidation_match",
        "revalidation_mismatch",
        "revalidation_inconclusive",
        "revalidation_skipped_busy",
        "revalidation_skipped_no_slot",
    ):
        assert snapshot[name] == 0
    assert snapshot["revalidate_every"] == 7 and snapshot["revalidation_in_flight"] == 0
    assert "last_revalidation_age_seconds" not in snapshot
    # With revalidation off the snapshot has none of these keys.
    plain = _cache(every=None).snapshot()
    assert not [k for k in plain if k.startswith("revalidat") or k.startswith("last_reval")]


def test_log_lines_are_content_free_and_carry_the_required_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(every=2)
    _store(cache)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _serve_and_revalidate(cache, FIRST, FreshOutcome.SUCCESS)  # serve 1: due
        _serve_and_revalidate(cache, FIRST, FreshOutcome.SUCCESS)  # serve 2: not due
        slot = _slot()
        assert slot.acquire(blocking=False)
        _serve_and_revalidate(cache, FIRST, FreshOutcome.SUCCESS, slot=slot)
    lines = [r.getMessage() for r in caplog.records if "result=revalidation" in r.getMessage()]
    assert any("result=revalidation_started" in line for line in lines)
    match = next(line for line in lines if "result=revalidation_match" in line)
    for field in ("entry=", "elapsed_ms=", "served_since=", "key_index=0", "revalidate_every=2"):
        assert field in match
    assert any("result=revalidation_skipped_no_slot" in line for line in lines)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Mathlib" not in text and "theorem" not in text
    for key in cache._keys:  # noqa: SLF001
        assert key not in text and key[:12] not in text and key[:16] not in text
    entry = match.split("entry=")[1].split()[0]
    assert len(entry) == 12 and all(c in "0123456789abcdef" for c in entry)


def test_served_since_in_the_log_counts_serves_since_the_last_revalidation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(every=3)
    _store(cache)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        for _ in range(4):
            _serve_and_revalidate(cache, FIRST)
    started = [
        r.getMessage() for r in caplog.records if "result=revalidation_started" in r.getMessage()
    ]
    assert [line.split("served_since=")[1].split()[0] for line in started] == ["1", "3"]


# --- flags --------------------------------------------------------------------------------------

_SHADOW = "PALS_VERIFIER_RESULT_CACHE_SHADOW"
_ENABLED = "PALS_VERIFIER_RESULT_CACHE_ENABLED"
_REVALIDATE = "PALS_VERIFIER_RESULT_CACHE_REVALIDATE"
_EVERY = "PALS_VERIFIER_RESULT_CACHE_REVALIDATE_EVERY"


def _env(monkeypatch: pytest.MonkeyPatch, **flags: str) -> None:
    _set_required_environment(monkeypatch)
    for name in (_SHADOW, _ENABLED, _REVALIDATE, _EVERY):
        monkeypatch.delenv(name, raising=False)
    for name, value in flags.items():
        monkeypatch.setenv(name, value)


def test_revalidation_defaults_off_and_the_interval_defaults_to_twenty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch)
    settings = HttpVerifierRuntimeSettings.from_env()
    assert settings.result_cache_revalidate is False
    assert settings.result_cache_revalidate_every == REVALIDATE_EVERY_DEFAULT == 20
    fields = HttpVerifierRuntimeSettings.__dataclass_fields__
    assert fields["result_cache_revalidate"].default is False
    assert fields["result_cache_revalidate_every"].default == 20
    assert REVALIDATE_EVERY_MIN == 1 and REVALIDATE_EVERY_MAX == 10_000


def test_the_valid_flag_combinations_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    for flags, mode in (
        ({}, None),
        ({_SHADOW: "true"}, ResultCacheMode.SHADOW),
        ({_SHADOW: "true", _REVALIDATE: "true"}, ResultCacheMode.SHADOW),
        ({_SHADOW: "true", _ENABLED: "true", _REVALIDATE: "true"}, ResultCacheMode.SERVE),
    ):
        _env(monkeypatch, **flags)
        settings = HttpVerifierRuntimeSettings.from_env()
        if mode is not None:
            assert (
                resolve_result_cache_flags(
                    shadow=settings.result_cache_shadow,
                    enabled=settings.result_cache_enabled,
                    revalidate=settings.result_cache_revalidate,
                )
                is mode
            )


@pytest.mark.parametrize(
    "value", ["1", "True", "TRUE", "yes", "on", "", " true", "true ", "0", "false\n"]
)
def test_the_revalidate_flag_is_a_strict_boolean(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _env(monkeypatch, **{_SHADOW: "true", _REVALIDATE: value})
    with pytest.raises(ValueError, match=_REVALIDATE):
        HttpVerifierRuntimeSettings.from_env()


def test_serving_without_revalidation_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, **{_SHADOW: "true", _ENABLED: "true"})
    with pytest.raises(ValueError, match=_REVALIDATE):
        HttpVerifierRuntimeSettings.from_env()
    _env(monkeypatch, **{_SHADOW: "true", _ENABLED: "true", _REVALIDATE: "false"})
    with pytest.raises(ValueError, match=_REVALIDATE):
        HttpVerifierRuntimeSettings.from_env()
    # The existing rule still wins when the shadow flag is missing too.
    _env(monkeypatch, **{_ENABLED: "true", _REVALIDATE: "true"})
    with pytest.raises(ValueError, match=_SHADOW):
        HttpVerifierRuntimeSettings.from_env()


def test_revalidation_without_a_cache_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, **{_REVALIDATE: "true"})
    with pytest.raises(ValueError, match="requires"):
        HttpVerifierRuntimeSettings.from_env()
    _env(monkeypatch, **{_SHADOW: "false", _REVALIDATE: "true"})
    with pytest.raises(ValueError, match="requires"):
        HttpVerifierRuntimeSettings.from_env()
    with pytest.raises(ValueError):
        resolve_result_cache_flags(shadow=False, enabled=False, revalidate=True)


@pytest.mark.parametrize(
    ("value", "expected"), [("1", 1), ("20", 20), ("10000", 10_000), ("37", 37)]
)
def test_the_interval_accepts_the_bounded_range(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int
) -> None:
    _env(monkeypatch, **{_SHADOW: "true", _REVALIDATE: "true", _EVERY: value})
    assert HttpVerifierRuntimeSettings.from_env().result_cache_revalidate_every == expected


@pytest.mark.parametrize(
    "value",
    ["0", "10001", "-1", "020", "01", " 5", "5 ", "5.0", "1e2", "", "many", "+5", "٣", "5\n"],
)
def test_the_interval_is_parsed_strictly_even_when_revalidation_is_off(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    for flags in ({_SHADOW: "true", _REVALIDATE: "true"}, {}):
        _env(monkeypatch, **flags, **{_EVERY: value})
        with pytest.raises(ValueError, match=_EVERY):
            HttpVerifierRuntimeSettings.from_env()


def test_the_new_flag_names_are_not_credential_shaped() -> None:
    from pals_agent.lean_verifier.boundary import _CREDENTIAL_ENV_RE

    assert len({_SHADOW, _ENABLED, _REVALIDATE, _EVERY}) == 4
    for name in (_REVALIDATE, _EVERY):
        assert _CREDENTIAL_ENV_RE.search(name) is None


def test_the_revalidation_verifier_runs_under_the_dedicated_shorter_deadline() -> None:
    assert REVALIDATION_DEADLINE_SECONDS == 60.0
    verifier = LeanVerifier(timeout_seconds=300.0)
    short = http_runtime._revalidation_verifier(verifier, 300.0)  # noqa: SLF001
    assert isinstance(short, LeanVerifier) and short.timeout_seconds == 60.0
    assert verifier.timeout_seconds == 300.0  # real requests keep their deadline
    # A configured deadline below the cap is never raised.
    assert http_runtime._revalidation_verifier(verifier, 30.0).timeout_seconds == 30.0  # noqa: SLF001


# --- HTTP behaviour -----------------------------------------------------------------------------


class RevalidationVerifier:
    """Call 1 succeeds (and stores).  Later calls return ``later`` after waiting on ``gate``."""

    def __init__(self, later: VerificationResult | None = None, gate: Event | None = None) -> None:
        self.later = later or _success()
        self.gate = gate
        self.calls: list[str] = []
        self.entered = Event()
        self._lock = Lock()

    def verify(self, lean_code: str) -> VerificationResult:
        with self._lock:
            index = len(self.calls)
            self.calls.append(lean_code)
        if index == 0:
            return _success()
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(8)
        return self.later


def _idle(cache: VerifierResultCache) -> None:
    _wait_for(lambda: cache.snapshot()["revalidation_in_flight"] == 0)


def test_a_hit_is_not_delayed_by_a_slow_revalidation_and_keeps_the_wire_contract(
    tls_contexts: Any,
) -> None:
    gate = Event()
    verifier = RevalidationVerifier(gate=gate)
    cache = _cache(every=1)
    with _serving(tls_contexts, verifier, cache):
        first = _post(tls_contexts, FIRST, job="job-1")
        started = time.monotonic()
        hit = _post(tls_contexts, FIRST, job="job-2")
        elapsed = time.monotonic() - started
        assert verifier.entered.wait(5)  # the revalidation is really compiling ...
        assert cache.snapshot()["revalidation_in_flight"] == 1
        assert elapsed < 2.0  # ... and the response did not wait for it (it would block for 8 s)
        # More hits while it runs are still answered at once and counted as skipped_busy.
        again = _post(tls_contexts, FIRST, job="job-3")
        gate.set()
        _idle(cache)
    assert (first[0], first[2]) == (200, "compile")
    assert (hit[0], hit[2]) == (200, "cache") and (again[0], again[2]) == (200, "cache")
    assert set(hit[1]) == ATTESTATION_KEYS  # no new JSON keys
    assert hit[1]["proof_job_id"] == "job-2"
    assert len(verifier.calls) == 2  # one compile + exactly one revalidation
    snapshot = cache.snapshot()
    assert snapshot["revalidations_started"] == 1 and snapshot["revalidation_match"] == 1
    assert snapshot["revalidation_skipped_busy"] >= 1


def test_a_real_request_during_a_revalidation_gets_the_retryable_503(tls_contexts: Any) -> None:
    gate = Event()
    verifier = RevalidationVerifier(gate=gate)
    cache = _cache(every=1)
    with _serving(tls_contexts, verifier, cache):  # max_concurrent_compiles=1
        _post(tls_contexts, FIRST, job="job-1")
        _post(tls_contexts, FIRST, job="job-2")
        assert verifier.entered.wait(5)
        busy = _post(tls_contexts, SECOND, job="job-3")  # not cached: needs the one slot
        gate.set()
        _idle(cache)
        after = _post(tls_contexts, SECOND, job="job-4")
    assert busy[0] == 503 and busy[1]["error_code"] == "verifier_unavailable"
    assert busy[1]["retryable"] is True and busy[2] is None
    assert (after[0], after[2]) == (200, "compile")


def test_a_second_compile_slot_lets_real_requests_run_beside_a_revalidation(
    tls_contexts: Any,
) -> None:
    gate = Event()
    verifier = RevalidationVerifier(gate=gate)
    cache = _cache(every=1)
    with _serving(tls_contexts, verifier, cache, max_concurrent_compiles=2):
        _post(tls_contexts, FIRST, job="job-1")
        _post(tls_contexts, FIRST, job="job-2")
        assert verifier.entered.wait(5)
        result: list[tuple[int, dict[str, Any], str | None]] = []
        thread = Thread(target=lambda: result.append(_post(tls_contexts, SECOND, job="job-3")))
        thread.start()
        time.sleep(0.2)
        gate.set()
        thread.join(timeout=8)
        _idle(cache)
    assert result and result[0][0] == 200


def test_a_busy_verifier_skips_the_revalidation_without_delaying_the_hit(
    tls_contexts: Any,
) -> None:
    release = Event()
    inside = Event()

    class Holding:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def verify(self, lean_code: str) -> VerificationResult:
            self.calls.append(lean_code)
            if lean_code == SECOND:
                inside.set()
                assert release.wait(8)
            return _success()

    verifier = Holding()
    cache = _cache(every=1)
    with _serving(tls_contexts, verifier, cache):
        _post(tls_contexts, FIRST, job="job-1")  # stores FIRST
        slow: list[Any] = []
        thread = Thread(target=lambda: slow.append(_post(tls_contexts, SECOND, job="slow")))
        thread.start()
        assert inside.wait(5)  # the only compile slot is now busy with a real request
        started = time.monotonic()
        hit = _post(tls_contexts, FIRST, job="job-hit")
        elapsed = time.monotonic() - started
        release.set()
        thread.join(timeout=8)
    assert (hit[0], hit[2]) == (200, "cache") and elapsed < 2.0
    snapshot = cache.snapshot()
    assert snapshot["revalidation_skipped_no_slot"] == 1
    assert snapshot["revalidations_started"] == 0
    assert verifier.calls == [FIRST, SECOND]  # no revalidation compile happened
    assert slow[0][0] == 200


def test_a_mismatch_over_http_blocks_serving_and_the_next_request_compiles(
    tls_contexts: Any, caplog: pytest.LogCaptureFixture
) -> None:
    verifier = RevalidationVerifier(later=_failure())
    cache = _cache(every=1)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME), _serving(tls_contexts, verifier, cache):
        _post(tls_contexts, FIRST, job="job-1")
        hit = _post(tls_contexts, FIRST, job="job-2")  # served; the revalidation fails behind it
        _idle(cache)
        calls_before = len(verifier.calls)
        next_other = _post(tls_contexts, SECOND, job="job-3")
        next_same = _post(tls_contexts, FIRST, job="job-4")
    assert (hit[0], hit[2]) == (200, "cache")  # the response that triggered it is unchanged
    assert cache.serving_blocked
    assert (next_other[2], next_same[2]) == ("compile", "compile")
    assert len(verifier.calls) == calls_before + 2  # both really compiled
    assert cache.snapshot()["revalidation_mismatch"] == 1
    assert [r.levelno for r in caplog.records if "revalidation_mismatch" in r.getMessage()] == [
        logging.ERROR
    ]


@pytest.mark.parametrize("later", [_timeout_failure, _interrupted])
def test_a_revalidation_timeout_or_interruption_is_inconclusive_and_serving_continues(
    tls_contexts: Any, later: Callable[[], VerificationResult]
) -> None:
    verifier = RevalidationVerifier(later=later())
    cache = _cache(every=1)
    with _serving(tls_contexts, verifier, cache):
        _post(tls_contexts, FIRST, job="job-1")
        _post(tls_contexts, FIRST, job="job-2")
        _idle(cache)
        calls = len(verifier.calls)
        third = _post(tls_contexts, FIRST, job="job-3")
        _idle(cache)
    snapshot = cache.snapshot()
    assert snapshot["revalidation_inconclusive"] >= 1
    assert snapshot["revalidation_mismatch"] == 0 and not cache.serving_blocked
    assert (third[0], third[2]) == (200, "cache")
    assert len(verifier.calls) >= calls


def test_the_revalidation_uses_its_own_verifier_with_the_allow_list_source(
    tls_contexts: Any,
) -> None:
    main = RevalidationVerifier()
    short = RevalidationVerifier()
    cache = _cache(every=1)
    with _serving(tls_contexts, main, cache) as server:
        server.revalidation_verifier = short
        _post(tls_contexts, FIRST, job="job-1")
        _post(tls_contexts, FIRST, job="job-2")
        _wait_for(lambda: len(short.calls) == 1)
        _idle(cache)
    assert main.calls == [FIRST]
    assert short.calls == [FIRST]


def test_many_concurrent_hits_never_deadlock_and_always_restore_the_slot(
    tls_contexts: Any,
) -> None:
    class Fast:
        def __init__(self) -> None:
            self.calls = 0
            self._lock = Lock()

        def verify(self, lean_code: str) -> VerificationResult:
            with self._lock:
                self.calls += 1
            time.sleep(0.01)
            return _success()

    verifier = Fast()
    cache = _cache(every=2)
    out: list[tuple[int, str | None]] = []
    out_lock = Lock()
    with _serving(tls_contexts, verifier, cache, max_concurrent_compiles=2) as server:
        _post(tls_contexts, FIRST, job="seed")

        def hammer(index: int) -> None:
            for step in range(5):
                response = _post(tls_contexts, FIRST, job=f"job-{index}-{step}")
                with out_lock:
                    out.append((response[0], response[2]))

        threads = [Thread(target=hammer, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        _idle(cache)
        slots_free = [server.compile_slot.acquire(blocking=False) for _ in range(2)]
    assert out == [(200, "cache")] * 30
    assert all(slots_free)
    snapshot = cache.snapshot()
    assert snapshot["revalidations_started"] >= 1
    assert (
        snapshot["revalidations_started"]
        == snapshot["revalidation_match"] + snapshot["revalidation_inconclusive"]
    )
    assert verifier.calls == 1 + snapshot["revalidations_started"]


def test_without_a_cache_or_with_revalidation_off_nothing_changes_on_the_wire(
    tls_contexts: Any,
) -> None:
    verifier = RevalidationVerifier()
    cache = _cache(every=None)
    with _serving(tls_contexts, verifier, cache):
        _post(tls_contexts, FIRST, job="job-1")
        hit = _post(tls_contexts, FIRST, job="job-2")
        time.sleep(0.1)
    assert (hit[0], hit[2]) == (200, "cache") and len(verifier.calls) == 1
    assert SOURCE_HEADER == "Pals-Verification-Source"
