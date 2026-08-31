from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).parents[2]
TASK6_RED = pytest.mark.xfail(
    strict=True,
    reason="PFI Task 6 runtime integration is blocked on the approved API PFI child",
)


def test_pfi_ag_003_private_candidate_boundary_is_implemented() -> None:
    from pals_agent.private_draft_candidates import PrivateDraftCandidateClient

    assert PrivateDraftCandidateClient.__name__ == "PrivateDraftCandidateClient"


def test_pfi_ag_004_complete_evidence_vectors_are_implemented() -> None:
    from pals_agent.proof_flow_evidence import project_draft_evidence

    assert project_draft_evidence.__name__ == "project_draft_evidence"


def test_pfi_ag_005_strict_reranker_is_implemented() -> None:
    from pals_agent.proof_flow_reranker import OpenAIDraftReranker

    assert OpenAIDraftReranker.__name__ == "OpenAIDraftReranker"


def test_pfi_ag_006_production_zero_database_capability_is_implemented() -> None:
    pyproject = (REPOSITORY / "pyproject.toml").read_text(encoding="utf-8")
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPOSITORY / "pals_agent").glob("*.py"))
    )
    dockerfile = (REPOSITORY / "Dockerfile").read_text(encoding="utf-8")

    assert "psycopg" not in pyproject.lower()
    assert "postgres" not in production.lower()
    assert "database_url" not in production.lower()
    assert "5432" not in dockerfile


def test_pfi_ag_006_compose_removes_agent_database_network_capability() -> None:
    compose = (REPOSITORY.parent / "docker-compose.yml").read_text(encoding="utf-8")
    agent = _compose_service(compose, "pals-agent")
    api = _compose_service(compose, "pals-api")
    postgres = _compose_service(compose, "postgres")

    assert "\n      postgres:\n" not in agent
    assert "\n      - default\n" in agent
    assert "\n      - pals-database\n" not in agent
    assert "\n      - pals-database\n" in api
    assert "\n      - pals-database\n" in postgres
    assert "\n      - default\n" not in postgres
    assert "  pals-database:\n    internal: true\n" in compose


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
            not line.startswith(" ")
            or (line.startswith("  ") and not line.startswith("    "))
        ):
            end = index
            break
    return "\n".join(lines[start:end])
