# P1 validation and review record

Baseline: 2026-09-06. This records candidate implementation evidence; it does not
assert that management-cloud has received the candidate image or CAPI upgrade.
The [support matrix](support-matrix.md) separates those states.

| Finding | Change | Regression evidence |
|---|---|---|
| Host moved after provisioning | Immutable allocation and UID-bound inventory claim | Stateful API contract tests, real CRD persistence/CAS tests |
| Cleanup released dirty hosts | Reset and durable success before releasing claim; quarantine on failure | Failure/retry, replacement UID and partial-claim recovery tests; real worker and whole-cluster deletion |
| Dry-run deletion reset unowned hosts | Bootstrap ownership required for mutation | Zero-SSH deletion tests |
| Invalid kubeadm arguments and external etcd | Version-aware rendering, explicit external etcd and guarded certificate delivery | v1beta3/v1beta4, control-plane join and external-etcd configuration tests |
| CAPI pause ignored | Fresh owner-chain pause checks for bootstrap, reboot and cleanup | Stateful tests and live controller pause/unpause tests |
| Reboot bypassed locks and reported early completion | Shared leases/UID guard; boot ID observation and Unknown outcome | Concurrent/lost-lease, failed/ambiguous submission and deletion guard tests |
| SSH identity unchecked | Required verified host trust; private staged payloads | Real AsyncSSH endpoint tests: valid, changed, missing and revoked keys; SFTP permissions |
| Test cleanup stripped finalizers | Read-only namespace audit; ordered test teardown | Audit boundary/RBAC tests and normal CAPI deletion without finalizer overrides |
| Unsupported CAPI/Kubernetes combination | Vendored CAPI 1.12.11 bridge, preserving HA overlays | Local 1.9.2 to 1.12.11 upgrade, real Kubernetes 1.34.11 lifecycle |
| SSH controller singleton | Two replicas, peering, remote fencing and durable bootstrap receipt | Abrupt active-Pod deletion during worker join: one bootstrap attempt, four Ready Nodes after takeover |

## Reproduce

Run `bash scripts/test-kind-lifecycle.sh` from the repository root with Docker,
Kind 0.33.0, kubectl 1.34.11 and uv available. It creates a uniquely named local
Kind management cluster and four disposable SSH/kubeadm hosts, installs pinned
upstream assets with SHA256 verification and runs both explicit integration and
lifecycle lanes. Allow approximately 8 GB RAM and 30 minutes. A failed local run
retains its explicit kubeconfig and cluster for diagnosis. No default kubeconfig,
external SSH target or production namespace is used.

The workflow `CI Python / CAPI lifecycle and provider failover` runs this path on
every PR. Missing prerequisites fail the explicit lane. Unit-only success does
not substitute for it. The optional external SSH lane separately requires
`E2E_SSH_PRIVATE_KEY` and independently verified `E2E_SSH_KNOWN_HOSTS` CI secrets.

Local evidence before PR: 182 unit/contract/real-SSH tests passed. The final
automated run passed eight real API integration tests and the complete four-node
lifecycle in 522.73 s. It covered init, two control-plane joins, a worker join,
worker deletion/reuse and an abrupt provider crash. One remote bootstrap attempt
completed and reconciliation recovered in 121.1 s (earlier independent trial:
122.7 s). These observations are not a recovery-time SLO. Whole-cluster cleanup
then completed through CAPI without removing finalizers manually. The k8s repository's
full suite passed 344 suites, with seven explicitly skipped environment lanes.
The final candidate's CI artifacts remain the authoritative commit-specific record.

## Lessons to carry into subsequent reviews

| Observed gap | Required improvement |
|---|---|
| Mocks accepted writes Kubernetes would prune or ignore | Include real structural CRDs, `/status` writes, defaults and stale resourceVersion conflicts in required CI |
| Replica count suggested HA while standalone mode disabled coordination | Test runtime peering and deliberately kill the active reconciler during a host operation |
| SSH connection loss killed or replayed remote bootstrap | Separate submission, durable remote execution and observation; assert exact attempt count after takeover |
| Two replicas plus required anti-affinity blocked rolling upgrades | Exercise a rolling update with only two eligible nodes; keep maxSurge 0 / maxUnavailable 1 |
| Inventory claim could survive a crash before Machine allocation persisted | Recover only the same Machine UID claim; test deletion at that exact persistence boundary |
| Test cleanup could hide provider failures | Never strip finalizers in fixtures; preserve keys/ownership until normal cleanup succeeds |
| Upstream aggregated RBAC conflicted under server-side apply | Omit controller-owned aggregated `rules`; validate the actual upgrade path without force-conflicts |
| Version config parsed only after merge, using differing GitVersion majors | Use GitVersion 6.8.x for PR version validation, image publication and release |
| Installed controllers were described as a managed fleet | Check actual CAPI objects and providerIDs; date the live inventory and keep it separate from source/CI evidence |

This is a pre-merge review record. After each PR merges, append its exact commit,
CI/image/GitOps evidence and any post-merge surprises before closing delivery.
