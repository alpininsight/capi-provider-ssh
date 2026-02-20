# Development Setup

This guide covers the tools and setup required for local development of capi-provider-ssh.

## Required Tools

| Tool | Purpose | Version |
|------|---------|---------|
| **uv** | Python package manager | 0.9+ |
| **Python** | Runtime (managed by uv) | 3.13+ |
| **Rust** | Rust toolchain (rustup) | stable |
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

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

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

# Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

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

If using zsh, ensure your PATH includes uv, cargo, and local binaries:

```bash
# Add to ~/.zshrc if not present
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
```

## Verification

Run these commands to verify your setup:

```bash
# Required tools
uv --version          # Should show 0.9+
rustc --version       # Should show stable
cargo --version       # Should show matching version
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

### Rust Provider

```bash
cd rust

# Build
cargo build

# Run tests
cargo test

# Lint
cargo clippy -- -D warnings

# Format
cargo fmt --check
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

# Rust tests
cd rust && cargo test

# Pre-commit hooks (from repo root)
uvx pre-commit run --all-files
```

## Code Quality

```bash
# Python: lint + format
cd python
uv run ruff check .
uv run ruff format .

# Rust: lint + format
cd rust
cargo clippy -- -D warnings
cargo fmt --check
```
