"""Local, deterministic Lean verification receipts for the continuity-v1 collection.

These receipts are deliberately marked as local-workspace verification evidence.  They are not a
signed seed and cannot be used as an API publication claim.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import rfc8785

from pals_agent.continuity_collection import concrete_cards
from pals_agent.proof_flow_seed import ContinuityCatalogError, load_continuity_catalog


_RECEIPT_SCHEMA = "pals.continuity-lean-receipts.local.v1"
_EXPECTED_CARD_COUNT = 110


_GENERIC_PROOFS: dict[str, str] = {
    "cv1_add_limit_at": "by\n  intro f g a L M hf hg\n  exact hf.add hg",
    "cv1_add_sequence": "by\n  intro u v L M hu hv\n  exact hu.add hv",
    "cv1_basic_limit_constant": "by\n  intro c a\n  exact tendsto_const_nhds",
    "cv1_basic_limit_identity": "by\n  intro a\n  exact Filter.tendsto_id.mono_left nhdsWithin_le_nhds",
    "cv1_basic_sequence_constant": "by\n  intro c\n  exact tendsto_const_nhds",
    "cv1_bridge_continuity_limit": (
        "by\n  intro f a hf\n  exact hf.tendsto.mono_left nhdsWithin_le_nhds"
    ),
    "cv1_bridge_continuous_on_at": "by\n  intro f a hf\n  exact hf.continuousAt",
    "cv1_bridge_sequential_continuity": (
        "by\n  intro f u a hf hu\n  constructor <;> exact hf.tendsto.comp hu"
    ),
    "cv1_compose_limit_at": "by\n  intro f g a L hg hf\n  exact hf.tendsto.comp hg",
    "cv1_compose_sequence": "by\n  intro f u L hu hf\n  exact hf.tendsto.comp hu",
    "cv1_div_limit_at": "by\n  intro f g a L M hf hg hM\n  exact hf.div hg hM",
    "cv1_div_sequence": "by\n  intro u v L M hu hv hM\n  exact hu.div hv hM",
    "cv1_mul_limit_at": "by\n  intro f g a L M hf hg\n  exact hf.mul hg",
    "cv1_mul_sequence": "by\n  intro u v L M hu hv\n  exact hu.mul hv",
    "cv1_neg_limit_at": "by\n  intro f a L hf\n  exact hf.neg",
    "cv1_neg_sequence": "by\n  intro u L hu\n  exact hu.neg",
    "cv1_scale_limit_at": "by\n  intro f a L c hf\n  exact hf.const_mul c",
    "cv1_scale_sequence": "by\n  intro u L c hu\n  exact hu.const_mul c",
    "cv1_sub_limit_at": "by\n  intro f g a L M hf hg\n  exact hf.sub hg",
    "cv1_sub_sequence": "by\n  intro u v L M hu hv\n  exact hu.sub hv",
}


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _concrete_proofs() -> dict[str, str]:
    return {card["draft_id"]: card["_proof_body"] for card in concrete_cards()}


def proof_body_for_card(draft_id: str) -> str:
    concrete = _concrete_proofs()
    if draft_id in concrete:
        return concrete[draft_id]
    if draft_id in _GENERIC_PROOFS:
        return _GENERIC_PROOFS[draft_id]
    if draft_id.startswith(
        (
            "cv1_add_",
            "cv1_basic_continuity_",
            "cv1_compose_continuity_",
            "cv1_div_continuity_",
            "cv1_mul_continuity_",
            "cv1_neg_continuity_",
            "cv1_scale_continuity_",
            "cv1_sub_continuity_",
        )
    ) or draft_id.endswith(("_continuity_at", "_continuous_on")):
        return "by\n  fun_prop"
    raise KeyError(f"no Lean proof source is defined for {draft_id}")


def _wrapper(target: str, proof_body: str) -> str:
    return f"import Mathlib\nopen scoped Topology\n\nexample : {target} := {proof_body}\n"


def build_local_receipts(
    catalog_path: Path,
    *,
    workspace: Path,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Compile every source card in the pinned workspace and return no-LF-JCS receipt content."""
    catalog = load_continuity_catalog(catalog_path)
    if len(catalog.cards) != _EXPECTED_CARD_COUNT:
        raise ContinuityCatalogError("catalog_card_count_below_local_receipt_floor")
    if not workspace.is_dir() or not (workspace / "lakefile.lean").is_file():
        raise ValueError("Lean workspace is invalid")
    lake = shutil.which("lake")
    if lake is None:
        raise RuntimeError("lake is unavailable")
    sources = [
        (card, _wrapper(card.raw["lean_target"], proof_body_for_card(card.draft_id)))
        for card in catalog.cards
    ]
    with tempfile.TemporaryDirectory(prefix="pals-continuity-receipts-") as directory:
        scratch = Path(directory)
        wrapper = scratch / "continuity_v1_batch.lean"
        wrapper.write_text(
            "import Mathlib\nopen scoped Topology\n\n"
            + "\n".join(
                f"-- {card.draft_id}\nexample : {card.raw['lean_target']} := {source.split(' := ', 1)[1]}"
                for card, source in sources
            )
            + "\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [lake, "env", "lean", "--threads=1", str(wrapper)],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout_seconds,
            check=False,
        )
        output = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise RuntimeError(f"Lean verification batch failed: {output[:4096]}")
    receipts = [
        {
            "compiler_output_sha256": _sha256(output),
            "draft_id": card.draft_id,
            "lean_target_sha256": _sha256(card.raw["lean_target"]),
            "openmath_xml_sha256": _sha256(card.raw["openmath_xml"]),
            "proof_source_sha256": _sha256(source),
            "status": "verified",
        }
        for card, source in sources
    ]
    expected_ids = [card.draft_id for card in catalog.cards]
    receipt_ids = [receipt["draft_id"] for receipt in receipts]
    if receipt_ids != expected_ids or len(set(receipt_ids)) != _EXPECTED_CARD_COUNT:
        raise RuntimeError("local receipt ID set is incomplete")
    toolchain = subprocess.run(
        [lake, "--version"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=timeout_seconds,
        check=True,
    ).stdout
    return {
        "receipts": receipts,
        "schema_version": _RECEIPT_SCHEMA,
        "toolchain_sha256": _sha256(toolchain),
        "verification_scope": "local_workspace_only",
    }


def receipt_bytes(receipts: dict[str, Any]) -> bytes:
    return rfc8785.dumps(receipts)


def write_local_receipts(receipts: dict[str, Any], destination: Path) -> None:
    destination.write_bytes(receipt_bytes(receipts))
