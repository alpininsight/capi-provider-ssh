# Development Setup

This guide covers the tools and setup required for local development of capi-provider-ssh.

## Required Tools

| Tool | Purpose | Version |
|------|---------|---------|
| **uv** | Python package manager | 0.9+ |
| **Python** | Runtime (managed by uv) | 3.13+ |
| **nerdctl** | Container builds (via Lima/containerd) | 2.0+ |
| **kubectl** | Kubernetes CLI | 1.30+ |
| **clusterctl** | Cluster API CLI | 1.9+ |
| **kustomize** | Manifest rendering | 5+ |
| **GitVersion** | Semantic versioning | 6+ |
| **pre-commit** | Git hooks (via uvx) | - |

### Optional Tools

| Tool | Purpose | Version |
|------|---------|---------|
| **kind** | Local management cluster | 0.25+ |
| **Lima** | macOS VM-based management cluster | 1.0+ |

## Installation

### Ubuntu / Debian

```bash
# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # or ~/.zshrc

# containerd + nerdctl
# See: https://github.com/containerd/nerdctl
# On Lima VMs, nerdctl is available via: limactl shell <vm> nerdctl

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm kubectl

# clusterctl
curl -L https://github.com/kubernetes-sigs/cluster-api/releases/latest/download/clusterctl-linux-$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') -o clusterctl
sudo install -o root -g root -m 0755 clusterctl /usr/local/bin/clusterctl && rm clusterctl

# kustomize
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
sudo mv kustomize /usr/local/bin/

# GitVersion
# Download from: https://github.com/GitTools/GitVersion/releases
# Or use dotnet tool:
dotnet tool install --global GitVersion.Tool
```

### macOS

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Lima (containerd + nerdctl included)
brew install lima

# Kubernetes tools
brew install kubectl clusterctl kustomize

# GitVersion
brew install gitversion
# Or: dotnet tool install --global GitVersion.Tool

# Optional: kind (local management cluster)
brew install kind
```

## Shell Setup (zsh)

If using zsh, ensure your PATH includes uv and local binaries:

```bash
# Add to ~/.zshrc if not present
export PATH="$HOME/.local/bin:$PATH"
```

## Verification

Run these commands to verify your setup:

```bash
# Required tools
uv --version          # Should show 0.9+
nerdctl --version     # Should show 2.0+ (via Lima)
kubectl version --client  # Should show 1.30+
clusterctl version    # Should show 1.9+
kustomize version     # Should show 5+

# After uv sync in python/
uv run python --version  # Should show 3.13+
```

## Project Setup

### Python Provider

```bash
cd python
uv sync

# Install pre-commit hooks
uvx pre-commit install
uvx pre-commit install --hook-type commit-msg

# Validate configured hooks
uvx pre-commit validate-config

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .
```

### CRDs

Apply shared CRDs to a management cluster:

```bash
kubectl apply -k shared/crds/
```

## Running Tests

```bash
# Python tests
cd python && uv run pytest

# Python with coverage
cd python && uv run pytest --cov

# Pre-commit hooks (from repo root)
uvx pre-commit run --all-files
```

## Code Quality

```bash
# Python: lint + format
cd python
uv run ruff check .
uv run ruff format .

```

## Lifecycle regression lanes

`uv run pytest -m "not integration and not e2e and not kind"` covers persisted API contracts,
real loopback SSH trust, cleanup failures, dry-run, pause, reboot observation and
cross-replica locking. Explicit integration/E2E lanes fail when prerequisites are
missing; an unexecuted lane is not a passing lifecycle test.

The disposable Kind lane uses an explicit loopback kubeconfig, two provider
replicas, real CAPI/CABPK/KCP and Linux kubeadm targets. Its fixtures do not use
the default management kubeconfig. Never point destructive lifecycle tests at a
management-cloud context. Test Secrets remain available until cleanup succeeds;
no test helper may strip finalizers to make a failed teardown pass.

SSH-only E2E requires `E2E_SSH_HOST`, `E2E_SSH_KEY_PATH` and
`E2E_SSH_KNOWN_HOSTS_PATH`. The nightly workflow reads independently verified
host trust from `E2E_SSH_KNOWN_HOSTS`; missing trust fails the lane before SSH.
See [the support matrix](docs/support-matrix.md) and [operations](docs/operations.md).
