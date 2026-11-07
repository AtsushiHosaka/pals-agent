# Definition only: the `stacks-frontier-4.35` library profile. Not built or deployed by this
# repository's tooling. Build context is the pals-agent root.
#
# Proofs may import the StacksFrontier modules listed in FRONTIER_MODULES (and only those: nothing
# else is built, so any other Frontier import fails with "unknown module"). Statements may not use
# a Frontier constant; the verifier's trusted audit enforces that. The image does NOT enable the
# profile: the deployment must also set PALS_LEAN_ALLOW_FRONTIER_PROOFS=true, otherwise the
# verifier refuses to start.
#
#   docker build -f docker/lean-verifier-stacks-frontier.Dockerfile \
#     --build-arg FRONTIER_MODULES="StacksFrontier.AlgebraicGeometry.Scheme.AffineOpenNeighborhood" .
#
# Every listed module and its Stacks import closure is first screened with the verifier's own
# source policy (no notation/macro/elab/initialize/unsafe/native evaluation ...); a module that
# fails the screen stops the build. Choose modules by closure size: a typical Frontier lemma pulls
# in hundreds to thousands of modules (see the PR for measurements).
FROM python:3.12-slim AS builder

ARG FRONTIER_MODULES

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

COPY pals_agent/lean_source_policy.py /build/pals_agent/lean_source_policy.py
COPY scripts/audit_frontier_closure.py /build/scripts/audit_frontier_closure.py

# The committed manifest pins every package; nothing is re-resolved (no `lake update`).
RUN test -n "${FRONTIER_MODULES}" \
    && xargs elan toolchain install < lean-toolchain \
    && lake exe cache get \
    && touch /build/pals_agent/__init__.py \
    && PYTHONPATH=/build python3 -I /build/scripts/audit_frontier_closure.py \
      .lake/packages/Stacks ${FRONTIER_MODULES} \
    && lake build StacksCore ${FRONTIER_MODULES}

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
    PALS_LEAN_LIBRARY_PROFILE=stacks-frontier-4.35

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
