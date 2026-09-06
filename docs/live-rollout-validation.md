# Rollout validation and teardown

Use the [support matrix](support-matrix.md) and [lifecycle/HA runbook](operations.md)
as the acceptance contract. management-cloud uses **ArgoCD**. Its existing nodes
are not currently managed by CAPI; installing controllers does not adopt them.

## Delivery order

1. Record current Git commits, controller image digests, API/CRD versions,
   provider placements and all CAPI/SSH inventory. Verify management API/etcd
   availability through the configured HA endpoint.
2. On a disposable cluster, run the unit/SSH suite, real API integration tests,
   CAPI/CABPK/KCP init and joins, deletion/reuse and provider-failure tests.
   An explicitly selected test lane must fail on missing prerequisites.
3. Publish the reviewed provider image for both supported architectures and record
   its digest. A provider PR merge does not move the Kubernetes GitOps image pin.
4. Upgrade CAPI 1.9.2 to **1.12.11** first. Keep core, CABPK and KCP aligned. The
   vendored Kubernetes manifests record upstream asset hashes and preserve their
   existing HA/security overlays. Aggregated RBAC rules stay controller-owned.
5. Deliver provider CRDs, RBAC, peering CRD/instance, PDB and matching image through
   the Argo application. Wait for CRDs and both replicas. Check peering heartbeat
   progress and run an authenticated API operation; `/healthz` alone is insufficient.
6. Create or resume only the intended canary lifecycle objects. Verify Machine
   bootstrap data, allocation UID/port, remote trust, providerID-to-Node association,
   workload API availability and Node readiness.
7. Delete the canary through CAPI. Keep Secrets until cleanup completes. Verify
   finalizer removal, absence of stale remote ownership/bootstrap files, release
   of the original host claim and reuse by a different Machine UID.

The next CAPI upgrade to 1.14 is a separate stage after the bridge has passed.
Do not combine it into an unsupported 1.9 → 1.14 jump.

## Stop and recovery

Use CAPI pause, not GitOps synchronization suspension, to stop new lifecycle work.
An accepted remote command can continue after pause or connection loss. Inspect
it before recovery. Failed reset means Quarantined and retained finalizer/claim;
never force-remove them. Reverting an image across the new persisted ownership
contract or downgrading CAPI is not an automatic rollback procedure.

For an empty, controller-only management installation, rollback/forward recovery
has a different scope from an active CAPI workload. Repeat the inventory check
immediately before delivery; do not rely on the dated empty baseline.

## Evidence to attach to the change

| Gate | Required evidence |
|---|---|
| Source / CI | Provider and GitOps commit IDs; required checks and actual executed test lanes |
| Image | Multi-architecture immutable digest and source revision |
| GitOps | Argo target revision, synced image pin, CRD/peering ordering |
| Runtime | Two Ready pods on distinct eligible nodes, fresh peer heartbeats, accepted API writes |
| Lifecycle | Init, control-plane join, worker join, UID/providerID association, cleanup and host reuse |
| HA | Active-pod failure during bootstrap, surviving remote guard, successful takeover without replay |
| Recovery | Failed cleanup/quarantine, retained claim and Secrets, observed reboot completion |

A green CI run which skipped a lane is not evidence for that lane. Keep local,
CI and live-cluster results separate in the handover.
