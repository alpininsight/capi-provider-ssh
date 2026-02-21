# capi-provider-ssh

A minimal [Cluster API](https://cluster-api.sigs.k8s.io/) infrastructure provider for SSH-reachable hosts.

Two implementations sharing the same CRDs and contract:

| Implementation | Directory | Language | Framework |
|---------------|-----------|----------|-----------|
| Python | `python/` | Python 3.13 | kopf + asyncssh |
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
| `SSHMachine` | Per-machine infrastructure (SSH address, credentials) |
| `SSHMachineTemplate` | Template for MachineDeployments |

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
