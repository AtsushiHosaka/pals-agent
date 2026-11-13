"""Shared by the evaluation drivers: confine the resident Lean on Linux.

On Linux ``ResidentLean`` refuses an unconfined worker, so every driver passes these keyword
arguments to ``ResidentConfig``.  Elsewhere (macOS development) confinement does not exist and
nothing is added.  ``request_root`` is the directory the driver's scratch directories live under.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pals_agent.lean_verifier.resident.manager import default_read_roots


def confinement_kwargs(lean_binary: str, lean_path: str, request_root: Path) -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        return {}
    root = Path(request_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return {
        "confine": True,
        "request_root": root,
        "read_roots": default_read_roots(lean_binary, lean_path),
    }
