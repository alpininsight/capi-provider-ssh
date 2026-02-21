FROM python:3.13-slim AS base

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy all source and config for package installation
COPY pyproject.toml uv.lock* README.md ./
COPY capi_provider_ssh/ capi_provider_ssh/

# Install production dependencies and the package itself
RUN uv sync --no-dev --no-editable

# Use the virtualenv created at build time; avoid runtime `uv run` cache writes.
ENV PATH="/app/.venv/bin:${PATH}"

# Non-root user
RUN groupadd --gid 65532 nonroot && \
    useradd --uid 65532 --gid 65532 --no-create-home nonroot
USER 65532:65532

ENTRYPOINT ["kopf", "run", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "capi_provider_ssh/main.py"]
