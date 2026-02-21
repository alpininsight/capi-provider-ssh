# Container Images

This document lists all container images used in this project for development, testing, and production.

## Provider Images

### Python Provider

| Image | Version | Purpose | Used In |
|-------|---------|---------|---------|
| `python` | 3.13-slim | Application runtime | Dockerfile |

### Rust Provider

| Image | Version | Purpose | Used In |
|-------|---------|---------|---------|
| `rust` | latest | Build stage | Dockerfile |
| `debian` | bookworm-slim | Runtime stage | Dockerfile |

## Testing

| Image | Version | Purpose | Used In |
|-------|---------|---------|---------|
| `kindest/node` | v1.34.x | CAPI integration tests | kind clusters |

## Pre-pull Images

To pre-pull all required images for offline development:

```bash
# Python provider
nerdctl pull python:3.13-slim

# Rust provider
nerdctl pull rust:latest
nerdctl pull debian:bookworm-slim

# Testing (kind)
nerdctl pull kindest/node:v1.34.4
```

## Check Available Images

```bash
nerdctl images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
```

## Version Policy

- **Python**: Target 3.13 stable, update when dependencies support newer versions
- **Rust**: Latest stable toolchain for builds
- **Debian**: bookworm-slim for minimal Rust runtime
- **kind**: Match target Kubernetes version

## Image Updates

When updating image versions:

1. Update `Dockerfile` for base images
2. Update `.github/workflows/` for CI images
3. Update this file to reflect changes
4. Test locally before committing
