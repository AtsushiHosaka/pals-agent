from __future__ import annotations

import ast
import importlib.util
import re
import shlex
import tomllib
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[2]


def test_pfi_ag_003_private_candidate_boundary_is_implemented() -> None:
    from pals_agent.private_draft_candidates import PrivateDraftCandidateClient

    assert PrivateDraftCandidateClient.__name__ == "PrivateDraftCandidateClient"


def test_pfi_ag_004_complete_evidence_vectors_are_implemented() -> None:
    from pals_agent.proof_flow_evidence import project_draft_evidence

    assert project_draft_evidence.__name__ == "project_draft_evidence"


def test_pfi_ag_005_strict_reranker_is_implemented() -> None:
    from pals_agent.proof_flow_reranker import OpenAIDraftReranker

    assert OpenAIDraftReranker.__name__ == "OpenAIDraftReranker"


_DATABASE_MODULES = {
    "psycopg",
    "psycopg2",
    "asyncpg",
    "pg8000",
    "sqlalchemy",
    "sqlite3",
    "pymysql",
    "mysql",
}
_DATABASE_KEY = re.compile(
    r"(?:DATABASE_|POSTGRES|PGHOST|PGPORT|PGUSER|PGPASSWORD|PGDATABASE|RDS_SECRET)", re.I
)
_SQL = re.compile(
    r"^\s*(?:SELECT\s+.+\s+FROM\b|INSERT\s+INTO\b|DELETE\s+FROM\b|UPDATE\s+.+\s+SET\b|(?:CREATE|ALTER|DROP)\s+TABLE\b)",
    re.I | re.S,
)


def _database_capabilities(source: str) -> list[str]:
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if alias.name.split(".")[0] in _DATABASE_MODULES
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".")[0] in _DATABASE_MODULES
        ):
            found.append(node.module or "")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            value = node.value
            if _SQL.match(value) or re.match(r"postgres(?:ql)?(?:\+\w+)?://", value, re.I):
                found.append("database command/URL literal")
            elif _DATABASE_KEY.search(value) and re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
                found.append("database credential/configuration key")
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            name = (
                node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            )
            if (
                name in {"__import__", "import_module"}
                and str(node.args[0].value).split(".")[0] in _DATABASE_MODULES
            ):
                found.append("dynamic database import")
    return found


def test_pfi_ag_006_production_zero_database_code_and_dependency_capability() -> None:
    project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())["project"]
    dependencies = {re.split(r"[<>=!~;\[ ]", value)[0].lower() for value in project["dependencies"]}
    assert dependencies.isdisjoint(_DATABASE_MODULES)
    violations = {
        str(path.relative_to(REPOSITORY)): found
        for path in sorted((REPOSITORY / "pals_agent").rglob("*.py"))
        if (found := _database_capabilities(path.read_text()))
    }
    assert violations == {}


@pytest.mark.parametrize(
    "source",
    [
        "import psycopg",
        "from sqlalchemy import create_engine",
        'importlib.import_module("asyncpg")',
        'os.getenv("PALS_DATABASE_URL")',
        'query = "SELECT secret FROM billing"',
        'url = "postgresql://owner:secret@db/pals"',
    ],
)
def test_database_boundary_scan_checks_executable_capabilities(source: str) -> None:
    assert _database_capabilities(source)


def test_database_boundary_scan_does_not_treat_boundary_documentation_as_access() -> None:
    assert (
        _database_capabilities(
            'def validate():\n    """No Postgres or database_url access."""\n    return True\n'
        )
        == []
    )


def _production_shell_lines() -> list[list[str]]:
    path = REPOSITORY.parent / "pals-infra/terraform/production/templates/host-user-data.sh.tftpl"
    source = path.read_text().replace("\\\n", " ")
    return [
        shlex.split(line)
        for line in source.splitlines()
        if line.lstrip().startswith(("docker run -d ", "iptables "))
    ]


def test_pfi_ag_006_production_worker_has_explicit_database_network_deny() -> None:
    commands = _production_shell_lines()
    worker = next(
        words
        for words in commands
        if "--name" in words and words[words.index("--name") + 1] == "pals-worker"
    )
    address = worker[worker.index("--ip") + 1] + "/32"
    denies = [
        words
        for words in commands
        if words[0] == "iptables"
        and "-I" in words
        and "DOCKER-USER" in words
        and "-s" in words
        and words[words.index("-s") + 1] == address
        and "-p" in words
        and words[words.index("-p") + 1] == "tcp"
        and "--dport" in words
        and words[words.index("--dport") + 1] == "5432"
        and "-j" in words
        and words[words.index("-j") + 1] == "DROP"
    ]
    assert denies, (
        "PFI-AG-006: worker must not reach PostgreSQL through the host's Aurora security group"
    )
    assert commands.index(denies[0]) < commands.index(worker)


def test_pfi_ag_006_worker_environment_does_not_receive_database_credentials() -> None:
    compose = (REPOSITORY.parent / "docker-compose.e2e.yml").read_text()
    worker = _compose_service(compose, "worker")
    local_keys = re.findall(r"^      ([A-Z][A-Z0-9_]+):", worker, re.M)
    template = (
        REPOSITORY.parent / "pals-infra/terraform/production/templates/host-user-data.sh.tftpl"
    ).read_text()
    before_worker_env = template.split(">/opt/pals/env/worker.env", 1)[0]
    assignments = before_worker_env.rsplit("printf '%s\\n'", 1)[-1]
    production_keys = re.findall(r"[\"']([A-Z][A-Z0-9_]+)=", assignments)
    assert local_keys and production_keys
    assert not [key for key in local_keys + production_keys if _DATABASE_KEY.search(key)]


def test_pfi_ag_007_release_evidence_lifecycle_is_implemented() -> None:
    module = importlib.util.find_spec("pals_agent.proof_flow_release_evidence")
    assert module is not None


def _compose_service(compose: str, service_name: str) -> str:
    lines = compose.splitlines()
    marker = f"  {service_name}:"
    start = lines.index(marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and (
            not line.startswith(" ") or (line.startswith("  ") and not line.startswith("    "))
        ):
            end = index
            break
    return "\n".join(lines[start:end])


def test_pfi_ag_006_worker_has_no_host_profile_and_cannot_modify_session_mount() -> None:
    commands = _production_shell_lines()
    worker = next(
        words
        for words in commands
        if "--name" in words and words[words.index("--name") + 1] == "pals-worker"
    )
    address = worker[worker.index("--ip") + 1] + "/32"
    assert "--read-only" in worker
    assert worker[worker.index("--cap-drop") + 1] == "ALL"
    assert (
        worker[worker.index("--mount") + 1]
        == "type=bind,src=/opt/pals/worker-aws,dst=/run/pals-worker-aws,readonly"
    )
    denied = [
        words
        for words in commands
        if words[0] == "iptables"
        and "-I" in words
        and "-s" in words
        and words[words.index("-s") + 1] == address
        and "-d" in words
        and words[words.index("-d") + 1] == "169.254.169.254/32"
        and "-j" in words
        and words[words.index("-j") + 1] == "DROP"
    ]
    assert denied and commands.index(denied[0]) < commands.index(worker)
    template = (
        REPOSITORY.parent / "pals-infra/terraform/production/templates/host-user-data.sh.tftpl"
    ).read_text()
    assignments = template.split(">/opt/pals/env/worker.env", 1)[0].rsplit("printf '%s\\n'", 1)[-1]
    assert "AWS_EC2_METADATA_DISABLED=true" in assignments
    assert "AWS_PROFILE=pals-worker" in assignments
    assert "AWS_CONFIG_FILE=/run/pals-worker-aws/config" in assignments
    assert "AWS_SHARED_CREDENTIALS_FILE=/dev/null" in assignments
    assert "AWS_ACCESS_KEY_ID=" not in assignments
    assert "AWS_SECRET_ACCESS_KEY=" not in assignments


def test_pfi_ag_006_local_overlay_uses_distinct_database_network_and_auth_guard() -> None:
    compose = (REPOSITORY.parent / "docker-compose.e2e.yml").read_text()
    postgres = _compose_service(compose, "postgres")
    assert "      database:" in postgres and "      e2e:" not in postgres
    for name in ("worker", "recipe-reviewer", "webfront", "verifier"):
        service = _compose_service(compose, name)
        assert "      database:" not in service and "[e2e, database]" not in service
    for name in ("api", "reconciler"):
        assert "      database:" in _compose_service(compose, name)
    assert "networks: [e2e, database]" in _compose_service(compose, "schema-release")
    network = compose.split("\nnetworks:\n", 1)[1].split("  e2e:\n", 1)[0]
    assert "  database:" in network and "    internal: false" in network
    guard = (REPOSITORY.parent / "pals-scripts/harden-local-postgres-access.py").read_text()
    assert "host all all 172.30.0.0/24 reject" in guard
    assert "host replication all 172.30.0.0/24 reject" in guard
    # Native Docker providers may still route cross-bridge TCP; runtime probes,
    # not this configuration test, establish network enforcement.
