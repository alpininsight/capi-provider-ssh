# Troubleshooting and FAQ

Start with an explicit management kubeconfig, the selected namespace/resource
and the actual deployed image digest. Preserve ownership and Secrets while
diagnosing. Detailed host/account evidence belongs in the private operational
record; redact bootstrap output and upstream errors before sharing.

## A controller is Running but lifecycle work does not progress

Running is a process state. Check Ready/Available replicas, the image/probe
configuration, authenticated API access and each replica's current peering
heartbeat. One healthy standby is expected. A stale peer or API denial requires
diagnosis even when `/healthz` responds. See the [HA gate](operations.md#liveness-readiness-and-the-live-ha-gate).

Readiness proves API/coordination access, not every watch or resource handler.
Then inspect the affected Machine's owner chain, pause state, allocation,
bootstrap receipt and conditions. Do not restart repeatedly without identifying
the failed layer.

## Does deletion release a host even when cleanup fails?

**No.** The order is owned cleanup, persisted success, claim release and finalizer
completion. An unreachable host, failed reset or unverified ownership retains
the claim and finalizer; failed cleanup quarantines the host. Restore verified
access and retry normal deletion. Never remove finalizers or clear consumerRef
to manufacture success. A completed dry-run with no bootstrap ownership performs
no remote reset. See [allocation and cleanup](operations.md#allocation-and-cleanup).

## Can cleanup hooks or firewall flushes make a host reusable?

There is no supported generic cleanup-hook API. The implemented reset does not
promise to erase CNI state, application data, firewall rules or storage volumes.
Do not insert unconditional reset/iptables-flush commands as a shortcut around
UID ownership and cleanup. Use a separately reviewed host sanitization procedure
when changing a host's trust domain. Reprovision through the owning CAPI Machine,
not by deleting the infrastructure object first.

## Why is an SSHHost reachable but unavailable for allocation?

`status.ready` describes SSH reachability. A claimed, deleting, Cleaning or
Quarantined host is not a free allocation. Health or label changes do not move an
existing Machine to a spare host. Inspect consumer UID, host UID, phase and
cleanup state together; orphaned or ambiguous claims require explicit recovery.

## RBAC: Does the example RBAC include CRD permissions for Kopf?

Yes: CRD get/list/watch is included for discovery. Check the exact shipped
[RBAC table](rbac-requirements.md) before adjusting an overlay. The controller
also needs peering access and provider-owned host Leases. It does not require
namespace patch/finalizer privileges to make the read-only audit succeed.
Use the intended ServiceAccount's operation when designing a canary; an auditor
operation under the controller identity can correctly fail with 403.

## How is duplicate bootstrap prevented?

Machine locks, mandatory peering, renewed host Leases, remote flock and a
Machine-UID owner record work together. A detached bootstrap records a durable
result. Takeover observes that receipt instead of assuming a lost SSH response
means the command never ran. The additional Machine lock defaults to 120 seconds;
host Leases use 60 seconds. See [architecture](architecture.md#coordination-layers)
for each layer's limit.

## Why does a reboot remain Submitted or Unknown?

Submission is not completion. The provider requires a changed Linux boot ID.
An unobserved request is not automatically replayed, and cleanup waits while its
outcome is unresolved. Verify through an independent trusted console before
issuing a deliberate new request. See [reboot semantics](operations.md#reboot-semantics).

## Why did the probe print ready but the container restart?

Inspect the probe exit code, container termination reason, cgroup OOM counters,
memory use and concurrent diagnostic processes. The lightweight in-cluster probe
avoids loading the generated Kubernetes SDK. A 128/512 MiB request/limit provides
Burstable headroom, not a guarantee against node pressure or a memory leak.
Do not import the full SDK into each exec probe or treat stdout as the only result.

## GitOps is Synced but the Application is Degraded

Inspect the individual resource health and latest operation. A failed scheduled
audit can keep the Application degraded while controllers are healthy. A manually
created independent Job does not necessarily advance the CronJob's successful
schedule state. Preserve failed-job evidence and verify the next owned scheduled
run; do not patch status or delete evidence solely to turn the dashboard green.

For ImagePullBackOff, inspect registry admission, the actual container-runtime
mirror path and scheduling eligibility. A cached image or a healthy registry Pod
does not prove that the controller/auditor identity can fetch the selected digest.

## What if kubectl logs or exec fails?

Confirm the Pod still exists, then inspect API-to-kubelet routing, authorization
and network conditions. These subresources need more than a reachable API root.
Use the management platform's approved HA endpoint and operational access path;
do not bypass it with an arbitrary control-plane backend or changed SSH host key.

## Can this repository's release or roadmap be treated as production certification?

No. Use immutable image/source evidence and the [support matrix](support-matrix.md).
The current plugin proposals are not implementations. Workload HA, external etcd,
hardware/distribution validation and the consumer rollout require their own proof.
See [release and delivery](release-process.md).
