# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first. Without this pip pulls the CUDA build for
# sentence-transformers and the image grows by several gigabytes for no benefit.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY pyproject.toml ./
COPY centerton_rag ./centerton_rag
COPY rag_rulebook/rules ./rag_rulebook/rules
COPY rag_rulebook/test_cases ./rag_rulebook/test_cases
COPY rag_rulebook/tools/__init__.py rag_rulebook/tools/emergency_matcher.py ./rag_rulebook/tools/
COPY rag_rulebook/__init__.py ./rag_rulebook/

RUN pip install .

# The rulebook version is baked into the image. Mounting a different rulebook at
# runtime would put the matcher and the rules out of step, which is the drift
# ADR-0022 removed, so RAG_RULEBOOK_ROOT should be left at its default.
ENV RAG_RULEBOOK_ROOT=/app/rag_rulebook

EXPOSE 8001

# Not published to the host. Spring reaches this over the docker network as
# http://centerton-rag:8001.
CMD ["uvicorn", "centerton_rag.main:app", "--host", "0.0.0.0", "--port", "8001"]
