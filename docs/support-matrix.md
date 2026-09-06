# Support and validation matrix

Live snapshot: **2026-09-06, 17:48 UTC**. A running Deployment, upstream compatibility,
provider contract compatibility and a successful workload lifecycle are separate evidence.

| Layer | Observed management-cloud | P1 target / scope | Evidence and limitation |
|---|---|---|---|
| Management Kubernetes | 1.34.10, 18 Ready nodes | Kubernetes 1.34 | Local Kind uses 1.34.11; patch versions are recorded separately |
| CAPI core / CABPK / KCP | 1.12.11 images, two replicas each; KCP has repeated restarts | **1.12.11**, supported upgrade bridge | Core/CABPK are Ready. KCP cannot start its cache while the live KubeadmControlPlane CRD lacks v1beta2; Argo reports an annotation-size apply failure |
| Further CAPI upgrade | Not deployed | 1.14.1 after the bridge | The maximum minor-version skip is three; never upgrade 1.9 directly to 1.14 |
| SSH provider | P1 image, two Ready pods on **k8s-cp-1 and k8s-cp-6** | P1 lifecycle and HA, followed by reviewed dependency updates | Live digest is `sha256:264aab7ded30b0d7c5c511a418a440b8edefb00dcd47cf9aebdf07eeed430eb0`; newer dependency images need their own GitOps pin |
| CAPI provider contract | `infrastructure.alpininsight.ai/v1beta1` | Legacy **v1beta1** contract | `status.ready` and `spec.providerID`; `initialization.provisioned` is additional provider state, not a v1beta2 compliance claim |
| Current CAPI adoption | No Cluster, Machine, KCP, SSHCluster, SSHMachine or SSHHost objects | Future lifecycle use | Controllers are installed; the current VMs are not CAPI-managed |
| CAPI controller placement | Core, CABPK and KCP on workers 4/6 | Two replicas across failure domains | Controllers need not run on control-plane nodes; KCP readiness alone did not reveal its missing-CRD cache failure |
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
At this snapshot, the provider Application was Synced/Healthy, but the core
Application was OutOfSync with a failed sync: client-side apply exceeded the
262144-byte annotation limit for `kubeadmcontrolplanes.controlplane.cluster.x-k8s.io`.
Its live CRD still served only v1beta1; the 1.12.11 KCP process requested v1beta2
and exited after its cache-sync timeout. The earlier local upgrade used
server-side apply. GitOps must use a suitable apply strategy for this large CRD
before the CAPI upgrade can be considered operationally complete.

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
