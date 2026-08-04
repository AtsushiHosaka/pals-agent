#!/usr/bin/env python3
"""Build the deterministic 110-card continuity-v1 catalog from the retained 37-card base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pals_agent.continuity_collection import (
    build_catalog,
    canonical_catalog_bytes,
    catalog_sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    payload, _proofs = build_catalog(source)
    args.destination.write_bytes(canonical_catalog_bytes(payload))
    print(json.dumps({"cards": len(payload["cards"]), "sha256": catalog_sha256(payload)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
