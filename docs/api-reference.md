# API and configuration reference

The [structural CRDs](../shared/crds/) are authoritative for accepted fields and
defaults. All provider resources are namespaced under
`infrastructure.alpininsight.ai/v1beta1`. The contract is legacy CAPI v1beta1;
see [support](support-matrix.md) for compatibility boundaries.

## Resource and ownership model

`SSHCluster` supplies `spec.controlPlaneEndpoint`. `SSHMachine` is the
infrastructure object of a CAPI Machine; templates supply the corresponding
specs to CAPI controllers. A template fragment alone is not a complete
ClusterClass or a runnable workload cluster.

| SSHMachine field | Meaning / default |
|---|---|
| `address`, `port`, `user` | Direct target; port 22, user root |
| `hostSelector.matchLabels` | Select an available host from namespaced SSHHost inventory |
| `hostRef` | Provider-persisted `namespace/name` of the selected host; not permission to adopt an unclaimed host |
| `sshKeyRef.name`, `.key` | Client-authentication Secret in the same namespace; key `value` |
| `sshHostKeyRef.name`, `.key` | Independently verified OpenSSH trust; key `known_hosts`; required for SSH at runtime |
| `dryRun` | Validate prerequisites and SSH without bootstrap/reboot; never cancels cleanup already owed |
| `paused` | Provider pause flag; standard CAPI owner-chain pause also applies |
| `bootstrapCheckStrategy` | `ssh` by default; `none` skips host-side readiness checks, not higher-level CAPI readiness |
| `remediation.reboot.requestedAt` | RFC3339 timestamp identifying a deliberate in-band reboot request |
| `providerID` | Provider-managed `ssh://<address>` identity; not an operator reassignment mechanism |
| `externalEtcd` | Explicit endpoints, certificate refs and optional file paths; see [external etcd](external-etcd.md) |

The chosen address/port/host identity is immutable after allocation. SSHHost
pool credentials can rotate without selecting another asset. Editing a Machine
address or providerID to reuse an existing allocation is rejected.

An illustrative inventory entry, after creating the referenced Secrets:

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHHost
metadata:
  name: worker-a
  namespace: example-cluster
  labels:
    role: worker
spec:
  address: 192.0.2.10
  port: 22
  user: root
  sshKeyRef:
    name: node-client-key
  sshHostKeyRef:
    name: node-verified-hosts
```

Replace the documentation address and namespace. Secret creation and full CAPI
ownership are installation prerequisites; applying this example alone does not
create a Kubernetes node.

## Observed state

| Field | Operator interpretation |
|---|---|
| `SSHHost.status.ready` / `lastProbeTime` | Last SSH reachability result and freshness; not proof of cleanliness |
| `SSHHost.spec.consumerRef.uid` | Claim owned by one SSHMachine UID |
| `SSHHost.status.phase` | Available, Claimed, Cleaning or Quarantined |
| `SSHMachine.status.allocation` | Persisted Machine/host UID and connection binding |
| `SSHMachine.status.bootstrapOwnership` | Persisted authorization for owned bootstrap/cleanup |
| `SSHMachine.status.ready` / `initialization.provisioned` | Infrastructure completion under the supported contract |
| `SSHMachine.status.cleanup.phase` | Running, Succeeded or Failed; only success permits release |
| `SSHMachine.status.remediation.reboot` | Prepared, Submitted, Unknown, Failed or Succeeded with request/boot evidence |

Statuses and ownership records are controller-owned. Do not patch them as a
routine recovery method; follow the identity and cleanup gates in [operations](operations.md).

## Runtime settings

| Setting | Default | Scope |
|---|---|---|
| `SSH_PROVIDER_HA` | `true` | Mandatory Kopf peering in the supported two-replica deployment |
| `POD_UID`, `POD_NAMESPACE` | Injected by Deployment | Peering identity and host-Lease namespace |
| `SSH_CONNECT_TIMEOUT` | 30 seconds | SSH connection establishment |
| `SSH_COMMAND_TIMEOUT` | 300 seconds | Command timeout / bootstrap receipt observation; not a kill deadline for detached bootstrap |
| `RECONCILE_INTERVAL` | 60 seconds | Periodic reconciliation fallback |
| `SSHMACHINE_RECONCILE_INTERVAL` | `RECONCILE_INTERVAL` | Machine-specific timer override |
| `SSHHOST_PROBE_INTERVAL` / `SSHHOST_PROBE_TIMEOUT` | 300 / 10 seconds | Periodic SSHHost reachability |
| `SSHMACHINE_DISTRIBUTED_LOCK_ENABLED` | `true` | Additional persisted Machine lock; keep enabled for HA |
| `SSHMACHINE_DISTRIBUTED_LOCK_TTL_SECONDS` | 120 seconds | Additional Machine lock expiry |
| `SSHMACHINE_DISTRIBUTED_LOCK_RETRY_DELAY_SECONDS` | 5 seconds | Lock-contention requeue |

Host Leases separately use a 60-second duration and 15-second renewal. Peering
uses 30-second lifetime. These defaults are not an end-to-end recovery SLO.
Readiness/resource settings are described in [operations](operations.md).
