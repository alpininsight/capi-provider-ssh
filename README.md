# capi-provider-ssh

[![CI](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/ci-python.yml)
[![Container](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml/badge.svg)](https://github.com/alpininsight/capi-provider-ssh/actions/workflows/container-build-python.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-brightgreen.svg)](LICENSE)

**Use the Linux servers you already have to build Kubernetes clusters with Cluster API.**

CAPI Provider SSH is an open source infrastructure controller for
[Cluster API (CAPI)](https://cluster-api.sigs.k8s.io/). It connects CAPI's desired
cluster state to existing Linux servers or VMs using verified SSH. Your
infrastructure team prepares the hosts; your platform team defines the cluster;
the controller assigns hosts and executes the supplied bootstrap and cleanup work.

The provider runs in a **management cluster**. Applications run in the
**workload clusters** managed from there. Installing the controller does not
create a workload cluster or take ownership of existing Kubernetes nodes.

## Who uses it, and for what?

| Who or component | Responsibility | Result |
|---|---|---|
| Infrastructure team or host preparation pipeline | Supply Linux hosts, OS, network, verified SSH identity and runtime/package prerequisites | Hosts ready to be assigned to Kubernetes Machines |
| Platform team / DevOps | Define the cluster, host inventory, control-plane and worker counts, credentials and trust | Reviewed desired state in Kubernetes manifests |
| GitOps controller, if used | Deliver the reviewed manifests and immutable image pin | Reproducible manifest delivery; separate from lifecycle reconciliation |
| CAPI core, kubeadm bootstrap and control-plane controllers | Orchestrate Machines, generate bootstrap data and manage control-plane lifecycle | The Kubernetes cluster lifecycle and bootstrap instructions |
| **SSH provider** | Assign prepared hosts, verify SSH trust, execute bootstrap, observe operations and perform owned cleanup | The infrastructure part of each Machine's lifecycle |
| Application teams | Deploy applications and jobs to the resulting Kubernetes cluster | Consume Kubernetes without operating the SSH provider directly |

For example, to grow a workload cluster **from two to three workers**, DevOps
increases the worker `MachineDeployment` replica count. CAPI creates another
Machine. The SSH provider claims a matching prepared host, executes the supplied
bootstrap instructions and reports infrastructure state. The host joins the
workload cluster. **The extra host must already exist**; this provider does not
create a VM or install its operating system.

The [getting-started explanation](docs/getting-started.md) walks through the
roles, objects and lifecycle. Use [installation](docs/installation.md) for the
actual prerequisites and delivery procedure.

## What it provides

- **Persistent host ownership.** UID-bound claims and durable operation receipts
  preserve identity across controller restarts. Ambiguous ownership blocks work.
- **Coordinated controller HA.** Two replicas use peering, host Leases and remote
  fencing. Management-cluster and workload control-plane HA are separate concerns.
- **Guarded cleanup.** Failed cleanup quarantines the host and retains its claim
  and finalizer. Delete Machines through CAPI; do not force finalizers away.
- **Verified SSH trust.** Host keys or CA trust must be verified independently
  before privileged lifecycle commands are permitted.

The same prepared-host model can be used with a Linux VM or a physical server.
A cloud or hypervisor API, BMC and host agent are not required. Host preparation
must supply Linux, reachable SSH, the required privileges, `flock` and the
container-runtime/kubeadm baseline. See the [support matrix](docs/support-matrix.md)
for tested combinations rather than assuming every platform is certified.

## Scope and delivery

| Question | Answer and next document |
|---|---|
| Is it a Python client or a command-line tool? | It is a Python-based Kubernetes controller. The container is the normal deployment artifact; Python package code is for runtime and development. See [getting started](docs/getting-started.md). |
| Where does it run? | In the management cluster, with two coordinated controller replicas. See [architecture](docs/architecture.md). |
| How do I install it? | Review and deliver CRDs, RBAC, peering, Deployment and PDB. See [installation](docs/installation.md). |
| How do I define hosts and Machines? | Use `SSHHost`, `SSHCluster`, `SSHMachine` and CAPI resources. See the [API reference](docs/api-reference.md). |
| Why can the fleet be empty? | Controllers wait for explicitly created workload-cluster resources. See the [fleet FAQ](docs/faq.md#why-is-the-capi-fleet-empty-even-though-the-controller-is-healthy). |
| Where is the released container? | GHCR, with release tags and immutable digests. See [container delivery](CONTAINER_IMAGES.md). |
| What is outside its scope? | VM creation, OS installation, hardware power management, DNS/application traffic cutover and automatic adoption of existing clusters. See [architecture](docs/architecture.md). |
| Are hardware plugins available? | No plugin runtime or out-of-band driver is shipped. See the [design boundary](docs/plugin-contract.md) and [roadmap](docs/roadmap.md). |

This repository contains the open source product and its contributor guidance.
Operator-specific inventories, deployment records, service commitments and
internal service procedures belong in the operator's access-controlled records.
No commercial SLA or managed service is included by installing the controller.

## Compatibility

The provider implements the **v1beta1 CAPI contract**. The validated baseline is
CAPI core/CABPK/KCP **1.12.11** on management Kubernetes **1.34.11**, with a tested
upgrade bridge from CAPI 1.9.2. Images are published for linux/amd64 and linux/arm64.
Use the [latest release](https://github.com/alpininsight/capi-provider-ssh/releases/latest)
and its immutable source/image evidence for the version you deploy.

CAPI v1beta2 migration is planned; it is not completed by the current CRD API
name. Read the [contract comparison](docs/capi-contract-migration.md) and
[support matrix](docs/support-matrix.md) before selecting versions or upgrading.

## Find the right guide

| Task | Guide |
|---|---|
| Understand the product and a worker-scaling example | [Getting started](docs/getting-started.md) |
| Evaluate ownership, safety and privileges | [Architecture](docs/architecture.md), [security](SECURITY.md), [RBAC](docs/rbac-requirements.md) |
| Install the controller and accept a first workload | [Installation](docs/installation.md), [rollout validation](docs/live-rollout-validation.md) |
| Operate pause, HA, reboot, cleanup and SSH trust | [Operations](docs/operations.md), [SSH key lifecycle](docs/ssh-key-lifecycle.md) |
| Diagnose a failure | [Troubleshooting and FAQ](docs/faq.md) |
| Contribute or validate a change | [Development](DEVELOPMENT.md), [testing](docs/testing.md), [contributing](CONTRIBUTING.md) |
| Prepare a release | [Release process](docs/release-process.md), [container delivery](CONTAINER_IMAGES.md) |

The [documentation index](docs/README.md) lists the full reference and roadmap.

## Resources

All provider resources are namespaced and use
`infrastructure.alpininsight.ai/v1beta1`. This is a Kubernetes API group and schema
version; it does not require a public DNS endpoint or CDN. The
[structural CRDs](shared/crds/) define accepted fields.

| Kind | Responsibility |
|---|---|
| `SSHHost` | Prepared-host inventory, reachability and UID-bound claim/cleanup state |
| `SSHCluster` / `SSHClusterTemplate` | Cluster infrastructure endpoint and its template |
| `SSHMachine` / `SSHMachineTemplate` | Machine infrastructure lifecycle and its template |

## Local validation and contribution

From `python/`, use the checked-in dependency lock:

```bash
uv sync --frozen --dev
uv run pytest -q -m 'not integration and not e2e and not kind'
```

Tests include real loopback SSH/TLS endpoints. The separate
[Kind lifecycle lane](docs/testing.md) uses disposable hosts and an explicit
test kubeconfig. Unit success alone does not certify a release or live rollout.

[Apache License 2.0](LICENSE), attribution in [NOTICE](NOTICE). Contributions use
[Conventional Commits](https://www.conventionalcommits.org/) and the
[Developer Certificate of Origin](DCO); sign commits with `git commit -s`.
Create a working branch from current `develop` and submit a PR to `develop`.
