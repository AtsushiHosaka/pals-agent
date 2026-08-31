FROM python:3.12.13-slim

ARG PALS_PFI_BUILD_PROVENANCE_V1
ARG PALS_PFI_BUILD_PROVENANCE_SHA256

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY pals_agent ./pals_agent
COPY --chown=65532:65532 \
    build/proof-flow-index/rootfs/opt/pals/draft-seed.json \
    /opt/pals/draft-seed.json

RUN pip install --upgrade pip \
    && pip install . \
    && test -n "${PALS_PFI_BUILD_PROVENANCE_V1}" \
    && test -n "${PALS_PFI_BUILD_PROVENANCE_SHA256}"

LABEL io.pals.draft-retrieval-provenance.v1="${PALS_PFI_BUILD_PROVENANCE_V1}" \
    io.pals.draft-retrieval-provenance.sha256="${PALS_PFI_BUILD_PROVENANCE_SHA256}"

USER 65532:65532

CMD ["pals-agent", "worker"]
