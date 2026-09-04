FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285 AS base

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff /uv /usr/local/bin/uv

WORKDIR /app

# Copy all source and config for package installation
COPY pyproject.toml uv.lock* README.md ./
COPY capi_provider_ssh/ capi_provider_ssh/

# Install only locked production dependencies. The application uses uv rather
# than pip at runtime, so remove pip and its ensurepip bundle; both contain
# vendored packages that should not expand the runtime attack surface.
RUN uv sync --frozen --no-cache --no-dev --no-editable && \
    python -m pip uninstall --yes pip && \
    rm -rf /usr/local/lib/python3.13/ensurepip

# Use the virtualenv created at build time; avoid runtime `uv run` cache writes.
ENV PATH="/app/.venv/bin:${PATH}"

# Non-root user
RUN groupadd --gid 65532 nonroot && \
    useradd --uid 65532 --gid 65532 --no-create-home nonroot
USER 65532:65532

# OCI labels (static fallback for standalone builds; CI overrides dynamic labels)
LABEL org.opencontainers.image.vendor="Alpin Insight Solutions" \
      org.opencontainers.image.licenses="MPL-2.0" \
      org.opencontainers.image.url="https://github.com/alpininsight/capi-provider-ssh" \
      org.opencontainers.image.source="https://github.com/alpininsight/capi-provider-ssh" \
      org.opencontainers.image.description="Cluster API infrastructure provider for SSH-reachable hosts"

ENTRYPOINT ["kopf", "run", "--all-namespaces", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "-m", "capi_provider_ssh.main"]
