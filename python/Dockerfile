FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS base

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff /uv /usr/local/bin/uv

WORKDIR /app

# Copy all source and config for package installation
COPY pyproject.toml uv.lock README.md LICENSE package_version.py hatch_build.py ./
COPY capi_provider_ssh/ capi_provider_ssh/

# Install only locked production dependencies. The application uses uv rather
# than pip at runtime, so remove pip and its ensurepip bundle; both contain
# vendored packages that should not expand the runtime attack surface.
ARG PROVIDER_VERSION
RUN if [ -n "$PROVIDER_VERSION" ]; then export PROVIDER_VERSION; else unset PROVIDER_VERSION; fi; \
    uv sync --frozen --no-cache --no-dev --no-editable && \
    rm -rf capi_provider_ssh && \
    rm -f package_version.py hatch_build.py pyproject.toml uv.lock README.md && \
    python -m pip uninstall --yes pip && \
    python -c 'import pathlib, shutil, sysconfig; shutil.rmtree(pathlib.Path(sysconfig.get_path("stdlib")) / "ensurepip")'

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

ENTRYPOINT ["kopf", "run", "--all-namespaces", "--liveness=http://0.0.0.0:8080/healthz", "-m", "capi_provider_ssh.main"]
