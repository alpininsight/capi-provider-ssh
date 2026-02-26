# capi-provider-ssh

[![CI](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml)
[![Container](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml)
[![GitHub Release](https://img.shields.io/github/v/release/alpininsight/capi-provider-ssh)](https://github.com/alpininsight/capi-provider-ssh/releases/latest)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)

A minimal [Cluster API](https://cluster-api.sigs.k8s.io/) infrastructure provider for SSH-reachable hosts.

Two implementations sharing the same CRDs and contract:

| Implementation | Directory | Language | Framework |
|---------------|-----------|----------|-----------|
| Python | `python/` | Python 3.13+ | kopf + asyncssh |
| Rust | `rust/` | Rust (stable) | kube-rs + russh |

## Purpose

Manage Kubernetes lifecycle on pre-provisioned servers reachable via SSH. No cloud API, no BMC/IPMI, no vendor lock-in.

**Use case:** Dedicated servers, colocated hardware, or edge nodes reachable via SSH — with OS already installed (rescue mode, cloud-init, PXE, or manual).

## Architecture

```
Management Cluster
├── CAPI Core Controller
├── kubeadm Bootstrap Provider
├── kubeadm Control Plane Provider
└── capi-provider-ssh Controller  ← this project
        │
        │ SSH (direct, VPN, or mesh)
        ▼
Target Hosts (any SSH-reachable server)
├── kubeadm init/join (executed by provider)
└── K8s node joins workload cluster
```

## CRDs

| Kind | Purpose |
|------|---------|
| `SSHCluster` | Cluster-level infrastructure (control plane endpoint) |
| `SSHClusterTemplate` | ClusterClass template for `SSHCluster` objects |
| `SSHMachine` | Per-machine infrastructure (SSH address, credentials) |
| `SSHMachineTemplate` | Template for MachineDeployments |

### ClusterClass Template Example

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHClusterTemplate
metadata:
  name: ssh-cluster-template
  namespace: default
spec:
  template:
    spec:
      controlPlaneEndpoint:
        host: 10.0.0.10
        port: 6443
---
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHMachineTemplate
metadata:
  name: ssh-worker-template
  namespace: default
spec:
  template:
    spec:
      hostSelector:
        matchLabels:
          role: worker
---
apiVersion: cluster.x-k8s.io/v1beta1
kind: ClusterClass
metadata:
  name: ssh-clusterclass
  namespace: default
spec:
  infrastructure:
    ref:
      apiVersion: infrastructure.alpininsight.ai/v1beta1
      kind: SSHClusterTemplate
      name: ssh-cluster-template
  workers:
    machineDeployments:
      - class: default-worker
        template:
          infrastructure:
            ref:
              apiVersion: infrastructure.alpininsight.ai/v1beta1
              kind: SSHMachineTemplate
              name: ssh-worker-template
```

## CAPI Contract

Both implementations fulfill the same [CAPI provider contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/overview):

- `status.initialization.provisioned` signals readiness
- `spec.providerID` identifies the node
- Finalizers handle cleanup (kubeadm reset)
- Pause/unpause behavior supported

## Bootstrap Configuration

Host preparation (installing containerd, kubeadm, kubelet) is handled by the
**kubeadm bootstrap provider** via `preKubeadmCommands` — not by this
infrastructure provider. No external tools (Ansible, Puppet, etc.) are needed.

```yaml
# KubeadmControlPlane or KubeadmConfigTemplate
spec:
  kubeadmConfigSpec:
    preKubeadmCommands:
      # System prerequisites
      - swapoff -a && sed -i '/swap/d' /etc/fstab
      - modprobe overlay && modprobe br_netfilter

      # Container runtime
      - apt-get update && apt-get install -y containerd
      - systemctl enable --now containerd

      # Kubernetes packages
      - |
        curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key \
          | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
        echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
          https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /" \
          > /etc/apt/sources.list.d/kubernetes.list
        apt-get update
        apt-get install -y kubelet kubeadm kubectl
        apt-mark hold kubelet kubeadm kubectl
        systemctl enable kubelet
```

See [docs/architecture.md](docs/architecture.md) for the full rationale and
production-ready examples.

## SSH Key Lifecycle

SSH private key management is standardized for GitOps workflows:

- SOPS-encrypted Secret manifests
- External Secrets syncing from a central secret manager
- Versioned key rotation runbook with rollback steps

See [docs/ssh-key-lifecycle.md](docs/ssh-key-lifecycle.md) and
[python/deploy/examples/ssh-key-lifecycle/](python/deploy/examples/ssh-key-lifecycle/).

## RBAC Requirements

See [docs/rbac-requirements.md](docs/rbac-requirements.md) for the full set of
RBAC permissions the controller requires. The reference implementation is in
[python/deploy/rbac.yaml](python/deploy/rbac.yaml).

## External Etcd

The SSHMachine resource supports optional external etcd wiring -- distributing
certificates and patching kubeadm configuration for external etcd clusters.

See [docs/external-etcd.md](docs/external-etcd.md) for the Secret format
contract and configuration reference.

## Flux Rollout

If CAPI cluster reconciliation is suspended in Flux, use the explicit rollout
procedure in [docs/flux-rollout.md](docs/flux-rollout.md) to:

- reconcile provider manifests first
- unsuspend `capi-clusters`
- verify health and rollback quickly if needed

For a full pre-release validation including per-phase teardown/remove steps,
use [docs/live-rollout-validation.md](docs/live-rollout-validation.md).

## DNS Cutover

For promoting staging to production traffic with rollback safety, use
[docs/dns-cutover.md](docs/dns-cutover.md).

## FAQ

See [docs/faq.md](docs/faq.md) for answers to common questions about RBAC/Kopf
permissions, cleanup behavior, health probing details, and troubleshooting.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for full setup instructions.

```bash
# Python
cd python && uv sync && uv run pytest

# Rust
cd rust && cargo test

# Apply CRDs
kubectl apply -k shared/crds/
```

## Contributing

We welcome contributions! By contributing to this project, you agree to the [Developer Certificate of Origin (DCO)](DCO).

All commits must be signed off to certify that you wrote or have the right to submit the code:

```bash
git commit -s -m "feat: add my contribution"
```

This adds a `Signed-off-by` trailer to your commit message. If you forget, amend the commit:

```bash
git commit --amend -s
```

### Branch rules

- `main` and `develop` are protected -- all changes require a pull request
- Branch naming: `<type>/<short-description>` (e.g. `feat/add-ssh-key-rotation`)
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)

## License

This project is licensed under the [Mozilla Public License 2.0](LICENSE).

## Related

- [insight-lima-k8s-capi](https://github.com/alpininsight/insight-lima-k8s-capi) - Management cluster (consumer of this provider)
- [CAPI Provider Contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/overview)
- [KubeCon 2022 Provider Tutorial](https://github.com/capi-samples/kubecon-na-2022-tutorial)
