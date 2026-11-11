"""Review 3, item 1: stage 0 refuses to start without a real OS containment backend.

CI runs on Linux, where this module has no backend (the production verifier's Landlock/seccomp is
the real one): everything that launches Lean must fail closed there.  `PALS_LEAN_SANDBOX=off`
must not silently disable it; only the in-process, test-only switch may.
"""

from pathlib import Path

import pytest

from pals_agent import automation_portfolio as ap
from pals_agent import general_recipe_lane as lane
from pals_agent import sandbox, stage0


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("PALS_LEAN_SANDBOX", raising=False)
    monkeypatch.setattr(sandbox, "_TEST_MODE", None)


def darwin(monkeypatch, *, exists=True):
    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox, "SANDBOX_EXEC", "/usr/bin/true" if exists else "/nonexistent/x")


def linux(monkeypatch):
    monkeypatch.setattr(sandbox.sys, "platform", "linux")


ISO = sandbox.Isolation("/x/bin/lean", "/x/lib")


def test_linux_has_no_backend_and_every_entry_point_fails_closed(monkeypatch, tmp_path):
    linux(monkeypatch)
    assert not sandbox.available()
    with pytest.raises(sandbox.ContainmentUnavailable):
        sandbox.require_containment()
    with pytest.raises(sandbox.ContainmentUnavailable):
        sandbox.command(["lean", "x.lean"], ISO, str(tmp_path))
    runner = lane.LeanRunner("/x/bin/lean", "/x/lib", 10.0)
    with pytest.raises(sandbox.ContainmentUnavailable):
        ap.WarmWorker(runner, Path("scripts/eval/warm_worker.lean"))
    with pytest.raises(sandbox.ContainmentUnavailable):
        stage0.Stage0(object(), [], None, require_flags=False)  # type: ignore[arg-type]


def test_darwin_with_sandbox_exec_is_contained(monkeypatch, tmp_path):
    darwin(monkeypatch)
    assert sandbox.available()
    sandbox.require_containment()
    assert sandbox.command(["lean", "x"], ISO, str(tmp_path))[0] == sandbox.SANDBOX_EXEC


def test_darwin_without_sandbox_exec_fails_closed(monkeypatch):
    darwin(monkeypatch, exists=False)
    with pytest.raises(sandbox.ContainmentUnavailable):
        sandbox.require_containment()


@pytest.mark.parametrize("value", ["off", "0", "false", "OFF"])
def test_the_environment_cannot_switch_containment_off(monkeypatch, tmp_path, value):
    darwin(monkeypatch)
    monkeypatch.setenv("PALS_LEAN_SANDBOX", value)
    assert not sandbox.available()
    with pytest.raises(sandbox.ContainmentUnavailable):
        sandbox.command(["lean", "x"], ISO, str(tmp_path))
    with pytest.raises(sandbox.ContainmentUnavailable):
        sandbox.require_containment()


def test_only_the_in_process_test_switch_allows_an_unsandboxed_run(monkeypatch, tmp_path):
    linux(monkeypatch)
    monkeypatch.setenv("PALS_LEAN_SANDBOX_TEST_ONLY", "1")  # an env var must not work
    monkeypatch.setenv("PALS_LEAN_SANDBOX", "off")
    with pytest.raises(sandbox.ContainmentUnavailable):
        sandbox.require_containment()
    with sandbox.test_only_unsandboxed():
        assert sandbox.command(["lean", "x"], ISO, str(tmp_path)) == ["lean", "x"]
        assert "UNSANDBOXED" in sandbox.describe()
    with pytest.raises(sandbox.ContainmentUnavailable):  # restored on exit
        sandbox.require_containment()


def test_the_assume_contained_switch_is_for_fakes_only(monkeypatch, tmp_path):
    linux(monkeypatch)
    with sandbox.test_only_assume_contained():
        sandbox.require_containment()  # lets Stage0 be built around a fake worker
        with pytest.raises(sandbox.ContainmentUnavailable):  # but never launches a bare process
            sandbox.command(["lean", "x"], ISO, str(tmp_path))
