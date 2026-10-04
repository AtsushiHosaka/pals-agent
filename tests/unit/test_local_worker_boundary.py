from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pals_agent import local_worker_boundary as boundary


def context(monkeypatch):
    for name, value in {
        "PALS_ENV": "local",
        "PALS_LOCAL_WORKER_NETWORK_GUARD": "1",
        "PALS_API_BASE_URL": "http://api:8000",
        "PALS_AWS_ENDPOINT_URL": "http://localstack:4566",
    }.items():
        monkeypatch.setenv(name, value)


def test_rules_block_both_database_ports_and_both_imds_families():
    rules = boundary.rule_set("55432")
    assert "table inet pals_worker" in rules
    assert "type filter hook output priority -150; policy accept;" in rules
    assert "tcp dport { 5432, 55432 } reject with tcp reset" in rules
    assert "ip daddr 169.254.169.254 reject" in rules
    assert "ip6 daddr fd00:ec2::254 reject" in rules
    assert "tcp dport { 5432, 65432 }" in boundary.rule_set("65432")
    assert "tcp dport { 5432 }" in boundary.rule_set("5432")


@pytest.mark.parametrize("value", ["0", "65536", "１２", "55432;accept", "", "-1"])
def test_invalid_port_cannot_enter_ruleset(value):
    with pytest.raises(ValueError):
        boundary.rule_set(value)


def test_nft_failure_never_starts_worker_or_attempts_privilege_drop(monkeypatch):
    context(monkeypatch)
    monkeypatch.setattr(boundary.os, "geteuid", lambda: 0)
    monkeypatch.setattr(boundary, "status_fields", lambda: {"CapEff": hex(boundary._STARTUP_CAPS)})

    def reject(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(boundary.subprocess, "run", reject)
    monkeypatch.setattr(boundary.os, "execv", lambda *_: pytest.fail("must not exec"))
    with pytest.raises(subprocess.CalledProcessError):
        boundary.start(["pals-agent", "worker"])


@pytest.mark.parametrize("existing_table", [False, True])
def test_installs_rules_before_irreversible_privilege_drop(monkeypatch, existing_table):
    context(monkeypatch)
    monkeypatch.setattr(boundary.os, "geteuid", lambda: 0)
    monkeypatch.setattr(boundary, "status_fields", lambda: {"CapEff": hex(boundary._STARTUP_CAPS)})
    calls = []

    def install(args, **kwargs):
        if args == ["/usr/sbin/nft", "-j", "list", "tables"]:
            tables = (
                [{"table": {"family": "inet", "name": "pals_worker"}}] if existing_table else []
            )
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"nftables": tables}))
        assert args == ["/usr/sbin/nft", "-f", "-"]
        assert kwargs["input"].startswith("delete table inet pals_worker\n") == existing_table
        assert kwargs["input"].count("table inet pals_worker {") == 1
        assert "flush ruleset" not in kwargs["input"]
        assert kwargs["check"] is True and kwargs["timeout"] == 10
        assert "tcp dport" in kwargs["input"]
        calls.append("rules")

    def drop(path, args):
        assert calls == ["rules"] and path == "/usr/bin/setpriv"
        for option in (
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--no-new-privs",
            "--reuid=65532",
            "--regid=65532",
            "--clear-groups",
        ):
            assert option in args
        assert args[-5:] == ["--run-isolated", "pals-agent", "worker", "--ready-file", "/tmp/ready"]
        raise OSError("exec failure")

    monkeypatch.setattr(boundary.subprocess, "run", install)
    monkeypatch.setattr(boundary.os, "execv", drop)
    with pytest.raises(OSError):
        boundary.start(["pals-agent", "worker", "--ready-file", "/tmp/ready"])


@pytest.mark.parametrize("field", [*boundary._CAP_FIELDS, "NoNewPrivs"])
def test_runtime_rejects_any_remaining_capability_or_privilege_escalation(monkeypatch, field):
    monkeypatch.setattr(boundary.os, "getresuid", lambda: (65532,) * 3, raising=False)
    monkeypatch.setattr(boundary.os, "getresgid", lambda: (65532,) * 3, raising=False)
    monkeypatch.setattr(boundary.os, "getgroups", lambda: [])
    status = dict.fromkeys(boundary._CAP_FIELDS, "0") | {"NoNewPrivs": "1"}
    boundary.validate_unprivileged(status)
    status[field] = "0" if field == "NoNewPrivs" else "1"
    with pytest.raises(ValueError):
        boundary.validate_unprivileged(status)


def test_nonlocal_context_is_rejected_before_privileged_operations(monkeypatch):
    context(monkeypatch)
    monkeypatch.setenv("PALS_ENV", "production")
    monkeypatch.setattr(
        boundary.subprocess, "run", lambda *_args, **_kw: pytest.fail("must not run")
    )
    with pytest.raises(ValueError):
        boundary.start(["pals-agent", "worker"])


def test_only_local_worker_service_gets_privileged_startup():
    root = Path(__file__).resolve().parents[3]
    compose = (root / "docker-compose.e2e.yml").read_text()
    worker = compose.split("\n  worker:\n", 1)[1].split("\n  recipe-reviewer:\n", 1)[0]
    rest = compose.replace(worker, "")
    assert 'user: "0:0"' in worker
    assert "cap_add: [NET_ADMIN, SETUID, SETGID, SETPCAP]" in worker
    assert "entrypoint: [python, -m, pals_agent.local_worker_boundary]" in worker
    assert "no-new-privileges:true" in worker and "read_only: true" in worker
    assert "stop_grace_period: 65m" in worker
    assert "pals_agent.local_worker_boundary" not in rest
    assert "cap_add: [NET_ADMIN" not in rest
    assert "USER 65532:65532" in (root / "pals-agent/Dockerfile.local").read_text()
    assert "local_worker_boundary" not in (root / "pals-agent/Dockerfile").read_text()


def test_healthcheck_keeps_pid_liveness_check_under_same_unprivileged_uid():
    root = Path(__file__).resolve().parents[3]
    compose = (root / "docker-compose.e2e.yml").read_text()
    worker = compose.split("\n  worker:\n", 1)[1].split("\n  recipe-reviewer:\n", 1)[0]
    health = worker.split("healthcheck:", 1)[1].split("read_only:", 1)[0]
    assert "test: [CMD, setpriv," in health
    for option in (
        "--reuid=65532",
        "--regid=65532",
        "--clear-groups",
        "--bounding-set=-all",
        "--inh-caps=-all",
        "--ambient-caps=-all",
        "--no-new-privs",
    ):
        assert option in health
    assert "os.kill(int(Path('/tmp/pals-worker-ready').read_text()),0)" in health
    assert "CAP_KILL" not in worker and "cap_add: [NET_ADMIN, SETUID, SETGID, SETPCAP]" in worker
