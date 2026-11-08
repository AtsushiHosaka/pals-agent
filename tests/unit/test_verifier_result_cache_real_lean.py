"""OPT-IN, REAL LEAN: the verifier result cache against the pinned Lean and a built Mathlib.

Skipped unless ``~/.elan/toolchains/leanprover--lean4---v4.32.0-rc1`` and the built Mathlib
packages (``PALS_TEST_MATHLIB_PACKAGES``) both exist, so CI without Lean never runs it.  Each
test compiles the x² template with ``import Mathlib`` (about 20 s per compile on a laptop), one
Lean process at a time.  ``lake`` is never run; ``tools/verifier_cache_real_lean.py`` explains
how the production ``LeanVerifier`` is pointed at the pinned ``lean`` binary directly.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from pals_agent.lean_verifier.result_cache import ResultCacheMode, result_cache_mode

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "verifier_cache_real_lean.py"
_spec = importlib.util.spec_from_file_location("verifier_cache_real_lean_tool", _TOOL)
assert _spec is not None and _spec.loader is not None
tool = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tool
_spec.loader.exec_module(tool)

pytestmark = pytest.mark.skipif(
    not tool.available(),
    reason="real-Lean test: pinned Lean v4.32.0-rc1 and a built Mathlib are required",
)


@pytest.fixture
def real_lean(tmp_path: Path) -> Any:
    adapter = tool.RealLeanAdapter(tmp_path)
    records = tool._Records()  # noqa: SLF001
    logger = logging.getLogger(tool.CACHE_LOGGER_NAME)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(records)
    try:
        with tool.tls_material() as tls:
            yield adapter, records, tls
    finally:
        logger.removeHandler(records)
        logger.setLevel(previous_level)
        adapter.close()


def test_shadow_only_compiles_twice_and_the_second_agrees_with_the_stored_verdict(
    real_lean: Any,
) -> None:
    adapter, records, tls = real_lean
    source = tool.allow_listed_sources()["x"]
    cache = tool.build_cache(result_cache_mode(shadow=True, enabled=False), adapter.normal)
    with tool.serving(tls, adapter, cache):
        session = tool.Session(tls[1], adapter, cache, records)
        first = session.post("first", source)
        second = session.post("second", source)
    assert (first["status"], first["source_header"], first["success"]) == (200, "compile", True)
    assert (second["status"], second["source_header"], second["success"]) == (200, "compile", True)
    assert len(adapter.calls) == 2
    assert "INFO:stored" in first["log_results"]
    assert "INFO:shadow_match" in second["log_results"]
    assert cache.snapshot().get("shadow_mismatch", 0) == 0


def test_serving_compiles_once_then_answers_from_the_cache_without_invoking_lean(
    real_lean: Any,
) -> None:
    adapter, records, tls = real_lean
    source = tool.allow_listed_sources()["x"]
    cache = tool.build_cache(result_cache_mode(shadow=True, enabled=True), adapter.normal)
    assert cache.mode is ResultCacheMode.SERVE
    with tool.serving(tls, adapter, cache):
        session = tool.Session(tls[1], adapter, cache, records)
        first = session.post("first", source)
        hits = [session.post("hit", source, job=f"hit-{i}") for i in range(3)]
        outside = session.post("outside", tool.not_allow_listed(source), job="o")
        failing = session.post("failing", tool.sorry_proof(source), job="f")
    assert (first["source_header"], first["lean_calls"]) == ("compile", 1)
    assert [(h["status"], h["source_header"], h["lean_calls"]) for h in hits] == [
        (200, "cache", 0)
    ] * 3
    assert all(h["echoed_job"] for h in hits)
    assert max(float(h["seconds"]) for h in hits) < float(first["seconds"]) / 10
    # One extra comment leaves the allow-list: compiled by Lean, never served from the cache.
    assert (outside["status"], outside["source_header"], outside["lean_calls"]) == (
        200, "compile", 1,
    )
    assert failing["status"] == 422 and failing["source_header"] == "compile"
    assert cache.snapshot()["entries"] == 1


def test_a_hit_is_instant_while_a_real_revalidation_compiles_and_then_matches(
    real_lean: Any,
) -> None:
    adapter, records, tls = real_lean
    source = tool.allow_listed_sources()["x"]
    cache = tool.build_cache(
        result_cache_mode(shadow=True, enabled=True), adapter.normal, revalidate_every=2
    )
    with tool.serving(tls, adapter, cache, adapter.revalidation_port()):
        session = tool.Session(tls[1], adapter, cache, records)
        first = session.post("first", source)
        hit = session.post("hit", source, job="hit-1")  # the first serve starts a revalidation
        tool.wait_for(lambda: cache.snapshot().get("revalidation_in_flight") == 1, "start")
        during = session.post("hit while revalidating", source, job="hit-2")
        tool.wait_for(lambda: cache.snapshot().get("revalidation_in_flight") == 0, "end")
    assert first["source_header"] == "compile"
    assert [(r["status"], r["source_header"], r["lean_calls"]) for r in (hit, during)] == [
        (200, "cache", 0)
    ] * 2
    assert max(float(r["seconds"]) for r in (hit, during)) < 0.5
    revalidations = [c for c in adapter.calls if c["mode"] == "revalidation"]
    assert len(revalidations) == 1 and revalidations[0]["success"]
    snapshot = cache.snapshot()
    assert snapshot["revalidation_match"] == 1 and snapshot.get("revalidation_mismatch", 0) == 0
    assert not cache.serving_blocked


def test_a_tampered_stored_verdict_is_caught_by_a_real_revalidation_and_blocks_serving(
    real_lean: Any,
) -> None:
    adapter, records, tls = real_lean
    bad = tool.wrong_lemma(tool.allow_listed_sources()["x"])  # real Lean rejects this
    cache = tool.build_cache(
        result_cache_mode(shadow=True, enabled=True),
        adapter.normal,
        allow_list=(bad,),
        revalidate_every=2,
    )
    cache._stored[cache._keys[0]] = "tampered-in-process"  # noqa: SLF001  (test only)
    with tool.serving(tls, adapter, cache, adapter.revalidation_port()):
        session = tool.Session(tls[1], adapter, cache, records)
        served = session.post("tampered hit", bad, job="t-1")
        tool.wait_for(
            lambda: cache.snapshot().get("revalidation_mismatch", 0) == 1, "mismatch"
        )
        after = session.post("after mismatch", bad, job="t-2")
    assert (served["status"], served["source_header"], served["lean_calls"]) == (200, "cache", 0)
    assert cache.serving_blocked
    assert (after["status"], after["source_header"], after["lean_calls"]) == (422, "compile", 1)
