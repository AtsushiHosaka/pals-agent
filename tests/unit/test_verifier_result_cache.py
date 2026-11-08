"""Shadow-first verifier result cache for the x² template (allow-list, flags, HTTP behaviour).

The Lean compiler is a stub here: these tests prove the cache's rules and the HTTP contract, not a
real Lean run.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import socket
import ssl
import string
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
from typing import Any

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_templates import (
    _bindings_for_prompt,
    render_x_squared_epsilon_delta,
    template_proof_for_request,
    template_proof_for_sketch,
    x_squared_worker_bindings,
)
from pals_agent.lean_verifier import result_cache as result_cache_module
from pals_agent.lean_verifier.http_runtime import HttpVerifierRuntimeSettings
from pals_agent.lean_verifier.http_server import (
    IsolatedVerifierHttpSettings,
    VerifierDeploymentBinding,
    create_server,
)
from pals_agent.lean_verifier.result_cache import (
    SOURCE_HEADER,
    VERIFIER_POLICY_VERSION,
    CacheDecision,
    CacheKeyComponents,
    FreshOutcome,
    ResultCacheMode,
    VerifierResultCache,
    build_result_cache,
    build_x_squared_allow_list,
    policy_modules_sha256,
    result_cache_mode,
)
from pals_agent.models import ProofRequest, RelatedDraftContext, VerificationResult
from tests.unit.test_http_verifier_runtime import _set_required_environment
from tests.unit.test_isolated_verifier_http_server import (
    _DEPLOYMENT_SHA,
    _RELEASE_ID,
    _admission_context,
    _create_certificates,
    _failure,
    _headers,
    _interrupted,
    _spki_sha256,
    _success,
    _timeout_failure,
)

ALLOW_LIST = build_x_squared_allow_list()
FIRST = ALLOW_LIST[0]
SECOND = ALLOW_LIST[1]
ATTESTATION_KEYS = {
    "lean_sha256",
    "proof_job_id",
    "result_artifact_uri",
    "schema_version",
    "verification_succeeded",
}
_BASE_COMPONENTS = CacheKeyComponents(
    lean_version="leanprover/lean4:v4.32.0-rc1",
    lean_toolchain_file_sha256="1" * 64,
    lake_manifest_sha256="2" * 64,
    verifier_toolchain_sha256="3" * 64,
    verifier_image_digest="sha256:" + "4" * 64,
    policy_version=VERIFIER_POLICY_VERSION,
    policy_sha256="5" * 64,
    options={"allow_sorry": False, "timeout_seconds": 300.0},
)


def _cache(
    mode: ResultCacheMode = ResultCacheMode.SHADOW,
    *,
    allow_list: tuple[str, ...] = ALLOW_LIST,
    **overrides: Any,
) -> VerifierResultCache:
    return VerifierResultCache(
        mode=mode,
        allow_list=allow_list,
        components=replace(_BASE_COMPONENTS, **overrides),
    )


def _compiled(cache: VerifierResultCache, source: str, outcome: FreshOutcome) -> CacheDecision:
    decision = cache.begin(source)
    cache.finish_compiled(decision, outcome)
    return decision


@pytest.fixture
def tls_contexts() -> Iterator[tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str]]:
    with tempfile.TemporaryDirectory(prefix="pals-mtls-", dir="/private/tmp") as directory:
        root = Path(directory)
        _create_certificates(root)
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.minimum_version = ssl.TLSVersion.TLSv1_3
        server.verify_mode = ssl.CERT_REQUIRED
        server.load_verify_locations(cafile=root / "ca.pem")
        server.load_cert_chain(root / "server.pem", root / "server.key")
        client = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=root / "ca.pem")
        client.minimum_version = ssl.TLSVersion.TLSv1_3
        client.load_cert_chain(root / "client.pem", root / "client.key")
        untrusted = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=root / "ca.pem")
        untrusted.minimum_version = ssl.TLSVersion.TLSv1_3
        yield server, client, untrusted, _spki_sha256((root / "client.der").read_bytes())


# --- the allow-list -----------------------------------------------------------------------------


def test_allow_list_is_rendered_by_the_real_renderer_and_equals_the_enumeration() -> None:
    enumeration = [render_x_squared_epsilon_delta(b) for b in x_squared_worker_bindings()]
    assert list(ALLOW_LIST) == enumeration
    assert len(set(ALLOW_LIST)) == len(ALLOW_LIST)
    header = "import Mathlib\n\nopen scoped Topology\n"
    assert all(source.startswith(header) for source in ALLOW_LIST)
    # Deterministic: a second build is byte-identical and in the same order.
    assert build_x_squared_allow_list() == ALLOW_LIST


def test_allow_list_has_exactly_one_source_per_ascii_letter() -> None:
    assert len(ALLOW_LIST) == 52 == len(string.ascii_letters)
    variables = {b.variable for b in x_squared_worker_bindings()}
    assert variables == set(string.ascii_letters)
    assert {(b.theorem, b.epsilon, b.delta) for b in x_squared_worker_bindings()} == {
        ("x2_continuous", "ε", "δ")
    }
    for b in x_squared_worker_bindings():
        assert b.moving == b.variable
        assert b.point == ("c" if b.variable == "a" else "a")


def test_enumeration_covers_everything_the_worker_can_render() -> None:
    allowed = set(ALLOW_LIST)
    context = RelatedDraftContext(
        source_draft_id="continuous_square",
        strategy_notes=(),
        sketch_steps=(),
        exact_equivalence=True,
        selected_proof_method="epsilon_delta",
    )
    reached: set[str] = set()
    for letter in string.ascii_letters:
        # Draft path: any ASCII letter the learner squared.
        request = ProofRequest(id="1", prompt=f"{letter}^2", related_draft_contexts=(context,))
        template = template_proof_for_request(request)
        assert template is not None
        assert template.bindings.variable == letter
        reached.add(template.lean_code)
        # The prompt reader on its own, for every letter.
        reached.add(render_x_squared_epsilon_delta(_bindings_for_prompt(f"{letter}^2")))
    # Grammar path: the variables the request grammar lists.
    for letter in "stuvwxy":
        grammar = template_proof_for_request(
            ProofRequest(id="1", prompt=f"{letter}^2 is continuous")
        )
        assert grammar is not None
        reached.add(grammar.lean_code)
    # Fallbacks: no letter, two letters, a letter that is not ASCII, the Sketch safety net.
    for prompt in ("what is continuity", "x^2 and y^2", "α² is continuous", ""):
        reached.add(render_x_squared_epsilon_delta(_bindings_for_prompt(prompt)))
    sketch = template_proof_for_sketch(
        ProofRequest(id="1", prompt="anything"),
        "theorem t : Continuous (fun x : ℝ => x ^ 2) := by\n  sorry\n",
    )
    assert sketch is not None
    reached.add(sketch.lean_code)
    assert reached == allowed
    assert len(reached) == 52


def test_a_one_character_difference_is_never_an_allow_list_entry() -> None:
    cache = _cache()
    base = FIRST
    assert cache.begin(base).eligible
    for index in range(len(base)):
        mutated = base[:index] + ("Z" if base[index] != "Z" else "Y") + base[index + 1 :]
        assert not cache.begin(mutated).eligible, index
        assert not cache.begin(base[:index] + base[index + 1 :]).eligible, index
    assert not cache.begin(base + " ").eligible
    assert not cache.begin(base + "\n").eligible
    assert not cache.begin(base.rstrip("\n")).eligible
    assert not cache.begin(base[1:]).eligible
    assert cache.snapshot().get("stored", 0) == 0


@pytest.mark.parametrize(
    "transform",
    [
        pytest.param(lambda s: s.replace("\n", "\r\n"), id="crlf"),
        pytest.param(lambda s: s.replace("  ", "\t", 1), id="tab"),
        pytest.param(lambda s: s.replace("  ", "  ", 1), id="nbsp"),
        pytest.param(lambda s: "﻿" + s, id="bom"),
        pytest.param(lambda s: s.replace("ε", "ϵ"), id="lunate-epsilon-homoglyph"),
        pytest.param(lambda s: s.replace("δ", "δ​", 1), id="zero-width-space"),
        pytest.param(lambda s: s.replace("ℝ", "R"), id="ascii-real"),
        pytest.param(lambda s: s + "-- trailing comment\n", id="comment"),
        pytest.param(lambda s: "/- x -/\n" + s, id="block-comment-first"),
        pytest.param(lambda s: s + "\n  sorry\n", id="appended-sorry"),
        pytest.param(lambda s: s + "\naxiom evil : False\n", id="appended-axiom"),
        pytest.param(lambda s: s + "\ntheorem extra : True := trivial\n", id="appended-theorem"),
        pytest.param(lambda s: s.replace("x2_continuous", "x2_continuouz"), id="renamed-theorem"),
        pytest.param(
            lambda s: s.replace("import Mathlib", "import Mathlib\nimport Lean"), id="import"
        ),
    ],
)
def test_poisoned_variants_are_not_allow_list_entries(transform: Callable[[str], str]) -> None:
    variant = transform(FIRST)
    assert variant != FIRST
    cache = _cache()
    decision = _compiled(cache, variant, FreshOutcome.SUCCESS)
    assert not decision.eligible
    snapshot = cache.snapshot()
    assert snapshot["entries"] == 0
    assert snapshot.get("stored", 0) == 0


def test_a_different_proof_under_the_same_theorem_name_is_not_cached() -> None:
    other = (
        "import Mathlib\n\ntheorem x2_continuous : Continuous (fun x : ℝ => x ^ 2) := by\n"
        "  exact continuous_pow 2\n"
    )
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    decision = cache.begin(other)
    assert not decision.eligible and not decision.serve


def test_a_lone_surrogate_source_is_ineligible_and_does_not_raise() -> None:
    cache = _cache()
    assert not cache.begin("import Mathlib\n\ud800").eligible


def test_the_decision_is_computed_from_the_received_bytes_only() -> None:
    # `begin` has no parameter other than the source: no header, field or id can name a key.
    import inspect

    assert list(inspect.signature(VerifierResultCache.begin).parameters) == ["self", "source"]
    cache = _cache(ResultCacheMode.SERVE)
    forged = CacheDecision(eligible=True, key="f" * 64, key_index=0, serve=True)
    cache.finish_compiled(forged, FreshOutcome.SUCCESS)
    assert cache.snapshot()["entries"] == 0
    assert cache.snapshot()["foreign_decision"] == 1


# --- key components -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"lean_version": "leanprover/lean4:v4.33.0"},
        {"lean_toolchain_file_sha256": "a" * 64},
        {"lake_manifest_sha256": "a" * 64},
        {"verifier_toolchain_sha256": "a" * 64},
        {"verifier_image_digest": "sha256:" + "a" * 64},
        {"policy_version": "pals.verifier-policy.v2"},
        {"policy_sha256": "a" * 64},
        {"options": {"allow_sorry": False, "timeout_seconds": 299.0}},
        {"options": {"allow_sorry": True, "timeout_seconds": 300.0}},
        {"options": {"allow_sorry": False, "timeout_seconds": 300.0, "extra": 1}},
    ],
    ids=lambda value: next(iter(value)) + str(value[next(iter(value))])[:12],
)
def test_a_change_of_any_key_component_is_a_miss(override: dict[str, Any]) -> None:
    original = _cache(ResultCacheMode.SERVE)
    changed = _cache(ResultCacheMode.SERVE, **override)
    _compiled(original, FIRST, FreshOutcome.SUCCESS)
    assert original.begin(FIRST).serve
    # Hand the stored entries of the original to a cache whose components differ.
    changed._stored.update(original._stored)  # noqa: SLF001
    assert changed._stored  # noqa: SLF001
    decision = changed.begin(FIRST)
    assert decision.eligible and not decision.serve
    # And with identical components the same hand-over serves (the control).
    same = _cache(ResultCacheMode.SERVE)
    same._stored.update(original._stored)  # noqa: SLF001
    assert same.begin(FIRST).serve
    assert changed._keys != original._keys  # noqa: SLF001


def test_keys_differ_per_source_and_the_source_hash_is_part_of_the_key() -> None:
    cache = _cache()
    assert len(set(cache._keys)) == 52  # noqa: SLF001
    key = result_cache_module._key_for(  # noqa: SLF001
        hashlib.sha256(FIRST.encode("utf-8")).hexdigest(), _BASE_COMPONENTS
    )
    assert key == cache._keys[0]  # noqa: SLF001
    other = result_cache_module._key_for("0" * 64, _BASE_COMPONENTS)  # noqa: SLF001
    assert other != key


def test_components_are_validated() -> None:
    overrides: tuple[dict[str, Any], ...] = (
        {"lake_manifest_sha256": "Z" * 64},
        {"verifier_image_digest": "b" * 64},
        {"policy_version": ""},
    )
    for override in overrides:
        with pytest.raises(ValueError):
            replace(_BASE_COMPONENTS, **override)


def test_real_components_come_from_the_verifier_and_the_policy_modules(tmp_path: Any) -> None:
    verifier = LeanVerifier(project_dir=None, timeout_seconds=300.0)
    options = result_cache_module.lean_verification_options(verifier)
    assert options["timeout_seconds"] == 300.0
    assert options["allow_sorry"] is False
    assert options["lean_threads"] == 1
    assert options["literal_admission_command"] is False
    other = result_cache_module.lean_verification_options(LeanVerifier(timeout_seconds=120.0))
    assert other != options
    digest = policy_modules_sha256()
    assert len(digest) == 64 and digest == policy_modules_sha256()
    cache = build_result_cache(
        mode=ResultCacheMode.SHADOW,
        verifier=verifier,
        lean_version="leanprover/lean4:v4.32.0-rc1",
        lean_toolchain_file_sha256="1" * 64,
        lake_manifest_sha256="2" * 64,
        verifier_toolchain_sha256="3" * 64,
        verifier_image_digest="sha256:" + "4" * 64,
    )
    assert cache is not None
    assert cache.allow_list_size == 52 == cache.max_entries
    assert (
        build_result_cache(
            mode=ResultCacheMode.OFF,
            verifier=verifier,
            lean_version="x",
            lean_toolchain_file_sha256="1" * 64,
            lake_manifest_sha256="2" * 64,
            verifier_toolchain_sha256="3" * 64,
            verifier_image_digest="sha256:" + "4" * 64,
        )
        is None
    )


# --- shadow and serve semantics -----------------------------------------------------------------


def test_shadow_mode_stores_the_first_success_and_compares_the_next(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(ResultCacheMode.SHADOW)
    with caplog.at_level(logging.INFO, logger=result_cache_module._LOGGER.name):  # noqa: SLF001
        first = _compiled(cache, FIRST, FreshOutcome.SUCCESS)
        second = _compiled(cache, FIRST, FreshOutcome.SUCCESS)
        _compiled(cache, SECOND, FreshOutcome.SUCCESS)
    assert first.eligible and not first.serve
    # Shadow mode never serves, even with a stored success for the key.
    assert second.eligible and not second.serve
    snapshot = cache.snapshot()
    assert snapshot["stored"] == 2
    assert snapshot["entries"] == 2
    assert snapshot["shadow_no_prior"] == 2
    assert snapshot["shadow_match"] == 1
    assert snapshot.get("shadow_mismatch", 0) == 0
    assert not cache.serving_blocked
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_failed_or_inconclusive_compile_is_never_stored() -> None:
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.FAILURE)
    _compiled(cache, FIRST, FreshOutcome.INCONCLUSIVE)
    assert cache.snapshot()["entries"] == 0
    assert not cache.begin(FIRST).serve
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    assert cache.begin(FIRST).serve


def test_a_mismatch_is_logged_at_error_counted_and_blocks_serving(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    assert cache.begin(FIRST).serve
    with caplog.at_level(logging.INFO, logger=result_cache_module._LOGGER.name):  # noqa: SLF001
        cache.finish_compiled(cache.begin(FIRST), FreshOutcome.FAILURE)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "result=shadow_mismatch" in message and "key_index=0" in message
    assert "serving_blocked=true" in message
    assert cache.snapshot()["shadow_mismatch"] == 1
    assert cache.serving_blocked
    # Blocked for every key, not only the one that disagreed.
    assert not cache.begin(FIRST).serve
    _compiled(cache, SECOND, FreshOutcome.SUCCESS)
    assert not cache.begin(SECOND).serve
    assert cache.snapshot()["blocked_by_mismatch"] >= 1


def test_an_inconclusive_compile_warns_but_does_not_block(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    with caplog.at_level(logging.INFO, logger=result_cache_module._LOGGER.name):  # noqa: SLF001
        cache.finish_compiled(cache.begin(FIRST), FreshOutcome.INCONCLUSIVE)
    assert [r.levelno for r in caplog.records if "shadow_inconclusive" in r.getMessage()] == [
        logging.WARNING
    ]
    assert cache.snapshot()["shadow_inconclusive"] == 1
    assert not cache.serving_blocked
    assert cache.begin(FIRST).serve


def test_log_lines_carry_no_source_key_or_job_content(caplog: pytest.LogCaptureFixture) -> None:
    cache = _cache(ResultCacheMode.SERVE)
    with caplog.at_level(logging.DEBUG, logger=result_cache_module._LOGGER.name):  # noqa: SLF001
        _compiled(cache, FIRST, FreshOutcome.SUCCESS)
        cache.begin(FIRST)
        cache.begin("example : True := by trivial")
        cache.finish_compiled(cache.begin(FIRST), FreshOutcome.FAILURE)
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert text
    assert "Mathlib" not in text and "theorem" not in text and "trivial" not in text
    for key in cache._keys:  # noqa: SLF001
        assert key not in text and key[:16] not in text
    assert hashlib.sha256(FIRST.encode()).hexdigest()[:16] not in text


def test_serve_mode_serves_only_a_stored_success_for_the_same_source() -> None:
    cache = _cache(ResultCacheMode.SERVE)
    assert not cache.begin(FIRST).serve
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    assert cache.begin(FIRST).serve
    assert not cache.begin(SECOND).serve
    assert not cache.begin(FIRST + "\n").serve


def test_a_restarted_cache_is_empty() -> None:
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    assert cache.begin(FIRST).serve
    restarted = _cache(ResultCacheMode.SERVE)
    assert restarted.snapshot()["entries"] == 0
    assert not restarted.begin(FIRST).serve


def test_memory_is_bounded_by_the_allow_list_size() -> None:
    cache = _cache(ResultCacheMode.SERVE)
    assert cache.max_entries == len(ALLOW_LIST)
    for source in ALLOW_LIST:
        for _ in range(3):
            _compiled(cache, source, FreshOutcome.SUCCESS)
    assert cache.snapshot()["entries"] == 52 == cache.max_entries
    assert cache.snapshot()["stored"] == 52
    small = _cache(ResultCacheMode.SERVE, allow_list=ALLOW_LIST[:2])
    assert small.max_entries == 2
    for source in ALLOW_LIST:
        _compiled(small, source, FreshOutcome.SUCCESS)
    assert small.snapshot()["entries"] == 2
    with pytest.raises(ValueError):
        _cache(allow_list=())
    with pytest.raises(ValueError):
        _cache(allow_list=(FIRST, FIRST))


def test_the_cache_has_no_flush_or_write_surface() -> None:
    public = {name for name in dir(VerifierResultCache) if not name.startswith("_")}
    assert public == {
        "allow_list_size",
        "begin",
        "finish_compiled",
        "mode",
        "serving_blocked",
        "snapshot",
    }


# --- concurrency --------------------------------------------------------------------------------


def test_simultaneous_identical_stores_leave_exactly_one_entry() -> None:
    cache = _cache(ResultCacheMode.SERVE)
    threads_count = 24
    barrier = Barrier(threads_count)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            decision = cache.begin(FIRST)
            cache.finish_compiled(decision, FreshOutcome.SUCCESS)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [Thread(target=run) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    snapshot = cache.snapshot()
    assert snapshot["entries"] == 1
    assert snapshot["stored"] == 1
    assert snapshot["stored"] + snapshot.get("shadow_match", 0) == threads_count
    assert snapshot.get("shadow_mismatch", 0) == 0


def test_hits_during_a_store_never_tear_and_never_deadlock() -> None:
    cache = _cache(ResultCacheMode.SERVE)
    start = Barrier(9)
    stop = Event()
    served: list[bool] = []
    served_lock = Lock()
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            start.wait(timeout=5)
            while not stop.is_set():
                decision = cache.begin(FIRST)
                assert decision.eligible and decision.key_index == 0
                with served_lock:
                    served.append(decision.serve)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    def writer() -> None:
        try:
            start.wait(timeout=5)
            for _ in range(200):
                cache.finish_compiled(cache.begin(FIRST), FreshOutcome.SUCCESS)
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
        finally:
            stop.set()

    threads = [Thread(target=reader) for _ in range(8)] + [Thread(target=writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    snapshot = cache.snapshot()
    # Every begin was counted exactly once as a hit or an eligible compile: no lost update.
    assert snapshot.get("hit", 0) + snapshot["eligible_compile"] == len(served) + 200
    assert snapshot["entries"] == 1 and snapshot["stored"] == 1
    assert cache.begin(FIRST).serve


# --- settings -----------------------------------------------------------------------------------


def test_flags_default_off_and_parse_like_the_other_strict_booleans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.delenv("PALS_VERIFIER_RESULT_CACHE_SHADOW", raising=False)
    monkeypatch.delenv("PALS_VERIFIER_RESULT_CACHE_ENABLED", raising=False)
    settings = HttpVerifierRuntimeSettings.from_env()
    assert settings.result_cache_shadow is False and settings.result_cache_enabled is False
    assert result_cache_mode(shadow=False, enabled=False) is ResultCacheMode.OFF
    # The dataclass default is off too.
    assert HttpVerifierRuntimeSettings.__dataclass_fields__["result_cache_shadow"].default is False
    assert HttpVerifierRuntimeSettings.__dataclass_fields__["result_cache_enabled"].default is False

    monkeypatch.setenv("PALS_VERIFIER_RESULT_CACHE_SHADOW", "true")
    settings = HttpVerifierRuntimeSettings.from_env()
    assert settings.result_cache_shadow is True and settings.result_cache_enabled is False
    assert result_cache_mode(shadow=True, enabled=False) is ResultCacheMode.SHADOW

    monkeypatch.setenv("PALS_VERIFIER_RESULT_CACHE_ENABLED", "true")
    settings = HttpVerifierRuntimeSettings.from_env()
    assert settings.result_cache_enabled is True
    assert result_cache_mode(shadow=True, enabled=True) is ResultCacheMode.SERVE


@pytest.mark.parametrize(
    "name", ["PALS_VERIFIER_RESULT_CACHE_SHADOW", "PALS_VERIFIER_RESULT_CACHE_ENABLED"]
)
@pytest.mark.parametrize(
    "value", ["1", "True", "TRUE", "yes", "on", "", " true", "true ", "0", "false\n"]
)
def test_a_flag_that_is_not_exactly_true_or_false_refuses_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("PALS_VERIFIER_RESULT_CACHE_SHADOW", "true")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        HttpVerifierRuntimeSettings.from_env()


def test_serving_cannot_be_enabled_without_the_shadow_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("PALS_VERIFIER_RESULT_CACHE_ENABLED", "true")
    monkeypatch.setenv("PALS_VERIFIER_RESULT_CACHE_SHADOW", "false")
    with pytest.raises(ValueError, match="requires"):
        HttpVerifierRuntimeSettings.from_env()
    monkeypatch.delenv("PALS_VERIFIER_RESULT_CACHE_SHADOW")
    with pytest.raises(ValueError, match="requires"):
        HttpVerifierRuntimeSettings.from_env()


def test_the_flag_names_are_not_credential_shaped_and_differ() -> None:
    from pals_agent.lean_verifier.boundary import _CREDENTIAL_ENV_RE

    names = ("PALS_VERIFIER_RESULT_CACHE_SHADOW", "PALS_VERIFIER_RESULT_CACHE_ENABLED")
    assert len(set(names)) == 2
    for name in names:
        assert _CREDENTIAL_ENV_RE.search(name) is None


# --- HTTP behaviour -----------------------------------------------------------------------------


class ScriptedVerifier:
    """Returns scripted results in order (the last one repeats) and records every call."""

    def __init__(self, *results: VerificationResult) -> None:
        self.results = list(results) or [_success()]
        self.calls: list[str] = []
        self._lock = Lock()

    def verify(self, lean_code: str) -> VerificationResult:
        with self._lock:
            self.calls.append(lean_code)
            index = min(len(self.calls), len(self.results)) - 1
            return self.results[index]


@contextmanager
def _serving(
    tls: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    verifier: Any,
    cache: VerifierResultCache | None,
    *,
    max_concurrent_compiles: int = 1,
) -> Iterator[Any]:
    server_context, _, _, client_spki_sha256 = tls
    settings = IsolatedVerifierHttpSettings(
        bind_host="127.0.0.1",
        binding=VerifierDeploymentBinding(
            release_id=_RELEASE_ID,
            deployment_binding_sha256=_DEPLOYMENT_SHA,
            verifier_image_digest="sha256:" + "b" * 64,
            verifier_toolchain_sha256="c" * 64,
        ),
        ssl_context=server_context,
        reconciler_client_spki_sha256=client_spki_sha256,
        reconciler_client_spiffe_uri="spiffe://pals/local/verified-reconciler",
        recipe_admission_context=_admission_context(),
        max_concurrent_compiles=max_concurrent_compiles,
    )
    server = create_server(settings, verifier=verifier, result_cache=cache)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def _post(
    tls: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str],
    source: str,
    *,
    job: str = "proof-1",
    extra_fields: dict[str, object] | None = None,
    extra_headers: dict[str, str] | None = None,
    release_id: str | None = None,
) -> tuple[int, dict[str, Any], str | None]:
    body = json.dumps(
        {
            "lean_code": source,
            "proof_job_id": job,
            "result_artifact_uri": f"s3://bucket/proof-jobs/{job}/result.lean",
            "schema_version": "pals.isolated-verifier-request.v1",
            **(extra_fields or {}),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    extra = "".join(f"{k}: {v}\r\n" for k, v in (extra_headers or {}).items()).encode("ascii")
    raw_request = (
        b"POST /v1/verify HTTP/1.1\r\n"
        + _headers(release_id=release_id)
        + extra
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )
    with (
        socket.create_connection(("127.0.0.1", 18117), timeout=5) as raw,
        tls[1].wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(raw_request)
        response = http.client.HTTPResponse(connection)
        response.begin()
        content = response.read()
        assert response.getheader("Pals-Release-Id") == str(_RELEASE_ID)
        return response.status, json.loads(content), response.getheader(SOURCE_HEADER)


def _get_ready(tls: tuple[ssl.SSLContext, ssl.SSLContext, ssl.SSLContext, str]) -> Any:
    with (
        socket.create_connection(("127.0.0.1", 18117), timeout=5) as raw,
        tls[1].wrap_socket(raw, server_hostname="verifier.internal") as connection,
    ):
        connection.sendall(b"GET /ready HTTP/1.1\r\n" + _headers() + b"\r\n")
        response = http.client.HTTPResponse(connection)
        response.begin()
        response.read()
        return response


def test_without_a_cache_every_compiled_response_says_compile_and_the_body_is_unchanged(
    tls_contexts: Any,
) -> None:
    verifier = ScriptedVerifier(_success(), _failure(), _timeout_failure(), _interrupted())
    with _serving(tls_contexts, verifier, None):
        ok = _post(tls_contexts, FIRST, job="job-a")
        rejected = _post(tls_contexts, FIRST, job="job-b")
        timeout = _post(tls_contexts, FIRST, job="job-c")
        interrupted = _post(tls_contexts, FIRST, job="job-d")
        ready = _get_ready(tls_contexts)
    assert [r[0] for r in (ok, rejected, timeout, interrupted)] == [200, 422, 504, 503]
    assert [r[2] for r in (ok, rejected, timeout, interrupted)] == ["compile"] * 4
    assert set(ok[1]) == ATTESTATION_KEYS
    assert ok[1] == {
        "lean_sha256": hashlib.sha256(FIRST.encode()).hexdigest(),
        "proof_job_id": "job-a",
        "result_artifact_uri": "s3://bucket/proof-jobs/job-a/result.lean",
        "schema_version": "pals.verifier-attestation.v1",
        "verification_succeeded": True,
    }
    assert ready.getheader(SOURCE_HEADER) is None
    assert len(verifier.calls) == 4


def test_requests_that_never_reach_the_compiler_carry_no_source_header(tls_contexts: Any) -> None:
    verifier = ScriptedVerifier()
    with _serving(tls_contexts, verifier, _cache(ResultCacheMode.SERVE)):
        wrong_binding = _post(tls_contexts, FIRST, release_id="wrong")
        extra_field = _post(tls_contexts, FIRST, extra_fields={"verification_source": "cache"})
    assert wrong_binding[0] == 409 and wrong_binding[2] is None
    assert extra_field[0] == 400 and extra_field[2] is None
    assert verifier.calls == []


def test_shadow_mode_always_compiles_and_never_changes_the_response(tls_contexts: Any) -> None:
    results = (_success(), _success(), _failure(), _success())
    plain_verifier = ScriptedVerifier(*results)
    shadow_verifier = ScriptedVerifier(*results)
    cache = _cache(ResultCacheMode.SHADOW)
    with _serving(tls_contexts, plain_verifier, None):
        plain = [_post(tls_contexts, FIRST, job=f"job-{i}") for i in range(4)]
    with _serving(tls_contexts, shadow_verifier, cache):
        shadow = [_post(tls_contexts, FIRST, job=f"job-{i}") for i in range(4)]
    assert shadow == plain
    assert [r[0] for r in shadow] == [200, 200, 422, 200]
    assert [r[2] for r in shadow] == ["compile"] * 4
    assert len(shadow_verifier.calls) == 4
    snapshot = cache.snapshot()
    assert snapshot["stored"] == 1 and snapshot["shadow_match"] == 2
    # The 422 disagreed with the stored success: visible, counted and blocking.
    assert snapshot["shadow_mismatch"] == 1
    assert cache.serving_blocked


def test_shadow_mode_leaves_other_sources_alone(tls_contexts: Any) -> None:
    verifier = ScriptedVerifier()
    cache = _cache(ResultCacheMode.SHADOW)
    with _serving(tls_contexts, verifier, cache):
        response = _post(tls_contexts, "example : True := by trivial")
    assert response[0] == 200 and response[2] == "compile"
    snapshot = cache.snapshot()
    assert snapshot["ineligible"] == 1 and snapshot["entries"] == 0


def test_serve_mode_answers_a_stored_success_without_compiling(tls_contexts: Any) -> None:
    verifier = ScriptedVerifier()
    cache = _cache(ResultCacheMode.SERVE)
    with _serving(tls_contexts, verifier, cache):
        first = _post(tls_contexts, FIRST, job="job-1")
        second = _post(tls_contexts, FIRST, job="job-2")
        third = _post(tls_contexts, FIRST, job="job-3")
    assert (first[0], first[2]) == (200, "compile")
    assert (second[0], second[2]) == (200, "cache")
    assert (third[0], third[2]) == (200, "cache")
    assert len(verifier.calls) == 1
    # The attestation is rebuilt from the new request: a stored one is never replayed.
    assert set(second[1]) == ATTESTATION_KEYS
    assert second[1] == {
        "lean_sha256": hashlib.sha256(FIRST.encode()).hexdigest(),
        "proof_job_id": "job-2",
        "result_artifact_uri": "s3://bucket/proof-jobs/job-2/result.lean",
        "schema_version": "pals.verifier-attestation.v1",
        "verification_succeeded": True,
    }
    assert third[1]["proof_job_id"] == "job-3"
    assert cache.snapshot()["hit"] == 2


def test_serve_mode_does_not_use_a_compile_slot_for_a_hit(tls_contexts: Any) -> None:
    release = Event()
    started = Event()

    class Holding:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def verify(self, lean_code: str) -> VerificationResult:
            self.calls.append(lean_code)
            started.set()
            assert release.wait(timeout=5)
            return _success()

    verifier = Holding()
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    with _serving(tls_contexts, verifier, cache):
        slow: list[tuple[int, dict[str, Any], str | None]] = []
        thread = Thread(target=lambda: slow.append(_post(tls_contexts, SECOND, job="slow")))
        thread.start()
        assert started.wait(timeout=5)
        hit = _post(tls_contexts, FIRST, job="fast")  # the only slot is busy; a hit needs none
        busy = _post(tls_contexts, "example : True := trivial", job="busy")
        release.set()
        thread.join(timeout=5)
    assert (hit[0], hit[2]) == (200, "cache")
    assert busy[0] == 503 and busy[1]["error_code"] == "verifier_unavailable" and busy[2] is None
    assert slow[0][0] == 200 and slow[0][2] == "compile"


def test_a_failed_compile_is_not_stored_and_a_later_success_is(tls_contexts: Any) -> None:
    verifier = ScriptedVerifier(_failure(), _timeout_failure(), _success())
    cache = _cache(ResultCacheMode.SERVE)
    with _serving(tls_contexts, verifier, cache):
        responses = [_post(tls_contexts, FIRST, job=f"job-{i}") for i in range(5)]
    assert [(r[0], r[2]) for r in responses] == [
        (422, "compile"),
        (504, "compile"),
        (200, "compile"),
        (200, "cache"),
        (200, "cache"),
    ]
    assert len(verifier.calls) == 3
    assert cache.snapshot()["stored"] == 1


def test_after_a_mismatch_serving_stops_and_every_request_compiles_again(
    tls_contexts: Any, caplog: pytest.LogCaptureFixture
) -> None:
    verifier = ScriptedVerifier(_success(), _failure(), _success())
    cache = _cache(ResultCacheMode.SERVE)
    # Simulate the race that makes a fresh compile disagree with a stored success: two requests
    # missed together, the first stored, the second came back as a rejection.
    decision_a = cache.begin(FIRST)
    decision_b = cache.begin(FIRST)
    cache.finish_compiled(decision_a, FreshOutcome.SUCCESS)
    with caplog.at_level(logging.ERROR, logger=result_cache_module._LOGGER.name):  # noqa: SLF001
        cache.finish_compiled(decision_b, FreshOutcome.FAILURE)
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1
    assert cache.serving_blocked
    with _serving(tls_contexts, verifier, cache):
        responses = [_post(tls_contexts, FIRST, job=f"job-{i}") for i in range(3)]
    assert [(r[0], r[2]) for r in responses] == [
        (200, "compile"),
        (422, "compile"),
        (200, "compile"),
    ]
    assert len(verifier.calls) == 3


def test_a_client_cannot_name_a_cache_key_or_force_a_hit(tls_contexts: Any) -> None:
    verifier = ScriptedVerifier()
    cache = _cache(ResultCacheMode.SERVE)
    # Warm only the first template, then ask for a different source while claiming the cache.
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    key = cache._keys[0]  # noqa: SLF001
    claims = {
        SOURCE_HEADER: "cache",
        "Pals-Cache-Key": key,
        "X-Cache-Hit": "true",
        "Cache-Control": "only-if-cached",
        "If-None-Match": key,
    }
    poisoned = FIRST + "\naxiom evil : False\n"
    sorry = FIRST.replace("simpa [Real.dist_eq] using hlt", "sorry")
    assert sorry != FIRST
    with _serving(tls_contexts, verifier, cache):
        results = [
            _post(tls_contexts, poisoned, job="p1", extra_headers=claims),
            _post(tls_contexts, sorry, job="p2", extra_headers=claims),
            _post(tls_contexts, SECOND, job="p3", extra_headers=claims),
            _post(tls_contexts, "x", job="p4", extra_fields={"cache_key": key}),
            _post(tls_contexts, FIRST, job="p5", extra_fields={"verification_source": "cache"}),
        ]
    assert [(r[0], r[2]) for r in results[:3]] == [(200, "compile")] * 3
    assert (results[3][0], results[3][2]) == (400, None)
    assert (results[4][0], results[4][2]) == (400, None)
    # Only the bytes the verifier received decide: the three non-matching sources compiled.
    assert verifier.calls == [poisoned, sorry, SECOND]
    snapshot = cache.snapshot()
    assert snapshot["entries"] == 2  # FIRST (pre-warmed) and SECOND (stored by its own compile)
    assert snapshot["ineligible"] == 2


def test_a_client_header_cannot_turn_a_compile_into_a_cache_answer_for_a_stored_source(
    tls_contexts: Any,
) -> None:
    # The converse: for an allow-listed source with nothing stored, a lying header still compiles.
    verifier = ScriptedVerifier()
    cache = _cache(ResultCacheMode.SERVE)
    with _serving(tls_contexts, verifier, cache):
        response = _post(tls_contexts, FIRST, extra_headers={SOURCE_HEADER: "cache"})
    assert (response[0], response[2]) == (200, "compile")
    assert len(verifier.calls) == 1


def test_two_simultaneous_identical_requests_both_compile_and_store_once(
    tls_contexts: Any,
) -> None:
    both_inside = Barrier(2)

    class Rendezvous:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self._lock = Lock()

        def verify(self, lean_code: str) -> VerificationResult:
            with self._lock:
                self.calls.append(lean_code)
            both_inside.wait(timeout=5)  # neither returns until both are compiling
            return _success()

    verifier = Rendezvous()
    cache = _cache(ResultCacheMode.SERVE)
    out: list[tuple[int, dict[str, Any], str | None]] = []
    out_lock = Lock()

    def request(job: str) -> None:
        response = _post(tls_contexts, FIRST, job=job)
        with out_lock:
            out.append(response)

    with _serving(tls_contexts, verifier, cache, max_concurrent_compiles=2):
        threads = [Thread(target=request, args=(f"job-{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads)
        later = _post(tls_contexts, FIRST, job="job-later")
    assert sorted((r[0], r[2]) for r in out) == [(200, "compile"), (200, "compile")]
    assert {r[1]["proof_job_id"] for r in out} == {"job-0", "job-1"}
    assert len(verifier.calls) == 2
    snapshot = cache.snapshot()
    assert snapshot["stored"] == 1 and snapshot["shadow_match"] == 1
    assert snapshot.get("shadow_mismatch", 0) == 0
    assert (later[0], later[2]) == (200, "cache")


def test_a_cache_bug_cannot_change_the_verdict_path(
    tls_contexts: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    verifier = ScriptedVerifier()
    cache = _cache(ResultCacheMode.SERVE)

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(cache, "begin", broken)
    with _serving(tls_contexts, verifier, cache):
        response = _post(tls_contexts, FIRST)
    assert (response[0], response[2]) == (200, "compile")
    assert len(verifier.calls) == 1

    healthy = _cache(ResultCacheMode.SERVE)
    monkeypatch.setattr(healthy, "finish_compiled", broken)
    verifier = ScriptedVerifier(_failure())
    with _serving(tls_contexts, verifier, healthy):
        failed = _post(tls_contexts, FIRST)
    assert (failed[0], failed[2]) == (422, "compile")


def test_a_wrong_release_binding_never_reaches_the_cache(tls_contexts: Any) -> None:
    verifier = ScriptedVerifier()
    cache = _cache(ResultCacheMode.SERVE)
    _compiled(cache, FIRST, FreshOutcome.SUCCESS)
    with _serving(tls_contexts, verifier, cache):
        response = _post(tls_contexts, FIRST, release_id="018a3b10-514d-4d6d-845e-000000000000")
    assert response[0] == 409 and response[2] is None
    assert cache.snapshot().get("hit", 0) == 0
