"""Lean compile tool interface for the PALS agent."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LeanCompileRequest:
    code: str
    imports: tuple[str, ...] = ()
    timeout_seconds: int = 30


@dataclass(frozen=True)
class LeanDiagnostic:
    severity: str
    message: str
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class LeanCompileResult:
    ok: bool
    diagnostics: tuple[LeanDiagnostic, ...] = ()
    elapsed_ms: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class LeanCompileTool:
    """Interface implemented by local, HTTP, or sidecar Lean verifier clients."""

    def compile(self, request: LeanCompileRequest) -> LeanCompileResult:
        raise NotImplementedError

