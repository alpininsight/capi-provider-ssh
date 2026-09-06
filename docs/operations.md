# Lifecycle safety and HA

The provider reconciles pre-provisioned Linux hosts. An outage of the provider
stops provisioning, cleanup and remediation; it does not stop already running
workloads. HA is useful for lifecycle availability. Management API/etcd HA and
workload control-plane HA are independent requirements.

## Controller HA

The deployment has two replicas, a PodDisruptionBudget with `minAvailable: 1`,
and required anti-affinity by hostname. The management-cloud overlay additionally
requires the control-plane role and spreads pods across `ais/proxmox-host`.
Two eligible nodes are required. Rolling updates use `maxUnavailable: 1` and
`maxSurge: 0`, so two eligible nodes suffice for upgrades as well as steady state.

Kopf uses a mandatory `ClusterKopfPeering/capi-provider-ssh` with distinct
priorities derived from Pod UIDs. A standby remains healthy while reconciliation
is paused. Install the peering CRD, wait for `Established`, create the peering
object, then start the Deployment. Argo sync waves encode this order.
Do not add `--standalone` when running multiple replicas.

Peering alone is not a distributed operation lock. Every mutating host operation
also holds a renewed Kubernetes Lease in the provider namespace and a remote
`flock` at `/var/lib/capi-provider-ssh-operation.lock`. The remote owner file
`/var/lib/capi-provider-ssh/owner` must match the SSHMachine UID. This protects
against an old remote command surviving an SSH disconnect or controller failure.
Bootstrap runs as a detached, UID-fenced job with private `bootstrap-started`,
`bootstrap-exit-code` and `bootstrap-output` records on the host. A new controller
observes that result instead of replaying the payload. Failed receipts quarantine
the allocation; a started job without a result after acquiring the remote lock
requires cleanup/replacement. SSH_COMMAND_TIMEOUT bounds observation, not remote
job lifetime. Scripts have unique attempt paths and are private; certificate installation runs
inside the guarded script. A takeover cannot truncate a running bootstrap file.

Peering lifetime is 30 seconds; host Leases expire after 60 seconds and renew
every 15 seconds. The additional Machine lock can delay takeover up to 120 seconds.
These are coordination bounds, not an end-to-end recovery SLO: scheduling, API
availability and an already running remote command may extend recovery.

Source: [Kopf peering](https://docs.kopf.dev/en/stable/peering/).

## Liveness, readiness and the live HA gate

`/healthz` checks the local Kopf event loop. Its `runtime` probe reports whether
configuration completed, the current process's startup time and its peering
priority. It performs no Kubernetes requests: a temporary API outage must not
turn into liveness-driven restart loops.

The separate Kubernetes exec readiness probe runs
`python -B -m capi_provider_ssh.readiness`. It requires local startup to have
completed, an authenticated and TLS-verified SSHCluster list request, and a fresh
heartbeat with this replica's priority in `ClusterKopfPeering`. That heartbeat
must be newer than the current process's startup and younger than 30 seconds.
A surviving peer from a previous container process cannot satisfy readiness.
The standby passes the same checks as the active reconciler; priority does not
make the standby unready. Explicit non-HA mode still requires CRD API access.

API calls disable automatic retries and use one-second connect/two-second read
timeouts. The probe has a ten-second execution budget and fails readiness after
two consecutive failures. Readiness does not guarantee that every resource
handler or watch is progressing; the lifecycle/failover tests and observed
reconciliation remain separate acceptance evidence.

The controller requests **128 MiB** and permits bursts up to **512 MiB**. This
is Kubernetes **Burstable** QoS: the scheduler accounts for the request; the
container uses additional available RAM only as needed, up to the fixed limit.
Automatically resizing the request/limit is a separate Vertical Pod Autoscaler
deployment, not a property of a higher limit.

The in-cluster exec path uses a small standard-library HTTPS client. It reads the
projected CA/token on each call, validates the server certificate and hostname,
does not follow redirects or proxies, and caps responses at 1 MiB. Explicit local
kubeconfigs retain the normal SDK/auth-plugin path. Do not reintroduce the full
generated SDK into the pod probe: an overlapping probe and diagnostic can share
the operator's cgroup and trigger an OOM kill. The Kind lane checks concurrent
probes, zero cgroup OOM kills and unchanged operator restart counts under the
declared resource budget.

Resource behavior: [Kubernetes requests and limits](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/),
[Burstable QoS](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/#burstable),
[Vertical Pod Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/vertical-pod-autoscale/).

Check every replica, rather than one reachable health endpoint:

```bash
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n capi-provider-ssh-system \
  exec "$PROVIDER_POD" -- python -B -m capi_provider_ssh.readiness
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get clusterkopfpeerings.kopf.dev capi-provider-ssh
```

The probe command requires an image containing this module and a matching
Deployment update. Updating an image tag or this repository alone does not update
the management-cloud GitOps pin. For older images, inspect API reachability and
peering directly; their `/healthz` endpoint does not establish readiness.

If only one replica can reach the API, inspect that node's Cilium agent API
connection and endpoint identity. A Ready Pod with Cilium's `reserved:init`
identity can still have no permitted egress. Restore the reviewed host networking
baseline through the infrastructure owner before accepting live HA. Keep
operator access on the management API's HA endpoint.

Sources: [Kopf probing](https://docs.kopf.dev/en/stable/probing/),
[Cilium troubleshooting](https://docs.cilium.io/en/stable/operations/troubleshooting/).

## Allocation and cleanup

`status.allocation` binds Machine UID, target address/port and, for pool mode,
SSHHost UID. `spec.consumerRef.uid` is the inventory claim. Health or label changes
never move an existing Machine to another host. Changing an allocated target
requires replacement, not editing its address or providerID.

The controller persists `status.bootstrapOwnership` before the first possible
bootstrap side effect. Host phases are `Available`, `Claimed`, `Cleaning` and
`Quarantined`. `SSHHost.status.ready` only describes SSH reachability; it does not
prove cleanliness. Status is written through the Kubernetes `/status` subresource.

Delete ordering is: keep claim → mark Cleaning → verify trust and ownership →
run guarded `kubeadm reset` and remove Kubernetes/bootstrap files → persist cleanup
Succeeded → release claim → allow the finalizer to disappear. Failures retain
the claim and finalizer and quarantine the host. Retries can complete cleanup;
pool selection never reclaims an orphan automatically.

The reset does not reimage a disk or promise removal of application data, CNI
configuration, firewall rules or storage volumes. Use a separate, verified host
sanitization procedure before transferring a host outside this inventory.

A Machine which only completed dry-run has no bootstrap ownership and performs
no remote reset on deletion. Setting dry-run after real or partial bootstrap
does not erase the cleanup obligation.

## Pause and emergency stop

The provider honors `Cluster.spec.paused` and `cluster.x-k8s.io/paused` on the
Cluster, owning Machine and infrastructure object, as well as its existing
`spec.paused`. Bootstrap, reboot and deletion all consult the owner chain.
Timers observe owner unpause even without an SSHMachine/SSHCluster spec change.

```bash
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n "$NAMESPACE" patch cluster "$CLUSTER" \
  --type=merge -p '{"spec":{"paused":true}}'
```

Record the pause in GitOps desired state as well so a subsequent Argo sync does
not remove it. Pausing Argo synchronization only stops manifest delivery; it
does not pause already installed CAPI controllers. Flux is retired in management-cloud.

Pause prevents the next remote operation. It cannot retract a command which the
host has already accepted. Inspect ownership, operation status and the remote
process before recovery; an interrupted SSH connection is not proof that the
remote process stopped. Do not remove finalizers to manufacture successful cleanup.

## Reboot semantics

A new `spec.remediation.reboot.requestedAt` identifies a request. The provider
records the previous Linux boot ID before submission. `Prepared` and `Submitted`
are not completion; only observing a different boot ID sets `Succeeded` and
`lastCompletedAt`. A lost response becomes `Unknown`, and the same request is
never resent automatically. Cleanup waits for an unresolved reboot.

If the host did not reboot and the outcome remains Unknown, establish through a
trusted console that no delayed reboot is pending. A deliberate new request can
then be issued, or the failed request can be marked resolved during an audited
recovery. Never reset/reassign a host while a reboot may still execute.

## SSH trust and existing installations

`sshHostKeyRef` is required at runtime on direct SSHMachines or selected SSHHosts:

```yaml
sshKeyRef:
  name: node-client-key
sshHostKeyRef:
  name: node-verified-hosts
  key: known_hosts
```

The trust Secret contains independently verified OpenSSH `known_hosts` contents.
Use `[address]:port` for nonstandard ports. Provision host keys or host CA trust
through a console, hardware inventory or another authenticated provisioning
channel. `ssh-keyscan` alone does not verify identity. Changed, missing and revoked
host keys fail closed before authentication. Rotate trust only after independent
identity verification; overlap verified old/new keys during an intentional rotation.

Existing unowned Machines/claims are not automatically adopted. Before upgrading,
inventory all Machines/hosts and their owner UIDs, pause lifecycle work, verify
SSH trust and match each remote host to its intended Machine. For an existing
provisioned Machine, migration must establish both API allocation/ownership and
the matching remote owner record under a reviewed recovery procedure. Without
that proof cleanup/reassignment remains blocked. Management-cloud's inspected
baseline has no such objects, so there is no current fleet to adopt.

## Test namespace audit

The hourly job only reads namespaces matching both `test-capi-ssh-*` and
`capi-provider-ssh-test=true`, in Terminating for at least one hour. Findings
produce a failed Job with diagnostic metadata. Its RBAC cannot patch finalizers.
Integration teardown likewise waits for Machine deletion before infrastructure
cleanup and preserves SSH Secrets when cleanup fails.

## Future plugins

`contracts.py`, `inventory.py`, `operations.py` and `lifecycle.py` separate CAPI
ownership/pause, allocation, execution fencing and lifecycle state. A future
driver must use these contracts, report submission separately from completion,
and reconcile unknown outcomes after restart. Out-of-band power drivers also
need a common physical asset identity and protocol-specific fencing; an SSH
Lease by address alone is not a complete plugin API. No hardware plugin runtime
is delivered by this change.
