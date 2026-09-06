# Release and delivery

The change owner coordinates source review and evidence. The platform owner
controls the consumer GitOps rollout. A security fix also follows
[SECURITY.md](../SECURITY.md). Neither a release nor a merge authorizes unrelated
infrastructure changes.

## Source acceptance

Work from current `develop` through a PR. Require completed checks on the current
head: Python 3.13/3.14, hooks, manifest validation, image/runtime validation and
the CAPI lifecycle lane. For changed behavior, update the support and operator
documentation before review. Inspect failed logs; do not replace failures with
skips or weaken a policy gate to obtain a green status.

The existing [release workflow](../.github/workflows/release.yml) uses GitVersion
6.8.x and creates a GitHub release from `main`; the [container workflow](../.github/workflows/container-build-python.yml)
publishes separately. Release metadata alone does not prove that a compatible
image or a `clusterctl` provider-components bundle exists. The current repository
does not ship a complete versioned `clusterctl` installation bundle.

## Evidence chain

| Gate | Evidence to retain | Acceptance |
|---|---|---|
| Reviewed source | PR head, merged commit and exact completed checks | No unresolved required failure or cancellation |
| Published image | OCI index, platform digests, source labels, scan and provenance/SBOM | Correct source for each advertised architecture |
| Consumer review | GitOps PR, CRD/RBAC ordering, immutable pin and resource/placement diff | Registry and platform prerequisites verified |
| Reconciliation | Observed GitOps revision and rendered objects | Desired manifests actually delivered |
| Controller runtime | Actual image IDs, both probes, peers, restart/OOM counters and scheduling | Stable active/standby operation |
| Workload canary | Bootstrap, Node association, deletion and host reuse | Required only when claiming workload lifecycle delivery |

For a mirror/relay, test the actual consumer identity and exact image pull path;
an existing local image cache does not prove registry authorization. Include a
negative identity check when changing admission. Preserve maintenance cordons and
other operators' work. A namespace-audit Job has different permissions from the
controller and must use its own operation contract.

## Upgrade and recovery

Choose component versions from [support](support-matrix.md). CAPI upgrades follow
the upstream version-skew policy and are staged separately from provider changes
when that makes evidence attributable. Do not combine an unsupported version jump
with lifecycle ownership migration.

Before a rollout, record current ownership/claims and agree the recovery boundary.
If validation fails, pause new lifecycle work through CAPI and preserve the
remote receipts, claims and finalizers. An accepted remote command can continue
after pause. A blind image downgrade can misinterpret persisted ownership state;
use the inspected state and a reviewed forward fix. Restore credentials or trust
only through the verified procedures in [operations](operations.md).

For management-plane disaster recovery, the platform must back up Kubernetes
state including CAPI/provider objects, relevant Secrets and their encryption
keys. There is no provider-owned backup service or guaranteed RPO/RTO. After a
restore, verify remote ownership/receipts against restored object UIDs before
allowing reconciliation; never infer identity from a reused object name.

## Post-merge review

Inspect replacement develop runs when changelog automation cancels earlier CI;
compare runtime inputs before reusing evidence. Record escaped defects, review
ambiguities and preventive actions in [merge reviews](merge-reviews.md).
Do not report delivery complete until the requested consumer gate passed.
Keep detailed deployment evidence in the access-controlled consumer record and
publish only appropriate aggregate product findings.
