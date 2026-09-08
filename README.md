# capi-provider-ssh

[![CI](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml)
[![Container](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)

A Python infrastructure provider for [Cluster API](https://cluster-api.sigs.k8s.io/)
that bootstraps and cleans up pre-provisioned Linux hosts over authenticated SSH.
It coordinates host allocation, bootstrap execution, in-band reboot and deletion
with persistent ownership checks across controller restarts.

## Product scope

The OS and network must already be provisioned. The host preparation pipeline or
reviewed kubeadm bootstrap configuration supplies the container runtime and
Kubernetes packages. CAPI core, the kubeadm bootstrap provider and the kubeadm
control-plane provider retain their own lifecycle responsibilities.

The provider currently implements the **legacy v1beta1 CAPI contract**. Although
CAPI 1.11 introduced **v1beta2**, our CRD contract labels, core API access and
end-to-end tests still target the legacy integration. The
[contract comparison and migration plan](docs/capi-contract-migration.md) shows
what is implemented, what differs and the remaining steps.
Two controller replicas, API-aware readiness, host Leases and remote UID fencing
provide lifecycle HA. A provider outage does not stop existing workload pods.
Hardware power management, OS installation and a plugin runtime are not shipped.

Read the [support matrix](docs/support-matrix.md) before choosing versions or
planning production use. Tested behavior is distinct from a support SLA, hardware
certification or a completed workload rollout in a particular environment.

## Start here

| Task | Guide |
|---|---|
| Evaluate the product and its boundaries | [Architecture](docs/architecture.md) |
| Find, pull and pin a released container | [Container delivery](CONTAINER_IMAGES.md) |
| Install a reviewed provider in a management cluster | [Installation](docs/installation.md) |
| Configure inventory and Machines | [API and configuration reference](docs/api-reference.md) |
| Operate HA, pause, reboot and cleanup | [Operations](docs/operations.md) |
| Diagnose a failure | [Troubleshooting and FAQ](docs/faq.md) |
| Validate a change or contribute | [Development](DEVELOPMENT.md), [testing](docs/testing.md), [contributing](CONTRIBUTING.md) |
| Plan a release or GitOps rollout | [Release and delivery](docs/release-process.md) |
| Review trust and report a vulnerability | [Security policy](SECURITY.md), [SSH key lifecycle](docs/ssh-key-lifecycle.md) |
| Design an extension | [Plugin design boundary](docs/plugin-contract.md), [roadmap](docs/roadmap.md) |

The [documentation index](docs/README.md) identifies reference, procedures and
historical evidence. Public product documentation excludes environment credentials,
private host inventories and raw operational evidence bundles.

## Resources

All provider objects use `infrastructure.alpininsight.ai/v1beta1` and are namespaced.
The [structural CRDs](shared/crds/) are the authoritative field definitions.

| Kind | Responsibility |
|---|---|
| `SSHHost` | Host inventory, SSH reachability and UID-bound claim/cleanup state |
| `SSHCluster` | Infrastructure endpoint for the owning CAPI Cluster |
| `SSHClusterTemplate` | Template for cluster infrastructure |
| `SSHMachine` | Immutable allocation, bootstrap ownership, readiness and lifecycle |
| `SSHMachineTemplate` | Infrastructure template for CAPI-managed Machines |

Delete Machines through CAPI. Cleanup retains the host claim and finalizer until
owned cleanup succeeds; failed cleanup quarantines the host. Never bypass this
contract to make a teardown appear successful.

## Local validation

From `python/`, the default isolated lane uses the checked-in dependency lock:

```bash
uv sync --frozen --dev
uv run pytest -q -m 'not integration and not e2e and not kind'
```

Tests include real loopback SSH/TLS endpoints. The separate
[Kind lifecycle lane](docs/testing.md) uses disposable hosts and an explicit
test kubeconfig. Unit success alone does not certify a release or live rollout.

## License and contribution

[Mozilla Public License 2.0](LICENSE). Contributions follow [Conventional Commits](https://www.conventionalcommits.org/)
and the [Developer Certificate of Origin](DCO); sign commits with `git commit -s`.
Create a working branch from current `develop` and submit a PR back to `develop`.
See [CONTRIBUTING.md](CONTRIBUTING.md) for review and documentation requirements.
