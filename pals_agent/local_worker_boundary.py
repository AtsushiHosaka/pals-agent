"""Local-only worker startup: install namespace rules, irreversibly drop privileges.

No host firewall is modified. The trusted entrypoint temporarily needs NET_ADMIN,
SETUID, SETGID and SETPCAP; the actual worker and all its descendants have no
capabilities, including an empty bounding set. Other image consumers do not use
this entrypoint. A failed rule installation or privilege drop prevents startup.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

_STARTUP_CAPS = sum(1 << number for number in (6, 7, 8, 12))
_CAP_FIELDS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")


class _LinuxIdentity(Protocol):
    def getresuid(self) -> tuple[int, int, int]: ...

    def getresgid(self) -> tuple[int, int, int]: ...


def status_fields() -> dict[str, str]:
    return dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )


def rule_set(host_port: str) -> str:
    if not host_port.isascii() or not host_port.isdecimal() or not 1 <= int(host_port) <= 65535:
        raise ValueError("Invalid local database port")
    ports = ", ".join(str(port) for port in sorted({5432, int(host_port)}))
    return (
        "table inet pals_worker {\n"
        "  chain output {\n"
        "    type filter hook output priority -150; policy accept;\n"
        f"    tcp dport {{ {ports} }} reject with tcp reset\n"
        "    ip daddr 169.254.169.254 reject\n"
        "    ip6 daddr fd00:ec2::254 reject\n"
        "  }\n"
        "}\n"
    )


def validate_local_context(environ: dict[str, str]) -> None:
    expected = {
        "PALS_ENV": "local",
        "PALS_LOCAL_WORKER_NETWORK_GUARD": "1",
        "PALS_API_BASE_URL": "http://api:8000",
        "PALS_AWS_ENDPOINT_URL": "http://localstack:4566",
    }
    if any(environ.get(name) != value for name, value in expected.items()):
        raise ValueError("This entrypoint requires the explicit local stack contract")


def validate_unprivileged(status: dict[str, str]) -> None:
    identity = cast(_LinuxIdentity, os)
    if (
        identity.getresuid() != (65532, 65532, 65532)
        or identity.getresgid() != (65532, 65532, 65532)
        or os.getgroups()
        or any(int(status[name].strip(), 16) != 0 for name in _CAP_FIELDS)
        or status["NoNewPrivs"].strip() != "1"
    ):
        raise ValueError("Worker privileges were not completely dropped")


def start(arguments: list[str]) -> None:
    validate_local_context(dict(os.environ))
    child = arguments[:1] == ["--run-isolated"]
    command = arguments[1:] if child else arguments
    if command[:2] != ["pals-agent", "worker"]:
        raise ValueError("Only the local proof worker may use this entrypoint")
    status = status_fields()
    if child:
        validate_unprivileged(status)
        os.execvp(command[0], command)
        raise RuntimeError("Worker exec did not replace the entrypoint")
    if os.geteuid() != 0 or int(status["CapEff"].strip(), 16) != _STARTUP_CAPS:
        raise ValueError("Unexpected trusted-startup authority")
    rules = rule_set(os.environ.get("PALS_LOCAL_DENIED_TCP_PORT", "55432"))
    existing = subprocess.run(
        ["/usr/sbin/nft", "-j", "list", "tables"],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    tables = json.loads(existing.stdout)["nftables"]
    if any(
        item.get("table", {}).get("family") == "inet"
        and item.get("table", {}).get("name") == "pals_worker"
        for item in tables
    ):
        rules = "delete table inet pals_worker\n" + rules
    # Replace only our table in one atomic transaction on restart; never flush
    # other rules or create an unguarded interval in an existing namespace.
    # nft applies this ruleset atomically inside this container's own namespace.
    subprocess.run(
        ["/usr/sbin/nft", "-f", "-"],
        input=rules,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    os.execv(
        "/usr/bin/setpriv",
        [
            "/usr/bin/setpriv",
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--no-new-privs",
            "--reuid=65532",
            "--regid=65532",
            "--clear-groups",
            sys.executable,
            "-m",
            "pals_agent.local_worker_boundary",
            "--run-isolated",
            *command,
        ],
    )
    raise RuntimeError("Privilege-drop exec did not replace the entrypoint")


def main() -> int:
    try:
        start(sys.argv[1:])
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError):
        print("Local worker isolation setup failed; worker was not started.", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
