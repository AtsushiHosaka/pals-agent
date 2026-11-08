# Definition only: the `stacks-4.35` library profile (Lean v4.35.0, Mathlib 56a0058, StacksCore).
# Not built or deployed by this repository's tooling. Build context is the pals-agent root.
#
# StacksFrontier (AI-generated, unreviewed) is never built into this image: its sources are removed
# from the working tree with a sparse checkout (so Lake still sees a clean repository), and the
# verifier additionally rejects any import outside Mathlib and StacksCore.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ELAN_HOME=/opt/elan \
    PATH="/opt/elan/bin:/usr/local/bin:/usr/bin:/bin"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git zstd \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
      | sh -s -- -y --default-toolchain none

WORKDIR /build/lean-workspace

COPY lean-workspaces/stacks-4.35/lean-toolchain lean-workspaces/stacks-4.35/lakefile.lean \
    lean-workspaces/stacks-4.35/lake-manifest.json ./

# The committed manifest pins every package; nothing is re-resolved (no `lake update`).
RUN xargs elan toolchain install < lean-toolchain \
    && lake exe cache get \
    && git -C .lake/packages/Stacks sparse-checkout set --no-cone \
      '/*' '!/StacksFrontier/' '!/StacksFrontier.lean' \
    && ! test -e .lake/packages/Stacks/StacksFrontier \
    && lake build StacksCore

WORKDIR /build

COPY pyproject.toml README.md ./
COPY pals_agent ./pals_agent

RUN pip wheel --wheel-dir /wheels .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ELAN_HOME=/opt/elan \
    PATH="/opt/elan/bin:/usr/local/bin:/usr/bin:/bin" \
    PALS_LEAN_PROJECT_DIR=/app/lean-workspace \
    PALS_LEAN_LIBRARY_PROFILE=stacks-4.35

RUN apt-get update \
    && apt-get install -y --no-install-recommends git libseccomp2 util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/elan /opt/elan
COPY --from=builder --chown=65532:65532 /build/lean-workspace /app/lean-workspace
COPY --from=builder /wheels /wheels

RUN pip install --no-index --find-links=/wheels pals-agent \
    && rm -rf /wheels

USER 65532:65532

CMD ["python", "-m", "pals_agent.lean_verifier.http_runtime"]
