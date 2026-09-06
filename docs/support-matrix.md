# Support and validation matrix

Live snapshot: **2026-09-06, 21:17 UTC**. A running Deployment, upstream compatibility,
provider contract compatibility and a successful workload lifecycle are separate evidence.

| Layer | Observed management-cloud | P1 target / scope | Evidence and limitation |
|---|---|---|---|
| Management Kubernetes | 1.34.10, 18 Ready nodes | Kubernetes 1.34 | Local Kind uses 1.34.11; patch versions are recorded separately |
| CAPI core / CABPK / KCP | 1.12.11 images, two replicas each; KCP stable since 18:11 UTC | **1.12.11**, supported upgrade bridge | The large-CRD apply failure was fixed through k8s #6556. Core GitOps is Synced/Healthy; the historical KCP restart counts remain at five per replica |
| Further CAPI upgrade | Not deployed | 1.14.1 after the bridge | The maximum minor-version skip is three; never upgrade 1.9 directly to 1.14 |
| SSH provider | P1 image on **k8s-cp-1 and k8s-cp-6**; both API paths recovered after host-route repair | P1 lifecycle and HA, followed by reviewed dependency updates | Live digest is `sha256:264aab7ded30b0d7c5c511a418a440b8edefb00dcd47cf9aebdf07eeed430eb0`; newer dependency/readiness images need their own GitOps pin |
| Provider readiness | Both replicas have fresh peers; the old local `/healthz` still cannot detect an API outage | Authenticated CRD access plus this process's fresh peer heartbeat; standby remains Ready | Unit tests cover startup, missing/stale/other-process peers, API denial and redacted diagnostics. Kind integration checks both replicas and a new operator with an unreachable API. Readiness is not proof of every watch or a workload lifecycle |
| CAPI provider contract | `infrastructure.alpininsight.ai/v1beta1` | Legacy **v1beta1** contract | `status.ready` and `spec.providerID`; `initialization.provisioned` is additional provider state, not a v1beta2 compliance claim |
| Current CAPI adoption | No Cluster, Machine, KCP, SSHCluster, SSHMachine or SSHHost objects | Future lifecycle use | Controllers are installed; the current VMs are not CAPI-managed |
| CAPI controller placement | Core, CABPK and KCP on workers 4/6 | Two replicas across failure domains | Controllers need not run on control-plane nodes; the earlier KCP cache failure is resolved |
| SSH controller placement | Control-plane affinity; currently cp-1/cp-6 | Two distinct control-plane nodes and physical-host spread | Node affinity selects a role, not a fixed node; at least two eligible nodes are required |
| Python / transport | P1 candidate from source `2f8d822`, before dependency updates | Container target: Python 3.14; source minimum 3.13; Kopf 1.44.6 and AsyncSSH 2.24.0 from `uv.lock` | Unit/contract/real-SSH CI covers 3.13 and 3.14; Kind exercises the built 3.14 container. Later Python minors are not yet validated |
| Kubernetes Python client | Older live dependencies | 36.0.3 from `uv.lock` | Upstream generation targets Kubernetes 1.36; the provider's shared Core, Coordination and CustomObjects APIs are tested against 1.34.11. This is not an exact match of every client/server API |
| kubeadm configuration | No current workload bootstrap | `v1beta3` and `v1beta4` rendering | v1beta3 uses argument maps; v1beta4 uses name/value lists; unknown versions fail closed |
| Linux targets | No current provider-owned hosts | Preinstalled OS, root SSH, `flock`, kubeadm/container runtime supplied by host preparation | A container-based test is not certification of every Linux distribution or hardware platform |
| External etcd | No current CAPI workload | Explicit kubeadm external configuration and certificate delivery | Configuration tests do not prove an external etcd cluster's availability; KCP/CABPK must also declare external etcd |
| SSH host identity | P1 host-trust enforcement deployed; no adopted SSH hosts | Required `sshHostKeyRef` with verified OpenSSH trust | Correct, changed, revoked and missing host keys are tested with real SSH handshakes |
| Hardware plugins | None installed or implemented | Lifecycle safety boundaries prepared | Redfish, IPMI, SNMP and GPIO remain design proposals; no loader, versioned plugin API or drivers are claimed |

The supported bridge is a delivery step, not a long-term version pin. CAPI 1.12
is in maintenance; plan the next supported upgrade and the provider's v1beta2
contract migration before legacy compatibility is removed (planned April 2027).
Do not downgrade CAPI or the provider across persisted ownership changes as an
automatic rollback. Pause and use the forward-recovery procedure in [operations](operations.md).

The live P1 delivery came from [k8s PR #6544](https://github.com/alpininsight/insight-lima-k8s-capi/pull/6544).
The annotation-size failure described in the earlier 17:48 snapshot was repaired
by [k8s PR #6556](https://github.com/alpininsight/insight-lima-k8s-capi/pull/6556):
CRDs now use server-side apply with Argo 3.2's client-side migration disabled.
The KCP CRD serves/stores v1beta2, its cache starts, and the core Application is
Synced/Healthy.

The independent provider HA investigation is tracked in
[k8s #6557](https://github.com/alpininsight/insight-lima-k8s-capi/issues/6557).
The cp-6 Cilium agent could not reach its configured API endpoint, leaving the
provider's network endpoint at `reserved:init` without allowed egress while its
local health server answered HTTP 200. The missing persistent/kernel host route
was restored using the existing foundation baseline, without an interface or
Cilium restart. By 21:17 both provider pods completed TLS-verified API requests,
both had fresh peers and normal Cilium endpoint identities, cp-6 had resumed
reconciliation and cp-1 had paused in its favour. Historical restart counts were
10/0. The Deployment had two available replicas. The Application still showed
Synced/Degraded and requires separate resource-health follow-up. The stronger
readiness contract and dependency updates still require a new image/GitOps pin;
this recovery is not proof of an adopted production workload lifecycle.

Sources checked for this change:
[CAPI version policy](https://main.cluster-api.sigs.k8s.io/reference/versions.html),
[CAPI 1.9 matrix](https://release-1-9.cluster-api.sigs.k8s.io/reference/versions),
[Kubernetes Python client matrix](https://github.com/kubernetes-client/python#compatibility),
[legacy infrastructure-machine contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-machine),
[kubeadm v1beta4](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/).

Live placement is a dated snapshot. Recheck it before any rollout:

```bash
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get pods -A -o wide | rg 'capi|kubeadm'
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get clusters,machines,kubeadmcontrolplanes -A
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get sshclusters,sshmachines,sshhosts -A
```
