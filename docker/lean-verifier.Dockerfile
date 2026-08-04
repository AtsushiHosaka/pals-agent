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

COPY lean-workspace/lean-toolchain lean-workspace/lakefile.lean \
    lean-workspace/lake-manifest.json ./

RUN xargs elan toolchain install < lean-toolchain \
    && lake update \
    && lake exe cache get

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
    PALS_LEAN_PROJECT_DIR=/app/lean-workspace

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
