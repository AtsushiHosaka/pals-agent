from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_pae_017_worker_image_contains_no_lean_toolchain_or_workspace() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    lowered = dockerfile.lower()

    assert "elan" not in lowered
    assert "lean-workspace" not in lowered
    assert "lake" not in lowered
    assert "user 65532:65532" in lowered


def test_pae_036_verifier_image_is_nonroot_and_uses_the_http_runtime() -> None:
    dockerfile = (REPOSITORY_ROOT / "docker" / "lean-verifier.Dockerfile").read_text(
        encoding="utf-8"
    )
    lowered = dockerfile.lower()

    assert lowered.count("from ") >= 2
    assert "user 65532:65532" in lowered
    assert "pals_lean_verifier_socket" not in lowered
    assert "lean_verifier.http_runtime" in lowered
    assert "expose " not in lowered
    assert (
        "copy --from=builder --chown=65532:65532 /build/lean-workspace /app/lean-workspace"
    ) in lowered


def test_pae_017_production_factory_has_no_local_lean_fallback() -> None:
    factory = (REPOSITORY_ROOT / "pals_agent" / "factory.py").read_text(encoding="utf-8")

    assert "UnixLeanVerifierClient" not in factory
    assert "verifier=LeanVerifier(" not in factory
    assert 'verification_mode="api_reconcile"' in factory


def test_pae_017_agent_package_has_no_unix_verifier_compatibility_module() -> None:
    verifier_package = REPOSITORY_ROOT / "pals_agent" / "lean_verifier"

    assert not (verifier_package / "client.py").exists()
    assert not (verifier_package / "server.py").exists()


def test_pae_036_verifier_server_is_http_only() -> None:
    server = (REPOSITORY_ROOT / "pals_agent" / "lean_verifier" / "http_server.py").read_text(
        encoding="utf-8"
    )

    assert "ThreadingHTTPServer" in server
    assert '"/ready"' in server
    assert '"/v1/verify"' in server
    assert "UnixStreamServer" not in server


def test_pae_017_compose_uses_bounded_cold_compile_deadline_pair() -> None:
    compose = (REPOSITORY_ROOT.parent / "docker-compose.e2e.yml").read_text(encoding="utf-8")

    # The base compose now runs only PostgreSQL; the integrated verifier is owned
    # by the E2E overlay. Scope these assertions to its actual service block.
    verifier = compose.split("\n  verifier:\n", 1)[1].split("\n  reconciler:\n", 1)[0]
    assert 'PALS_LEAN_TIMEOUT_SECONDS: "300"' in verifier
    assert "cpus: 2.0" in verifier
    assert "mem_limit: 4g" in verifier
    assert "memswap_limit: 4g" in verifier
    from pals_agent.lean_verifier.http_runtime import _MAX_TIMEOUT_SECONDS

    assert _MAX_TIMEOUT_SECONDS == 300
