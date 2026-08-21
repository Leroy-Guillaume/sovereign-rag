# syntax=docker/dockerfile:1

# ---- Stage 1: resolve dependencies and bake the embedding model ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency layer: only invalidated when the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra local --no-install-project

# Bake the embedding model into an image layer: no Hugging Face download at
# runtime, the container starts fully offline (frozen model, see README).
# Placed before the source COPY so editing src/ never re-downloads the weights.
# The model is a build argument so an operator upgrading embeddings (see the
# README's bge-m3 walkthrough) rebuilds with the matching weights baked in:
#   docker compose build --build-arg BAKED_EMBEDDING_MODEL=BAAI/bge-m3 api
ARG BAKED_EMBEDDING_MODEL=intfloat/multilingual-e5-small
RUN HF_HOME=/opt/hf-cache .venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${BAKED_EMBEDDING_MODEL}')"

# Same treatment for the reranker: only the files the adapter loads, with the
# adapter's own resolution order (ONNX export if published, torch weights
# otherwise; patterns mirrored from reranking/local.py -- keep in sync). The
# model is a build argument like the embedding model: switching rerankers
# means rebuilding with the matching weights baked in.
ARG BAKED_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RUN HF_HOME=/opt/hf-cache .venv/bin/python -c "\
from huggingface_hub import snapshot_download; from pathlib import Path; \
common = ['config.json', 'tokenizer*', 'special_tokens_map.json', 'sentencepiece*']; \
p = snapshot_download('${BAKED_RERANKER_MODEL}', allow_patterns=[*common, 'onnx/model_O3.onnx']); \
(Path(p) / 'onnx/model_O3.onnx').is_file() or \
snapshot_download('${BAKED_RERANKER_MODEL}', allow_patterns=[*common, '*.safetensors'])"

# Project layer: sources and migrations, then install the project itself.
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --extra local

# ---- Stage 2: minimal non-root runtime ----
FROM python:3.12-slim

# Apply the distribution security updates published since the base image was
# built. The CI gate rejects any fixable CRITICAL/HIGH finding, and the base
# image is rebuilt on its own cadence, not Debian's advisory cadence.
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 1000 --user-group --create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv ./.venv
COPY --from=builder --chown=app:app /app/src ./src
COPY --from=builder --chown=app:app /app/migrations ./migrations
COPY --from=builder --chown=app:app /opt/hf-cache /opt/hf-cache

ENV HF_HOME=/opt/hf-cache \
    HF_HUB_OFFLINE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD ["python", "-m", "sovereign_rag.healthcheck"]

USER app

CMD ["uvicorn", "sovereign_rag.main:app", "--host", "0.0.0.0", "--port", "8000"]
