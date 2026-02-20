FROM python:3.13-slim AS base

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies only
RUN uv sync --no-dev --no-editable

# Copy source code
COPY src/ src/

# Non-root user
RUN groupadd --gid 65532 nonroot && \
    useradd --uid 65532 --gid 65532 --no-create-home nonroot
USER 65532:65532

ENTRYPOINT ["uv", "run", "kopf", "run", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "src/capi_provider_ssh/main.py"]
