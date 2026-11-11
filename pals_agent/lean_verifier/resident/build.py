"""Build the resident worker's C part at image build time.

    python -m pals_agent.lean_verifier.resident.build --lean /opt/elan/toolchains/<v>/bin/lean \
        --out /opt/pals/pals_resident_shim.so

The verifier then passes ``ResidentConfig(prebuilt_shim=..., allow_shim_compile=False)`` and needs
neither a C compiler nor a writable directory for it at run time.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pals_agent.lean_verifier.resident.manager import compile_shim


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lean", required=True, help="the pinned toolchain's lean binary")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cc", default=None)
    args = parser.parse_args()
    compile_shim(args.lean, args.out, args.cc)
    print(args.out)


if __name__ == "__main__":
    main()
