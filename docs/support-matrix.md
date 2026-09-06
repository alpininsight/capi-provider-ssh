# Support and validation matrix

Verified baseline: **2026-09-06**. A running Deployment, upstream compatibility,
provider contract compatibility and a successful workload lifecycle are separate evidence.

| Layer | Observed management-cloud | P1 target / scope | Evidence and limitation |
|---|---|---|---|
| Management Kubernetes | 1.34.10, 18 Ready nodes | Kubernetes 1.34 | Local Kind uses 1.34.11; patch versions are recorded separately |
| CAPI core / CABPK / KCP | 1.9.2, two replicas each | **1.12.11**, supported upgrade bridge | 1.9 is EOL and does not support management Kubernetes 1.34; local 1.9.2 → 1.12.11 rollout exercised |
| Further CAPI upgrade | Not deployed | 1.14.1 after the bridge | The maximum minor-version skip is three; never upgrade 1.9 directly to 1.14 |
| SSH provider | v0.4.2, one Ready pod on **k8s-cp-5** | P1 candidate, two replicas | Candidate source and local tests do not change the live image |
| CAPI provider contract | `infrastructure.alpininsight.ai/v1beta1` | Legacy **v1beta1** contract | `status.ready` and `spec.providerID`; `initialization.provisioned` is additional provider state, not a v1beta2 compliance claim |
| Current CAPI adoption | No Cluster, Machine, KCP, SSHCluster, SSHMachine or SSHHost objects | Future lifecycle use | Controllers are installed; the current VMs are not CAPI-managed |
| CAPI controller placement | Core and CABPK on workers 5/15; KCP on workers 11/5 | Two replicas across failure domains | Controllers need not run on control-plane nodes |
| SSH controller placement | Control-plane affinity; currently cp-5 | Two distinct control-plane nodes and physical-host spread | Node affinity selects a role, not a fixed node; at least two eligible nodes are required |
| Python / transport | Live image has older source/dependencies | Container target: Python 3.14; source minimum 3.13; Kopf and AsyncSSH from `uv.lock` | Unit/contract/real-SSH CI covers 3.13 and 3.14; Kind exercises the built 3.14 container. Later Python minors are not yet validated |
| kubeadm configuration | No current workload bootstrap | `v1beta3` and `v1beta4` rendering | v1beta3 uses argument maps; v1beta4 uses name/value lists; unknown versions fail closed |
| Linux targets | No current provider-owned hosts | Preinstalled OS, root SSH, `flock`, kubeadm/container runtime supplied by host preparation | A container-based test is not certification of every Linux distribution or hardware platform |
| External etcd | No current CAPI workload | Explicit kubeadm external configuration and certificate delivery | Configuration tests do not prove an external etcd cluster's availability; KCP/CABPK must also declare external etcd |
| SSH host identity | Old provider did not verify host keys | Required `sshHostKeyRef` with verified OpenSSH trust | Correct, changed, revoked and missing host keys are tested with real SSH handshakes |
| Hardware plugins | None installed or implemented | Lifecycle safety boundaries prepared | Redfish, IPMI, SNMP and GPIO remain design proposals; no loader, versioned plugin API or drivers are claimed |

The supported bridge is a delivery step, not a long-term version pin. CAPI 1.12
is in maintenance; plan the next supported upgrade and the provider's v1beta2
contract migration before legacy compatibility is removed (planned April 2027).
Do not downgrade CAPI or the provider across persisted ownership changes as an
automatic rollback. Pause and use the forward-recovery procedure in [operations](operations.md).

Sources checked for this change:
[CAPI version policy](https://main.cluster-api.sigs.k8s.io/reference/versions.html),
[CAPI 1.9 matrix](https://release-1-9.cluster-api.sigs.k8s.io/reference/versions),
[legacy infrastructure-machine contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-machine),
[kubeadm v1beta4](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/).

Live placement is a dated snapshot. Recheck it before any rollout:

```bash
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get pods -A -o wide | rg 'capi|kubeadm'
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get clusters,machines,kubeadmcontrolplanes -A
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get sshclusters,sshmachines,sshhosts -A
```
