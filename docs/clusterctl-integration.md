# clusterctl integration plan

Reviewed: **2026-10-19**. Tracking epic:
[#316](https://github.com/alpininsight/capi-provider-ssh/issues/316).
This is a delivery plan. The current release does not ship a complete
clusterctl installation bundle and the provider is not in clusterctl's built-in
catalogue. No install, upgrade or move support is added by this document.

## Independent deliverables

A provider-directory entry is a documentation change for discoverability.
Built-in clusterctl installation requires release artifacts and tested behavior.
Management-cluster move/pivot has a separate state/identity contract. Completing
one does not establish the others, and none implies certification by upstream.

The proposed built-in name is **`alpininsight-ssh`**, following the GitHub-org
prefix rule for new providers outside `kubernetes-sigs`. It is not yet registered
or reserved. The provider resource API remains
`infrastructure.alpininsight.ai/v1beta1`; installation naming does not require
DNS/CDN publication or a new Python client interface. #257 owns CAPI contract
migration, which is a different version decision.

## PR-sized packages and dependencies

| Package | Issue | Reviewable result | Acceptance before support |
|---|---|---|---|
| A: installation contract | [#311](https://github.com/alpininsight/capi-provider-ssh/issues/311) | Identity/label ADR, controller container `manager`, namespace/entrypoint behavior, CRD/RBAC/peering/Deployment/PDB delivery and an existing-consumer migration boundary | Rendered identity and namespace tests; preserved trust, readiness, security settings and HA; no competing ArgoCD/clusterctl owner |
| B: release assets | [#312](https://github.com/alpininsight/capi-provider-ssh/issues/312) | Reproducible `metadata.yaml`, `infrastructure-components.yaml` and a documented prepared-host `cluster-template.yaml` | Depends on A; downloaded release assets match reviewed source, actual stable image, checksums and contract mappings |
| C: release-asset acceptance | [#313](https://github.com/alpininsight/capi-provider-ssh/issues/313) | Disposable install/generate/lifecycle/upgrade/uninstall lane using the actual released assets | Depends on A/B; preserve bootstrap, cleanup, reuse, providerID association, trust and failover; missing prerequisites fail explicitly |
| D: move/pivot boundary | [#314](https://github.com/alpininsight/capi-provider-ssh/issues/314) | State reconstruction/identity design, object/Secret discovery and a tested support or unsupported decision | Independent design can start with A; use two disposable management clusters and interruption tests before claiming move support |
| E: ecosystem visibility | [#315](https://github.com/alpininsight/capi-provider-ssh/issues/315) | Directory-only upstream PR, intent issue for the proposed name, then built-in registration | Directory/intent preparation can proceed independently after accurate public docs; registration depends on B/C and an explicit move boundary |

Q4 2026 targets design, directory/intent preparation and incremental engineering.
It is not an unconditional deadline for full move support or built-in
registration. Each issue must link its exact accepted PR, release and test
evidence. Hardware plugins and fleet-scale guarantees stay outside this scope.

## Installation and release contract

The metadata must use `clusterctl.cluster.x-k8s.io/v1alpha3`, kind `Metadata`,
and release-series mappings that match the accepted CRD contract. Do not publish
v1beta2 labels or metadata until [#257](capi-contract-migration.md) is accepted.
The components bundle must contain the required provider resources, with one
default namespace and consistent provider labels. Workload templates are an
upstream recommendation; this plan includes one so evaluation has a usable,
documented path.

Current deployments use the `controller` container and `infrastructure-ssh`
provider identity. Review any migration of those names against consumer image
patches, RBAC/peering references, registry admission and tests. Do not apply a
global rename to active GitOps installations as an incidental packaging change.
The actual Kopf entrypoint must satisfy namespace handling without conflicting
all-namespace arguments.

The intended future command is `clusterctl init --infrastructure
alpininsight-ssh:<released-version>`. It is not a supported command for the
current release. First test installation with a custom provider configuration
and accepted release assets; built-in discovery needs the later upstream change.

## Move/pivot is a separate safety problem

Upstream never restores an object's status subresource during move. The current
provider persists allocation, bootstrap ownership and cleanup/reboot receipts
there, and checks Kubernetes UIDs in inventory claims and remote fencing.
Those checks protect existing workloads, but a fresh management API creates
different object identities. Do not assume the state can be reconstructed or
that generic discovery includes SSHHost inventory and custom Secret references.

#314 must inventory each state location and prove safe reconstruction/transfer,
or specify an explicit unsupported/blocking boundary. Acceptance includes unknown
remote outcomes, partial transfer and recovery without duplicate bootstrap,
unsafe reset, stale claim release or weakened host trust. A backup/restore
procedure is not provided by clusterctl move.

## Upstream submission

The provider belongs under **Infrastructure** in
`docs/book/src/reference/providers.md`. An accurate directory-only entry can be
prepared before install support. The separate registration process starts with
an upstream intent issue; the registration PR changes clusterctl and the book
after accepted stable artifacts exist. The repository can remain in the
`alpininsight` organization. These roadmap issues do not submit upstream changes.

Primary references:
[provider directory](https://cluster-api.sigs.k8s.io/reference/providers),
[clusterctl contract and registration](https://cluster-api.sigs.k8s.io/developer/providers/contracts/clusterctl),
[move and status semantics](https://cluster-api.sigs.k8s.io/clusterctl/commands/move).
