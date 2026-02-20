# capi-provider-ssh

A minimal [Cluster API](https://cluster-api.sigs.k8s.io/) infrastructure provider for SSH-reachable hosts.

Two implementations sharing the same CRDs and contract:

| Implementation | Directory | Language | Framework |
|---------------|-----------|----------|-----------|
| Python | `python/` | Python 3.13 | kopf + asyncssh |
| Rust | `rust/` | Rust (stable) | kube-rs + russh |

## Purpose

Manage Kubernetes lifecycle on pre-provisioned servers reachable via SSH. No cloud API, no BMC/IPMI, no vendor lock-in.

**Use case:** Dedicated servers (Hetzner, Strato, OVH, ...) connected via Tailscale/Headscale mesh, with OS already installed via Ansible.

## Architecture

```
Management Cluster (Lima VMs, arm64)
├── CAPI Core Controller
├── kubeadm Bootstrap Provider
├── kubeadm Control Plane Provider
└── capi-provider-ssh Controller  ← this project
        │
        │ SSH (via Tailscale IPs)
        ▼
Target Hosts (Hetzner/Strato, amd64)
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
