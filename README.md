# capi-provider-ssh

[![CI](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml)
[![Container](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)

**Cluster API for the servers you already have.**

Every other Cluster API infrastructure provider creates machines: it calls a
cloud API, starts a VM, or boots bare metal through a management controller.
This one adopts machines that already exist. Point it at a Linux host it can
reach over SSH, and Cluster API manages that host as first-class infrastructure.

A Python infrastructure provider for [Cluster API](https://cluster-api.sigs.k8s.io/)
that bootstraps and cleans up pre-provisioned Linux hosts over authenticated SSH.
It coordinates host allocation, bootstrap execution, in-band reboot and deletion
with persistent ownership checks across controller restarts.

- **Survives its own restarts.** Host claims are UID-bound and persisted, so a
  controller crash never orphans a host or hands the same one out twice.
- **Two replicas, no single point of failure.** Host Leases and API-aware
  readiness mean a provider outage leaves running workload pods untouched.
- **Refuses to lie about teardown.** Failed cleanup quarantines the host and
  keeps the finalizer instead of reporting a deletion that did not happen.
- **In production.** It runs the Alpin Insight management cluster, delivered by
  GitOps and pinned by image digest.

## The same provider from a laptop VM to a datacenter

The requirement list is deliberately short.

| Required on the host | Not required anywhere |
|---|---|
| Linux, reachable over SSH with verified trust | A hypervisor or cloud API |
| Root-capable operations and `flock` | A BMC, Redfish or IPMI |
| A prepared container runtime and kubeadm baseline | An agent installed on the host |
| Nothing else | A cloud account, or any vendor at all |

Nothing in the left column is vendor-specific, so a Lima VM on a MacBook, a
Proxmox guest in a homelab, a repurposed NUC and a hosted root server are the
same case, handled by the same provider. Alpin Insight runs both ends of that
range: local development clusters on notebook VMs, and the production management
cluster on hosted servers.

This is not a claim that Cluster API was previously unusable outside a
datacenter. The upstream
[Docker provider](https://github.com/kubernetes-sigs/cluster-api/tree/main/test/infrastructure/docker)
covers local development, and providers exist for Proxmox, KubeVirt and vSphere.
The difference is the size of the prerequisite. Metal3 and Tinkerbell need
out-of-band management hardware, which most homelab and no notebook has.
Hypervisor providers need that hypervisor's API, which ties the cluster to the
platform underneath it. This provider needs an SSH login.

### Where the hardware plugin fits

Out-of-band power management is **not shipped**. The
[plugin design boundary](docs/plugin-contract.md) and the
[protocol-based taxonomy research](docs/roadmap/protocol-based-hardware-taxonomy.md)
plan it around protocols instead of vendor names: one `redfish` plugin covering
HPE iLO, Dell iDRAC, Lenovo XCC and Supermicro alike, plus `ipmi` for older
servers, `snmp` for smart PDUs and `gpio` for single-board computers such as
Raspberry Pi and Jetson.

That work exists for physical hardware which also needs remote power control. A
notebook VM or a homelab hypervisor guest needs none of it: whatever created
those hosts powers them on, and SSH is enough. Plugins are a separate capability
decision in the [roadmap](docs/roadmap.md), not a prerequisite for the cases
above.

## Product scope

The OS and network must already be provisioned. The host preparation pipeline or
reviewed kubeadm bootstrap configuration supplies the container runtime and
Kubernetes packages. CAPI core, the kubeadm bootstrap provider and the kubeadm
control-plane provider retain their own lifecycle responsibilities.

Hardware power management, OS installation and a plugin runtime are not shipped.
Two controller replicas, API-aware readiness, host Leases and remote UID fencing
provide lifecycle HA.

### Versions and CAPI contract

Validated against CAPI core, the kubeadm bootstrap provider and the kubeadm
control-plane provider at **1.12.11**, with an upgrade bridge tested from 1.9.2,
on management Kubernetes 1.34.11. Container images are published for linux/amd64
and linux/arm64; see the
[releases](https://github.com/alpininsight/capi-provider-ssh/releases) for the
current version.

The provider implements the **v1beta1 CAPI contract**. CAPI 1.11 introduced
v1beta2, and our CRD contract labels, core API access and end-to-end tests still
target the v1beta1 integration; the migration is the Q4 2026 roadmap item. The
[contract comparison and migration plan](docs/capi-contract-migration.md) shows
what is implemented, what differs and the remaining steps.

Read the [support matrix](docs/support-matrix.md) before choosing versions or
planning production use. Tested behavior is distinct from a support SLA, hardware
certification or a completed workload rollout in a particular environment.

## What this provider is and how to use it

| Question | Documentation |
|---|---|
| What is the provider? | This [README](README.md): a Python-based CAPI infrastructure provider, not a VM or OS provisioner. |
| Where does it run? | [Architecture](docs/architecture.md): two controller replicas in the management cluster. |
| How is it installed? | [Installation](docs/installation.md): CRDs, RBAC, Deployment/PDB and GitOps delivery order. |
| How is it used? | [API and configuration reference](docs/api-reference.md): `SSHHost`, `SSHCluster`, `SSHMachine` and the CAPI ownership chain. |
| How is it delivered? | [Container delivery](CONTAINER_IMAGES.md): GHCR image, release tag and digest pinning. |
| What is out of scope? | [Architecture](docs/architecture.md): OS installation, hardware power management, cloud VM creation and a plugin runtime. |

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

[Mozilla Public License 2.0](LICENSE), copyright in [NOTICE](NOTICE). Contributions follow [Conventional Commits](https://www.conventionalcommits.org/)
and the [Developer Certificate of Origin](DCO); sign commits with `git commit -s`.
Create a working branch from current `develop` and submit a PR back to `develop`.
See [CONTRIBUTING.md](CONTRIBUTING.md) for review and documentation requirements.
