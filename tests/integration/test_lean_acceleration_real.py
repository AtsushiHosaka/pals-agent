"""Real installed Lean/Mathlib checks; opt in with an explicit shared workspace."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.lean_environment import LakeEnvironmentCache, VerificationTiming
from tools.lean_acceleration.benchmark import (
    INVALID_SOURCE,
    check_concurrency_and_reset,
    load_corpus,
    source_for,
    verifier_for,
)


def _runtime() -> dict[str, Path]:
    project = os.environ.get("PALS_ACCELERATION_REAL_PROJECT")
    lean = os.environ.get("PALS_ACCELERATION_REAL_LEAN")
    lake = os.environ.get("PALS_ACCELERATION_REAL_LAKE")
    if not (project and lean and lake):
        pytest.skip("set PALS_ACCELERATION_REAL_PROJECT/LEAN/LAKE for real pinned compiler checks")
    paths = {"project_dir": Path(project), "lean_binary": Path(lean), "lake_binary": Path(lake)}
    assert paths["project_dir"].is_dir()
    assert paths["lean_binary"].is_file()
    assert paths["lake_binary"].is_file()
    return paths


@pytest.mark.parametrize("case", load_corpus(), ids=lambda case: case["id"])
def test_real_same_corpus_baseline_and_environment_hit(case: dict[str, object]) -> None:
    runtime = _runtime()
    events: list[VerificationTiming] = []
    baseline = verifier_for(cache=None, events=events, **runtime)
    assert baseline.verify(source_for(case, narrow=False)).success
    source = source_for(case, narrow=True)
    assert baseline.verify(source).success
    events.clear()
    cached = verifier_for(cache=LakeEnvironmentCache(), events=events, **runtime)
    assert cached.verify(source).success
    assert cached.verify(source).success
    assert [e.cache_status for e in events if e.stage == "environment_prepare"] == ["miss", "hit"]
    assert sum(e.stage == "compile" for e in events) == 2


def test_real_concurrent_invalid_source_and_lifecycle_reset() -> None:
    result = check_concurrency_and_reset(**_runtime())
    assert result["concurrent_valid_success"]
    assert not result["concurrent_invalid_success"]
    assert result["after_clear_prepare_statuses"] == ["miss"]


def test_real_elan_proxy_path_hits_and_every_request_still_compiles() -> None:
    project = os.environ.get("PALS_ACCELERATION_REAL_PROJECT")
    elan_home = os.environ.get("PALS_ACCELERATION_REAL_ELAN_HOME")
    if not (project and elan_home):
        pytest.skip("set PALS_ACCELERATION_REAL_PROJECT/ELAN_HOME for the production proxy path")
    proxies = Path(elan_home) / "bin"
    events: list[VerificationTiming] = []
    verifier = LeanVerifier(
        project_dir=Path(project), lean_binary=str(proxies / "lean"),
        lake_binary=str(proxies / "lake"), elan_home=elan_home,
        child_path=f"{proxies}:/usr/local/bin:/usr/bin:/bin", timeout_seconds=120,
        lake_environment_cache=LakeEnvironmentCache(), timing_observer=events.append,
    )
    source = source_for(load_corpus()[0], narrow=True)
    assert verifier.verify(source).success
    assert verifier.verify(source).success
    assert not verifier.verify(INVALID_SOURCE).success
    assert [e.cache_status for e in events if e.stage == "environment_prepare"] == [
        "miss", "hit", "hit",
    ]
