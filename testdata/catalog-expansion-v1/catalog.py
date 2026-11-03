"""Recover pinned mathematical authoring records and replay their exact Lean bundles.

No network, database, embedding, review, signing or catalog publication operation.
Local compilation is not runtime admission or natural-language correctness evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from pals_agent.breadth_evaluation import Corpus, environment_binding
from pals_agent.lean import _strip_lean_comments_and_strings
from pals_agent.typed_local_catalog import TypedLocalCatalogError, load_typed_local_catalog_manifest

ROOT = Path(__file__).resolve().parents[3]
SOURCES = Path(__file__).with_name("sources.json")
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def read(root: Path, relative: str, expected: str | None = None) -> bytes:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("source path escapes repository")
    selected = root
    for part in path.parts:
        selected /= part
        if selected.is_symlink():
            raise ValueError("symlink source refused")
    raw = selected.read_bytes()
    if not raw or len(raw) > 8 * 1024 * 1024 or (expected is not None and sha(raw) != expected):
        raise ValueError("source bytes changed or excessive")
    return raw


def checked_source(text: str) -> list[str]:
    checked = _strip_lean_comments_and_strings(text)
    if re.search(r"\b(?:sorry|admit|axiom|unsafe|run_tac|run_cmd)\b|#(?:eval|exit)", checked):
        raise ValueError("unchecked or executable source construct")
    if re.search(r"^\s*namespace\b", checked, re.M):
        raise ValueError("namespace requires explicit audit naming support")
    return checked.splitlines()


def audit_source(text: str) -> tuple[str, list[str]]:
    """Name examples without changing proofs; retain their ambient section context."""
    checked = checked_source(text)
    lines = text.splitlines()
    names = []
    for index, line in enumerate(checked):
        if re.match(r"^example\b", line):
            name = f"pals_catalog_audit_{len(names):04d}"
            if not re.match(r"^example\b", lines[index]):
                raise ValueError("audit line mapping differs")
            lines[index] = re.sub(r"^example\b", "theorem " + name, lines[index], count=1)
            names.append(name)
    if not names:
        raise ValueError("no audit declarations")
    audit = "\n".join(lines)
    context = "variable (S : Type*) [CommRing S] [Algebra R S] [IsLocalization M S]"
    if context in checked:
        # Anonymous examples can use M only in their proof; named declarations
        # need its existing arbitrary section parameter explicitly retained.
        audit = audit.replace(context, context + "\ninclude M")
    return audit + "\n\n" + "".join("#print axioms " + name + "\n" for name in names), names


def axioms(output: str, names: list[str]) -> dict[str, list[str]]:
    found = {}
    for name, values in re.findall(r"'([^']+)' depends on axioms: \[([^]]*)\]", output, re.S):
        if name in found:
            raise ValueError("duplicate axiom observation")
        found[name] = sorted(value.strip() for value in values.split(",") if value.strip())
    for name in re.findall(r"'([^']+)' does not depend on any axioms", output):
        if name in found:
            raise ValueError("duplicate axiom observation")
        found[name] = []
    if set(found) != set(names) or any(set(values) - ALLOWED_AXIOMS for values in found.values()):
        raise ValueError("missing or unapproved theorem axioms")
    return found


def example_index(source: str, card: dict[str, Any]) -> int:
    starts = [match.start() for match in re.finditer(r"^example\b", source, re.M)]
    marker = "-- manifest card: " + card["id"]
    if marker in source:
        begin = source.index(marker) + len(marker)
        next_marker = source.find("-- manifest card:", begin)
        end = len(source) if next_marker < 0 else next_marker
        indexes = [index for index, start in enumerate(starts) if begin <= start < end]
        if len(indexes) != 1:
            raise ValueError("card marker does not bind one example")
        return indexes[0]
    target = card.get("lean_target", card.get("lean", {}).get("target"))
    proof = card.get("lean_witness", card.get("lean", {}).get("witness"))
    if not isinstance(target, str) or not isinstance(proof, str):
        raise ValueError("card lacks a Lean witness")
    declaration = (
        proof
        if proof.startswith("example")
        else (target if target.startswith("example") else "example : " + target) + " := " + proof
    )
    if source.count(declaration.rstrip()) != 1:
        raise ValueError("card witness does not bind one source example")
    begin = source.index(declaration.rstrip())
    if begin not in starts:
        raise ValueError("card witness is not a top-level example")
    return starts.index(begin)


def inventory(root: Path = ROOT) -> dict[str, Any]:
    pins = json.loads(SOURCES.read_bytes(), object_pairs_hook=unique)
    read(root, pins["inventory_path"], pins["inventory_sha256"])
    # Reuse the owning conservative duplicate signal; it is not theorem equivalence.
    spec = importlib.util.spec_from_file_location(
        "catalog_curriculum_auditor", root / "pals-scripts/audit-foundation-curriculum.py"
    )
    assert spec and spec.loader
    auditor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auditor)
    bindings = json.loads(read(root, "pals-api/app/domain/typed_catalog_bindings.json"))
    cards, bundles, excluded = [], [], []
    seen_ids, seen_xml = set(), set()
    for pin in pins["sources"]:
        raw = read(root, pin["manifest_path"], pin["manifest_sha256"])
        source_raw = read(root, pin["witness_path"], pin["witness_sha256"])
        payload = json.loads(raw, object_pairs_hook=unique)
        source = source_raw.decode()
        checked_source(source)
        rows = [card for key in pin["card_keys"] for card in payload[key]]
        if len(rows) != pin["expected_cards"]:
            raise ValueError("pinned card population changed")
        try:
            loaded = load_typed_local_catalog_manifest(
                root / pin["manifest_path"], repository_root=root
            )
        except TypedLocalCatalogError:
            excluded.append(
                {
                    "source_id": pin["id"],
                    "card_ids": [row["id"] for row in rows],
                    "reason": "owning_manifest_validation_failed",
                }
            )
            continue
        by_id = {card.card_id: card for card in loaded.cards}
        if set(by_id) != {card["id"] for card in rows}:
            raise ValueError("owning loader population differs")
        imports = re.findall(r"^import\s+([^\n]+)$", source, re.M)
        bundles.append({**pin, "imports": imports, "profile_id": loaded.profile.profile_id})
        for raw_card in rows:
            card = by_id[raw_card["id"]]
            if card.card_id in seen_ids or card.canonical_openmath_xml in seen_xml:
                raise ValueError("duplicate exact card identity or canonical XML")
            seen_ids.add(card.card_id)
            seen_xml.add(card.canonical_openmath_xml)
            signature = auditor.structural_signature(card.canonical_openmath_xml)
            if signature is None:
                raise ValueError("invalid structural signature")
            cards.append(
                {
                    "id": card.card_id,
                    "profile_id": card.profile_id,
                    "source_id": pin["id"],
                    "manifest_path": pin["manifest_path"],
                    "manifest_sha256": pin["manifest_sha256"],
                    "witness_path": pin["witness_path"],
                    "witness_sha256": pin["witness_sha256"],
                    "source_example_index": example_index(source, raw_card),
                    "imports": imports,
                    "canonical_statement": card.canonical_statement,
                    "canonical_openmath_xml": card.canonical_openmath_xml,
                    "canonical_openmath_xml_sha256": card.canonical_openmath_xml_sha256,
                    "proof_strategy": card.proof_strategy,
                    "sketch_steps": list(card.sketch_steps),
                    "lean_target": raw_card.get(
                        "lean_target", raw_card.get("lean", {}).get("target")
                    ),
                    "lean_witness": raw_card.get(
                        "lean_witness", raw_card.get("lean", {}).get("witness")
                    ),
                    "structural_pattern_sha256": sha(signature.encode()),
                    "api_profile_registered": card.profile_id in bindings,
                    "semantic_alignment_independently_verified": False,
                    "compiled_in_this_run": False,
                    "admitted": False,
                    "published": False,
                }
            )
    groups: dict[str, list[str]] = defaultdict(list)
    for card in cards:
        groups[card["structural_pattern_sha256"]].append(card["id"])
    repeated = [sorted(group) for group in groups.values() if len(group) > 1]
    return {
        "schema_version": "pals.catalog-expansion.inventory.v1",
        "source_index_sha256": sha(SOURCES.read_bytes()),
        "toolchain": {
            "lean_toolchain": pins["lean_toolchain"],
            "mathlib_revision": pins["mathlib_revision"],
        },
        "cards": cards,
        "bundles": bundles,
        "excluded": excluded,
        "exact_record_count": len(cards),
        "structural_pattern_count": len(groups),
        "structural_duplicate_signals": repeated,
        "distinct_semantics_established": False,
        "usable_runtime_records_added": 0,
    }


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def mathematical_identity(data: dict[str, Any]) -> dict[str, Any]:
    # Runtime registration may be updated concurrently by its owning release
    # task. It is an inventory observation, never part of the Lean evidence.
    return {
        **data,
        "cards": [
            {key: value for key, value in row.items() if key != "api_profile_registered"}
            for row in data["cards"]
        ],
    }


def verify(
    data: dict[str, Any], project: Path, binary: Path, output: Path, only: list[str]
) -> dict[str, Any]:
    project, binary = project.resolve(strict=True), binary.resolve(strict=True)
    corpus = Corpus(
        SOURCES,
        sha(SOURCES.read_bytes()),
        data["toolchain"]["lean_toolchain"],
        data["toolchain"]["mathlib_revision"],
        (),
    )
    binding = environment_binding(corpus, project)
    version = subprocess.run(
        [str(binary), "--version"], check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()
    if "version 4.32.0-rc1" not in version:
        raise ValueError("compiler version differs")
    packages = json.loads((project / "lake-manifest.json").read_bytes())
    directory = project / packages.get("packagesDir", ".lake/packages")
    libraries = [directory / row["name"] / ".lake/build/lib/lean" for row in packages["packages"]]
    if not (directory / "mathlib/.lake/build/lib/lean/Mathlib.olean").is_file():
        raise ValueError("compiled Mathlib is absent")
    environment = {
        "PATH": "/usr/bin:/bin",
        "LEAN_PATH": ":".join(str(p) for p in libraries if p.is_dir()),
    }
    selected = [row for row in data["bundles"] if not only or row["id"] in only]
    if only and set(only) != {row["id"] for row in selected}:
        raise ValueError("unknown selected source")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipts = output.parent / (output.stem + ".bundles")
    if output.exists() or receipts.exists():
        raise ValueError("replay output or partial evidence already exists")
    receipts.mkdir(mode=0o700)
    outcomes = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="catalog-replay-", dir=output.parent) as temporary:
        for index, pin in enumerate(selected):
            if time.monotonic() - started > 1200:
                raise ValueError("total compiler budget exhausted")
            source = read(ROOT, pin["witness_path"], pin["witness_sha256"])
            audit, names = audit_source(source.decode())
            audit_path = Path(temporary) / f"Audit{index}.lean"
            audit_path.write_text(audit)
            began = time.monotonic()
            result = subprocess.run(
                [str(binary), str((ROOT / pin["witness_path"]).resolve())],
                capture_output=True,
                text=True,
                env=environment,
                timeout=120,
            )
            if result.returncode != 0 or len(result.stdout + result.stderr) > 1024 * 1024:
                raise ValueError("original witness compilation failed: " + pin["id"])
            observed = subprocess.run(
                [str(binary), str(audit_path)],
                capture_output=True,
                text=True,
                env=environment,
                timeout=120,
            )
            if observed.returncode != 0 or len(observed.stdout + observed.stderr) > 1024 * 1024:
                raise ValueError("axiom audit compilation failed: " + pin["id"])
            found = axioms(observed.stdout + observed.stderr, names)
            read(ROOT, pin["witness_path"], pin["witness_sha256"])
            row = {
                "source_id": pin["id"],
                "source_sha256": sha(source),
                "audit_source_sha256": sha(audit.encode()),
                "compiled": True,
                "axioms": found,
                "elapsed_seconds": time.monotonic() - began,
                "compiler_diagnostics_sha256": sha((result.stdout + result.stderr).encode()),
            }
            outcomes.append(row)
            # Immutable per-bundle evidence survives a later compilation failure.
            save(receipts / (pin["id"] + ".json"), row)
            print(
                json.dumps(
                    {"source_id": pin["id"], "compiled": True, "axiom_audited_examples": len(names)}
                ),
                flush=True,
            )
    if environment_binding(corpus, project) != binding or (
        mathematical_identity(inventory()) != mathematical_identity(data)
    ):
        raise ValueError("sources or dependencies changed during replay")
    by_source = {row["source_id"]: row for row in outcomes}
    verified_cards = []
    for card in data["cards"]:
        if card["source_id"] not in by_source:
            continue
        row = by_source[card["source_id"]]
        name = f"pals_catalog_audit_{card['source_example_index']:04d}"
        verified_cards.append(
            {
                "id": card["id"],
                "source_id": card["source_id"],
                "source_sha256": row["source_sha256"],
                "audit_theorem": name,
                "axioms": row["axioms"][name],
                "compiled_in_this_run": True,
            }
        )
    report = {
        "schema_version": "pals.catalog-expansion.local-replay.v1",
        "inventory_sha256": sha(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()),
        "compiler_version": version,
        "compiler_binary_sha256": sha(binary.read_bytes()),
        "environment": binding,
        "bundles": outcomes,
        "cards": verified_cards,
        "compiled_card_count": len(verified_cards),
        "all_selected_compiled": True,
        "elapsed_seconds": time.monotonic() - started,
        "cache_or_sources_modified": False,
        "precompiled_artifact_origin_audited": False,
        "semantic_alignment_independently_verified": False,
        "admitted": False,
        "published": False,
        "runtime_verified": False,
    }
    save(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--lean-binary", type=Path)
    parser.add_argument("--only-source", action="append", default=[])
    args = parser.parse_args()
    data = inventory()
    if args.verify:
        if args.project is None or args.lean_binary is None:
            parser.error("verification requires project and lean binary")
        report = verify(data, args.project, args.lean_binary, args.output, args.only_source)
        print(
            json.dumps({"compiled_card_count": report["compiled_card_count"], "published": False})
        )
    else:
        if args.only_source or args.project or args.lean_binary:
            parser.error("compiler options require --verify")
        save(args.output, data)
        print(
            json.dumps(
                {
                    "records": data["exact_record_count"],
                    "structural_patterns": data["structural_pattern_count"],
                    "published": False,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
