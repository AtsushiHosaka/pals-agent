"""Prepare unsealed search candidates from an externally obtained compiler receipt.

No DB/provider access, key generation, review, signature, or admission occurs here.
The receipt file must be exported from the real admitted Recipe; the release
admitter independently checks its identity against that immutable DB evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import rfc8785

ROOT = Path(__file__).resolve().parent
DIGEST = re.compile(r"[0-9a-f]{64}")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def read_object(path: Path) -> dict:
    value = json.loads(path.read_bytes(), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def materialize(manifest: dict) -> bytes:
    if (
        manifest["schema_version"] != "pals.recipe-authoring-manifest.v1"
        or manifest["kind"] != "exact_target_proof"
        or manifest["imports"] != ["Mathlib"]
        or manifest["environment"] != {"namespace": None, "opens": []}
        or not manifest["proof_body"].startswith("by")
    ):
        raise ValueError("unsupported authoring manifest")
    return (
        "import Mathlib\n\nexample : "
        + manifest["target_source"]
        + " := "
        + manifest["proof_body"]
        + "\n"
    ).encode()


def search_candidate(case: dict, manifest: dict, receipt: dict) -> dict:
    """Pure binding check, not proof of the supplied receipt's origin or authority."""
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
        or not DIGEST.fullmatch(receipt["compiler_command_sha256"])
        or case["id"] != manifest["recipe_id"]
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
        "recipe_id": manifest["recipe_id"],
        "recipe_revision": manifest["revision"],
        "statement": case["question"],
        "domain": case["family_id"],
        "assumptions": case["assumptions"],
        # Exact quantification is retained in the formal conclusion below.
        "quantifiers": [],
        "conclusion": manifest["target_source"],
        "proof_method_tag": None,
        "search_text": case["question"] + "\n" + "\n".join(case["assumptions"]),
        "output_language": "ja",
        "answer": case["answer"],
        "answer_sha256": sha(case["answer"].encode()),
        "target_sha256": sha(manifest["target_source"].encode()),
        "lean_sha256": sha(source),
        "compiler_receipt_sha256": sha(rfc8785.dumps(receipt)),
        "toolchain_sha256": fingerprint_hash,
    }


def write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--compiler-receipt", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    cases = read_object(ROOT / "corpus.json")["cases"]
    selected = [case for case in cases if case["id"] == args.recipe_id]
    if len(selected) != 1:
        raise ValueError("exactly one known Recipe required")
    manifest = read_object(ROOT / "publication" / (args.recipe_id + ".json"))
    entry = search_candidate(selected[0], manifest, read_object(args.compiler_receipt))
    args.output_directory.mkdir(mode=0o700, exist_ok=False)
    write_new(args.output_directory / "entry.json", rfc8785.dumps(entry))
    write_new(args.output_directory / "Main.lean", materialize(manifest))
    print(json.dumps({"prepared": 1, "reviewed": False, "admitted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
