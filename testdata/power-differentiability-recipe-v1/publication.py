"""Prepare a general Recipe's release inputs, offline.

Recipe: differentiability.power.natural.induction-product-rule
Statement: ∀ (n : ℕ), Differentiable ℝ (fun x : ℝ => x ^ n)

No DB/provider/network/key access, review, signature or admission occurs here. The
authoring manifest binds the frozen compiler identity of ``requested-math-seeds-v1``;
the release boundary must still observe the real verifier fingerprint and compile again.
The unsealed search entry needs a compiler receipt exported from a real admitted revision.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import rfc8785

ROOT = Path(__file__).resolve().parent
RECIPE_ID = "differentiability.power.natural.induction-product-rule"
AUTHOR = "pals.principal.v1/claude/power-differentiability-recipe-20261107"
_SEEDS = ROOT.parent / "requested-math-seeds-v1" / "publication.py"
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _shared() -> Any:
    """Reuse the audited receipt/materializer helpers instead of copying them."""
    spec = importlib.util.spec_from_file_location("requested_seed_publication", _SEEDS)
    if spec is None or spec.loader is None:
        raise ValueError("requested seed publication helpers are unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shared = _shared()
EXPECTED_TOOLCHAIN: dict[str, Any] = shared.EXPECTED_TOOLCHAIN
sha = shared.sha
read_object = shared.read_object
materialize = shared.materialize
write_new = shared.write_new


def load_card() -> dict[str, Any]:
    card: dict[str, Any] = read_object(ROOT / "card.json")
    if card["id"] != RECIPE_ID or card["schema_version"] != "pals.general-recipe-card.v1":
        raise ValueError("unexpected card identity")
    return card


def proof_body(card: dict[str, Any]) -> str:
    """The text after `:=` of the single theorem, so the checked file and manifest cannot drift."""
    source = (ROOT / card["source_path"]).read_text()
    match = re.search(
        r"^theorem\s+" + card["theorem_name"] + r"\s*:[^\n]*:= (by\n.*)\Z", source, re.S | re.M
    )
    if match is None:
        raise ValueError("proof file does not have the expected theorem shape")
    return str(match.group(1)).rstrip("\n")


def authoring_manifest(
    card: dict[str, Any], toolchain: dict[str, Any] = EXPECTED_TOOLCHAIN
) -> dict[str, Any]:
    return {
        "schema_version": "pals.recipe-authoring-manifest.v1",
        "recipe_id": card["id"],
        "revision": card["revision"],
        "kind": "exact_target_proof",
        "source_author_principal": AUTHOR,
        "author_profile": {
            "schema_version": "pals.recipe-author-profile.v1",
            "source_author_principal": AUTHOR,
        },
        "toolchain": toolchain,
        "imports": ["Mathlib"],
        "environment": {"namespace": None, "opens": []},
        "target_source": card["target_source"],
        "proof_body": proof_body(card),
    }


def search_text(card: dict[str, Any]) -> str:
    """English text-search lexemes plus the Japanese statement; retrieval-only, never evidence."""
    return "\n".join(
        [
            card["statement"],
            *card["assumptions"],
            *card["question_variants"]["en"],
            *card["proof_outline"],
            *card["aliases"]["en"],
            *card["aliases"]["ja"],
            "power function differentiability differentiable natural "
            "exponent product rule induction",
            card["family_id"].replace("-", " "),
        ]
    )


def load_toolchain(path: Path | None) -> dict[str, Any]:
    """The frozen binding, or an operator-observed one when the verifier fingerprint changed."""
    if path is None:
        return EXPECTED_TOOLCHAIN
    value: dict[str, Any] = read_object(path)
    fingerprint = value.get("fingerprint")
    if (
        set(value) != {"toolchain_id", "fingerprint"}
        or not isinstance(value["toolchain_id"], str)
        or not isinstance(fingerprint, dict)
        or set(fingerprint) != set(EXPECTED_TOOLCHAIN["fingerprint"])
        or fingerprint["schema_version"] != EXPECTED_TOOLCHAIN["fingerprint"]["schema_version"]
        or fingerprint["materializer_version"]
        != EXPECTED_TOOLCHAIN["fingerprint"]["materializer_version"]
        or any(
            not isinstance(fingerprint[key], str) or not _DIGEST.fullmatch(fingerprint[key])
            for key in ("lake_manifest_sha256", "verifier_sha256")
        )
    ):
        raise ValueError("toolchain object does not have the fingerprint shape")
    return value


def search_candidate(
    card: dict[str, Any],
    manifest: dict[str, Any],
    receipt: dict[str, Any],
    toolchain: dict[str, Any] = EXPECTED_TOOLCHAIN,
) -> dict[str, Any]:
    """Pure binding check, not proof of the supplied receipt's origin or authority."""
    if manifest["toolchain"] != toolchain:
        raise ValueError("authoring toolchain differs from the frozen compiler")
    source = materialize(manifest)
    fingerprint_hash = sha(rfc8785.dumps(manifest["toolchain"]["fingerprint"]))
    if (
        set(receipt)
        != {
            "schema_version",
            "materialized_source_sha256",
            "toolchain_fingerprint_sha256",
            "compiler_command_sha256",
            "compiler_result",
        }
        or receipt["schema_version"] != "pals.recipe-admission-compiler-receipt.v1"
        or receipt["materialized_source_sha256"] != sha(source)
        or receipt["toolchain_fingerprint_sha256"] != fingerprint_hash
        or not isinstance(receipt["compiler_command_sha256"], str)
        or not _DIGEST.fullmatch(receipt["compiler_command_sha256"])
        or card["id"] != manifest["recipe_id"]
        or card["revision"] != manifest["revision"]
        or card["target_source"] != manifest["target_source"]
    ):
        raise ValueError("compiler receipt identity mismatch")
    result = receipt["compiler_result"]
    if (
        not isinstance(result, dict)
        or set(result) != {"schema_version", "verification_succeeded", "diagnostic_codes"}
        or result["schema_version"] != "pals.recipe-admission-compiler-result.v1"
        or result["verification_succeeded"] is not True
        or not isinstance(result["diagnostic_codes"], list)
        or any(not isinstance(code, str) for code in result["diagnostic_codes"])
    ):
        raise ValueError("successful closed compiler result required")
    return {
        "schema_version": "pals.recipe-search-entry.v1",
        "recipe_id": card["id"],
        "recipe_revision": card["revision"],
        "statement": card["statement"],
        "domain": card["domain"],
        "assumptions": card["assumptions"],
        "quantifiers": card["quantifiers"],
        "conclusion": card["conclusion"],
        "proof_method_tag": card["proof_method_tag"],
        "search_text": search_text(card),
        "output_language": "ja",
        "answer": card["answer"],
        "answer_sha256": sha(card["answer"].encode()),
        "target_sha256": sha(card["target_source"].encode()),
        "lean_sha256": sha(source),
        "compiler_receipt_sha256": sha(rfc8785.dumps(receipt)),
        "toolchain_sha256": fingerprint_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    manifest_command = commands.add_parser(
        "manifest", help="write the canonical authoring manifest"
    )
    manifest_command.add_argument("--output", required=True, type=Path)
    manifest_command.add_argument(
        "--toolchain-json",
        type=Path,
        help="observed {toolchain_id, fingerprint}; default is the frozen aws-v2 binding",
    )
    entry_command = commands.add_parser("entry", help="write an unsealed search entry and source")
    entry_command.add_argument("--compiler-receipt", required=True, type=Path)
    entry_command.add_argument("--output-directory", required=True, type=Path)
    entry_command.add_argument("--toolchain-json", type=Path)
    args = parser.parse_args()
    card = load_card()
    toolchain = load_toolchain(args.toolchain_json)
    manifest = authoring_manifest(card, toolchain)
    if args.command == "manifest":
        write_new(args.output, rfc8785.dumps(manifest))
        print(json.dumps({"prepared": "manifest", "admitted": False}))
        return 0
    entry = search_candidate(card, manifest, read_object(args.compiler_receipt), toolchain)
    args.output_directory.mkdir(mode=0o700, exist_ok=False)
    write_new(args.output_directory / "entry.json", rfc8785.dumps(entry))
    write_new(args.output_directory / "Main.lean", materialize(manifest))
    print(json.dumps({"prepared": 1, "reviewed": False, "admitted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
