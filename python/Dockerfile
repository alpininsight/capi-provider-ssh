FROM python:3.14-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS base

# The pinned Trixie base includes APT 3.0.4 and the prior security updates.
# Apply the zlib security fix which is not yet included in that base.
RUN apt-get update && \
    apt-get install --yes --no-install-recommends --only-upgrade \
        zlib1g=1:1.3.dfsg+really1.3.1-1+deb13u1 && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff /uv /usr/local/bin/uv

WORKDIR /app

# Copy all source and config for package installation
COPY pyproject.toml uv.lock README.md LICENSE NOTICE package_version.py hatch_build.py ./
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
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.url="https://github.com/alpininsight/capi-provider-ssh" \
      org.opencontainers.image.source="https://github.com/alpininsight/capi-provider-ssh" \
      org.opencontainers.image.description="Cluster API infrastructure provider for SSH-reachable hosts"

ENTRYPOINT ["kopf", "run", "--all-namespaces", "--liveness=http://0.0.0.0:8080/healthz", "-m", "capi_provider_ssh.main"]
