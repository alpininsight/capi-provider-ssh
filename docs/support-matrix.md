# Support and validation matrix

Reviewed: **2026-09-08**. This is the product compatibility reference for the
checked-out source, not a live deployment dashboard. A published architecture,
passing contract test and certified physical workload are different claims.
No separate commercial SLA, LTS schedule or hardware certification is declared.

## Tested baseline

| Layer | Implemented / validated baseline | Boundary |
|---|---|---|
| Management Kubernetes | Disposable lifecycle CI: 1.34.11 | Other minors and every distribution are not established by this lane |
| CAPI core / CABPK / KCP | 1.12.11, aligned components; tested upgrade bridge from 1.9.2 | The next supported upgrade is a separate validation stage |
| Provider API | `infrastructure.alpininsight.ai/v1beta1`, namespaced structural CRDs | Legacy v1beta1 CAPI contract; no complete v1beta2 conformance claim |
| Python | Source minimum 3.13; unit matrix 3.13/3.14; container Python 3.14 | Later Python minors are not validated |
| Kopf / AsyncSSH | Locked 1.44.6 / 2.24.0 | Keep dependency changes with their actual image/lifecycle evidence |
| Kubernetes Python client | Locked 36.0.3; used Core, Coordination and CustomObjects APIs tested against 1.34.11 | The client is generated for Kubernetes 1.36; this is API overlap, not exact minor equivalence |
| OCI architectures | Published linux/amd64 and linux/arm64 | Required hosted Kind lifecycle runs on linux/amd64; publication is not arm64 hardware certification |
| kubeadm configuration | v1beta3 maps and v1beta4 name/value arguments | Unknown versions fail closed; not a general cloud-init implementation |
| Target hosts | Pre-provisioned Linux, verified SSH, root-capable operations, flock and a prepared kubeadm/runtime baseline | No OS installer, disk erasure guarantee or all-distribution certification |

The locked source is [python/uv.lock](../python/uv.lock). Current automated lanes
are in [CI Python](../.github/workflows/ci-python.yml),
[container validation/publication](../.github/workflows/container-build-python.yml)
and the [test portfolio](testing.md). Use the final run for the exact revision
under review; historical counts are not a substitute.

## Capability and evidence

| Capability | Status | Evidence / limitation |
|---|---|---|
| Host allocation and cleanup | Implemented | UID/resourceVersion claims, persisted binding, quarantine and successful cleanup before release; no automatic adoption |
| Bootstrap and failover | Implemented | Real CAPI init/joins, durable receipts, provider takeover and no duplicate bootstrap in the Kind lane |
| CAPI pause | Implemented | Owner-chain pause, missing/recreated owners and API denial prevent new remote work; accepted commands can continue |
| Reboot remediation | Implemented, in-band SSH | Completion requires changed boot ID; Unknown is not automatically replayed and blocks unresolved cleanup |
| Controller HA | Two replicas with mandatory peering, host Leases and remote fencing | Requires eligible placement and a healthy management API/network; no end-to-end recovery SLO |
| Readiness / liveness | Authenticated API and own current-process heartbeat / local HTTP health | Both active and standby are checked; not proof of every watch/handler |
| Controller memory | 128 MiB request / 512 MiB limit, Burstable | Lightweight probe and overlapping-probe/OOM tests; no VPA installation or automatic resizing |
| SSH trust | Required verified host keys/CA reference | Real valid/changed/missing/revoked-key transport tests; host authorization and key rotation remain operational responsibilities |
| External etcd | Configuration and private certificate delivery implemented | Rendering tests do not certify external-etcd availability; KCP/CABPK configuration must agree |
| Namespace audit | Read-only module; scheduled job is consumer-owned | Reports stuck test namespaces; no finalizer mutation or automatic cleanup service |
| Templates / ClusterClass | SSHClusterTemplate and SSHMachineTemplate CRDs | A fragment is not a complete ClusterClass topology or full conformance test |
| clusterctl packaging | Not complete | No shipped versioned metadata/components installation bundle |
| Hardware plugins | Design only | No loader, stable driver API, capability discovery or OOB drivers; see [plugin requirements](plugin-contract.md) |
| Fleet scale / recovery objectives | Not certified | Requires consumer-specific soak, capacity, failure-domain and recovery evidence |

## Version evolution

CAPI 1.12 is an upgrade bridge in upstream maintenance mode, not a permanent pin.
Follow the current upstream version policy, keep core/CABPK/KCP aligned and
validate each selected transition.
Do not jump directly from 1.9 to 1.14. Plan a versioned provider v1beta2 migration;
upstream removal of legacy v1beta1 compatibility is **tentatively April 2027**.
An extra `initialization.provisioned` status field alone does not complete that
migration. Never downgrade blindly across persisted ownership-state changes.

The [contract comparison and migration plan](capi-contract-migration.md) records
the current implementation, mandatory and optional differences, and acceptance
steps. The provider may retain its own v1beta1 resource API while implementing
the v1beta2 CAPI contract; a CRD API rename is not automatically required.

## Consumer deployment records

The consumer repository owns actual image pins, platform placement and dated
rollout evidence. For management-cloud, see the private
[provider VERSION and manifests](https://github.com/alpininsight/insight-lima-k8s-capi/tree/develop/infrastructure/capi/providers/ssh)
and [readiness/resource rollout PR](https://github.com/alpininsight/insight-lima-k8s-capi/pull/6571).
Installed CAPI controllers do not imply that the existing VMs are CAPI-managed.
Recheck Clusters, Machines and provider inventory before every change.

Do not copy private host inventories, account identifiers or raw diagnostic
bundles into this public compatibility reference. The
[delivery evidence chain](release-process.md) distinguishes source acceptance,
registry admission, actual Pod image/probe state and a workload canary.

Sources: [CAPI version policy](https://main.cluster-api.sigs.k8s.io/reference/versions.html),
[Kubernetes Python client compatibility](https://github.com/kubernetes-client/python#compatibility),
[legacy infrastructure-Machine compatibility](https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-machine),
[kubeadm v1beta4](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/).
