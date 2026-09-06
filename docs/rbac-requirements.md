# RBAC permission reference

The authoritative manifests are [python/deploy/rbac.yaml](../python/deploy/rbac.yaml).
The table describes the shipped controller role; it does not promise that an
unreviewed reduced or expanded role will preserve the same behavior.

| API group | Resources | Granted verbs | Purpose |
|---|---|---|---|
| `infrastructure.alpininsight.ai` | sshclusters, sshclustertemplates, sshhosts, sshmachines, sshmachinetemplates | get, list, watch, create, update, patch, delete | Provider resource reconciliation |
| `infrastructure.alpininsight.ai` | sshclusters/status, sshhosts/status, sshmachines/status | get, update, patch | Status subresource writes |
| `infrastructure.alpininsight.ai` | sshclusters/finalizers, sshmachines/finalizers | update | Owned lifecycle finalizers |
| `cluster.x-k8s.io` | clusters, machines | get, list, watch | CAPI ownership, pause and bootstrap references |
| `apiextensions.k8s.io` | customresourcedefinitions | get, list, watch | Kopf discovery |
| `kopf.dev` | clusterkopfpeerings | get, list, watch, patch | Active/standby peering |
| `coordination.k8s.io` | leases | get, create, update | Provider host-operation Leases |
| Core | secrets | get, list, watch | Client keys, host trust, bootstrap and etcd material |
| Core | events | create, patch | Reconciliation events |

The role grants no ConfigMap permissions. Host Leases are provider-specific
operation locks, not Kopf's leader-election implementation. The role is read-only
for CAPI Clusters/Machines and Secrets. Separate aggregate roles extend upstream
CAPI/KCP managers with access to this provider's resources and status APIs.

## Management trust boundary

The controller role is cluster-wide, including Secret reads. Restrict writes to
provider resources, bootstrap data and credential Secrets to trusted operators.
Namespaced references do not make this deployment a boundary for hostile tenants.
Any future namespace-scoped operating mode requires separate implementation and
tests; do not imply isolation by editing a table alone.

## Auditor and registry identities

The optional consumer namespace-audit CronJob is delivered by the GitOps repo,
not this base deployment. Its own account reads namespaces and must not patch
namespace finalizers. Keep its test operation distinct from the controller's
SSHCluster API read. Registry/mirror admission is another policy layer and is
not granted by these Kubernetes RBAC rules.

## Diagnosing a denial

Record the denied API group/resource/verb and the intended identity without
dumping bearer tokens or Secrets. Compare actual RBAC with the source role, then
use a reviewed overlay change if a required contract is missing. Do not grant
wildcards or namespace mutation to make an unrelated canary pass. Verify both
positive and forbidden operations after a permission change.
