# CLAUDE.md - capi-provider-ssh

## Project Overview

Minimal CAPI infrastructure provider for SSH-reachable hosts. Two implementations (Python, Rust) sharing the same CRDs and CAPI contract.

## Key Conventions

- Python 3.13, managed with `uv` exclusively
- Rust stable, managed with `cargo`
- Shared CRDs in `shared/crds/` -- both implementations use the same YAML
- API group: `infrastructure.alpininsight.ai/v1beta1`
- CRD kinds: `SSHCluster`, `SSHMachine`, `SSHMachineTemplate`
- No Helm -- raw YAML manifests only
- Conventional Commits for all commit messages
- No AI references in commit messages (ADR-004)

## CAPI Contract

Both implementations must fulfill:
- `status.initialization.provisioned` signals readiness
- `spec.providerID = "ssh://<address>"` identifies the node
- Finalizers handle cleanup (`kubeadm reset` via SSH)
- Pause/unpause via `spec.paused`

## Test Strategy

- Python: pytest
- Rust: `cargo test`
- Integration: both must pass the same functional test suite against a real cluster
