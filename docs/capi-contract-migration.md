# CAPI contract comparison and migration plan

Reviewed: **2026-09-08**, against provider **v0.4.3** and its reviewed develop
source `542755537b67deeaa21a76f281111bf1b6cb83b0`. This is an implementation
assessment and work plan; it does not enable v1beta2 support.

The provider still advertises the legacy v1beta1 contract because its API access,
CRD contract labels and lifecycle test harness have not completed the migration.
P1 established lifecycle safety and HA on that integration. Adding the new
initialization field and upgrading CAPI components did not migrate the whole
provider. The newer contract is available from CAPI 1.11; our 1.12.11 test
baseline can therefore be used for the first migration lane. [S1], [S2], [S3]

## Version meanings

Provider release `v0.4.3`, CAPI component release `v1.12.11`, the CAPI contract
`v1beta1`/`v1beta2`, and resource API `infrastructure.alpininsight.ai/v1beta1`
identify different things. The core API used by our client is another compatibility
choice: a contract label alone does not remove calls to the retiring core API.
A provider can implement the v1beta2 contract while
keeping its own resource API named v1beta1, provided that its schema and behavior
satisfy that contract. The contract label maps between these versions. [S1], [S2]

For compatible, additive changes, the candidate mapping would be:

```yaml
metadata:
  labels:
    cluster.x-k8s.io/v1beta2: v1beta1
```

This is a planned example, not the active configuration. Publish the label only
with the implementation and successful acceptance evidence. A new provider API
version and conversion machinery become a separate decision if the selected
changes cannot preserve the existing API and persisted lifecycle state.

## Differences and our current state

**Implemented** refers only to the stated behavior. **Partial** means that an
existing implementation still has a specific migration or evidence gap.
**Open** means the required work is absent. Optional capabilities are identified
explicitly and do not all block the basic infrastructure contract.

| Area | Legacy v1beta1 | Current v1beta2 | Our current state |
|---|---|---|---|
| Contract discovery and provider API | CRD label `cluster.x-k8s.io/v1beta1` identifies the contract mapping | A v1beta2 contract label maps to a served provider API version; matching API version names are not required [S1], [S2] | **Open:** all five provider CRDs serve/store only v1beta1 and declare only the legacy label. Add the verified mapping for the CAPI-facing Cluster/Machine resources and templates; `SSHHost` remains provider inventory. [CRDs](../shared/crds/) |
| Core API access and namespace audit — retirement readiness | Clients can read CAPI objects through `cluster.x-k8s.io/v1beta1` | A v1beta2 client path removes the dependency on the retiring core API; this is separate from the provider contract label [S3], [S6] | **Partial:** owner-chain pause reads use the referenced owner version, but the label-only fallback, Machine bootstrap reader and auditor still hardcode v1beta1. Provider API reads are a separate choice. [Pause/identity](../python/capi_provider_ssh/contracts.py), [bootstrap reader](../python/capi_provider_ssh/controllers/sshmachine.py), [audit](../python/capi_provider_ssh/namespace_audit.py) |
| CAPI object references | Core spec references carry an `apiVersion` | Contract-versioned core spec references use `apiGroup`, `kind`, `name`; CRD labels resolve the version. Kubernetes `ownerReferences` still carry `apiVersion`. `Machine.spec.bootstrap.dataSecretName` remains available [S4], [S5] | **Open:** the Kind harness creates all CAPI groups as v1beta1 and builds legacy reference payloads. Convert the actual schemas, including KCP/worker templates; a text replacement of version strings is insufficient. [Harness](../python/tests/kind/runtime.py) |
| Infrastructure initialization | CAPI uses `status.ready` | CAPI uses `status.initialization.provisioned` [S1], [S2] | **Partial:** both `SSHCluster` and `SSHMachine` already write the new field alongside `ready`. Existing end-to-end tests use the legacy integration; they do not prove that CAPI progresses through the new contract fields. [Cluster](../python/capi_provider_ssh/controllers/sshcluster.py), [Machine](../python/capi_provider_ssh/controllers/sshmachine.py) |
| Conditions and lifecycle readiness | Legacy CAPI condition conventions | Conditions are recommended; compatible fields are accepted. A `Ready` condition covers the full lifecycle, including deletion [S1], [S2], [S3] | **Partial:** both controllers emit readable `Ready` conditions. They omit `observedGeneration`; their condition builders issue a new transition timestamp whenever they emit conditions. Machine cleanup changes only the legacy `ready` flag, leaving its existing `Ready` condition untouched. Generation tracking and stable timestamps are quality improvements, not missing mandatory fields in the core read contract. [Cleanup](../python/capi_provider_ssh/lifecycle.py) |
| Failure reporting and remediation | `failureReason` / `failureMessage` historically signalled terminal failures | Conditions and documented consumer policy replace special terminal-failure handling. Current CAPI no longer uses those legacy fields to trigger MachineHealthCheck remediation [S1], [S3] | **Partial:** Machine errors already produce conditions plus legacy diagnostics. Cleanup failure/quarantine lacks matching lifecycle conditions; an automatic CAPI remediation outcome is not established. Retain explicit ownership and quarantine safeguards when defining the policy. [Machine](../python/capi_provider_ssh/controllers/sshmachine.py), [cleanup](../python/capi_provider_ssh/lifecycle.py) |
| Endpoint, provider ID and addresses | `spec.controlPlaneEndpoint`, `spec.providerID`, `status.addresses` | These integration points remain, with their initialization semantics [S1], [S2] | **Implemented on the existing lane:** user-supplied endpoint, provider-ID wiring and addresses exist. Revalidate their propagation through v1beta2; this migration does not require a new load-balancer implementation. [Cluster schema](../shared/crds/sshcluster.yaml), [Machine schema](../shared/crds/sshmachine.yaml) |
| Failure-domain placement — optional | Cluster domains use a map; legacy InfraMachine `spec.failureDomain` can report placement | Cluster domains use a named list; actual Machine placement is reported in `status.failureDomain` and follows the owning Machine's request [S1], [S2] | **Not implemented:** neither provider status schema exposes failure domains. There is no existing domain map to migrate. Keep this capability unsupported unless placement is deliberately added and tested; controller replica anti-affinity is a different concern. |
| Pause and lifecycle safety | Pause, identity and lifecycle coordination already apply | Pause remains recommended; a `Paused` condition is recommended when pause is implemented [S1], [S2] | **Implemented behavior / partial reporting:** owner-chain pause and UID checks exist, but no `Paused` condition is emitted. Two-replica peering, host Leases, remote fencing and durable receipts are existing safety mechanisms to preserve and retest, not new v1beta2 features. [Contracts](../python/capi_provider_ssh/contracts.py), [operations](../python/capi_provider_ssh/operations.py) |
| Templates and topology | InfraMachine templates support cloning; ClusterClass adds further requirements | Template support remains; topology-specific SSA dry-run compatibility is conditional on ClusterClass support [S1], [S2] | **Partial:** both template CRDs exist. `SSHMachineTemplate.spec.template.metadata` is absent from its schema, unlike the Cluster template. Metadata propagation and v1beta2 cloning need coverage; a complete ClusterClass/SSA lane is not established. [Machine template](../shared/crds/sshmachinetemplate.yaml), [Cluster template](../shared/crds/sshclustertemplate.yaml) |
| clusterctl packaging — separate capability | Installation metadata declares supported contract series | If packaging is provided, metadata and CRD contract labels must agree [S1], [S2], [S6] | **Open, separate delivery work:** no complete versioned metadata/components bundle is shipped. Basic v1beta2 contract work must not be presented as automatic `clusterctl init`/upgrade support. [Installation](installation.md) |
| Test and component baseline | Existing harness exercises legacy CAPI APIs and references | Acceptance must prove the advertised contract and migration path, including independence from retiring APIs | **Implemented legacy baseline / open v1beta2 evidence:** CAPI/CABPK/KCP 1.12.11, Kubernetes 1.34.11, four Ready nodes, bootstrap/deletion/reuse/failover; the isolated suite has 319 tests. No explicit v1beta2 lane exists. CAPI 1.12 is a maintenance/transition baseline; 1.14.1 was the latest stable release checked on this review date. [Harness pins](../python/tests/kind/upstream.json), [tests](testing.md), [S6], [S7] |

The condition findings are concrete gaps in status reporting. The presence of a
compatible condition structure alone does not prove correct transitions, and
the absence of optional failure-domain support does not imply contract failure.
Do not derive a readiness percentage by counting these differently scoped rows.

## Work sequence and acceptance

1. **Decide the supported API and upgrade path — provider maintainer.** Prefer
   preserving the provider's v1beta1 resource API when changes are compatible;
   record any reason for introducing a new served/storage version. Separate
   mandatory contract work from optional topology, domains and packaging.
   Acceptance: an explicit mapping, old-client compatibility policy and data
   preservation plan for allocations, bootstrap ownership, receipts, cleanup,
   UIDs, claims and finalizers. Start contract testing on the known CAPI 1.12.11
   baseline; plan validation of a supported release line such as 1.14.1 separately.

2. **Migrate core API access and reference payloads — provider/CI maintainers.**
   Separate the selected CAPI API version from the provider's `API_VERSION`.
   Update bootstrap reads, owner/Cluster resolution, the namespace auditor and
   Kind create/get/patch/delete helpers. Convert core/CABPK/KCP payloads against
   their real schemas; keep Kubernetes owner-reference identity checks intact.
   Acceptance: missing owners, changed UIDs and API denials still prevent remote
   work; the auditor remains read-only; v1beta2 requests work without relying on
   a served core v1beta1 endpoint. Provider readiness must continue to address
   the selected provider API, not be changed by a global string replacement.

3. **Complete status behavior — provider maintainer.** Introduce consistent
   condition updates for initialization, normal reconciliation, pause, deletion,
   failed cleanup and quarantine. Preserve unrelated conditions, report observed
   generations and retain transition time when condition status is unchanged.
   Define error reasons and the actual remediation policy while retaining
   transitional legacy diagnostics only where needed for existing consumers.
   Acceptance: current `Ready`/`Paused` reporting matches the operation, cleanup
   failure retains the claim/finalizer, and no diagnostic change permits replay
   of an uncertain bootstrap or reboot. Verify actual CAPI/MachineHealthCheck
   behavior instead of assuming a legacy failure field triggers replacement.

4. **Prepare the matching CRDs and contract mapping — provider maintainer.** Add
   the selected status fields and template metadata support, and review schema
   pruning, validation and any change to SSA list semantics. Apply the candidate
   v1beta2 labels in the disposable test environment with the new controller.
   Acceptance: API-server round trips preserve user metadata and persisted
   ownership; rendering and actual CAPI template cloning succeed. If an
   incompatible provider API version is chosen, add and test conversion/storage
   migration before publishing that support claim. Test topology SSA separately
   if ClusterClass support is included.

5. **Extend the tests to prove the migration — CI maintainer.** Add targeted
   regression cases for the API adapter, conditions and failures above. Extend
   the real Kind lane to v1beta2 core objects and references, assert CAPI's
   initialization and mirrored conditions, and add a lane that rejects legacy
   core API use. Test upgrade from existing v1beta1 objects, including allocated,
   provisioned, paused and deleting resources, plus takeover during bootstrap.
   Acceptance: four Ready nodes, one bootstrap attempt across takeover, correct
   provider-ID/Node association, safe deletion and reuse, and preserved identity
   across migration. Re-run the existing trust, fencing, readiness-memory and
   negative-path checks. A separate approved external SSH target remains necessary
   for physical endpoint evidence; the present CI configuration does not supply it.

6. **Release and deliver the proven scope — release/platform owners.** Publish
   the successful provider/CRD contract as a reviewed release with matching
   multi-platform image provenance. Update the support matrix and upgrade guide,
   then deliver the immutable pin and ordered manifests through a separate
   consumer GitOps PR. Validate the chosen CAPI/CABPK/KCP upgrade together against
   the current upstream skew policy; it allows bounded minor skips, not only
   single-minor upgrades. Acceptance: the actual controller uses the intended
   API/contract, two replicas remain healthy, and a disposable workload canary
   proves lifecycle and cleanup. Complete clusterctl packaging independently if
   that installation interface is being offered. [S6], [release delivery](release-process.md)

Current upstream policy schedules the end of legacy API/contract support for
CAPI **1.16 / April 2027**; the contract pages still describe the date as
tentative. Recheck it at implementation and rollout. Historical migration notes
contain an older August 2026 estimate and must not override the current policy.
Do not combine API migration with unverified adoption of existing hosts or a
blind downgrade across changed ownership state. [S1], [S2], [S6]

## Sources and maintenance

The provider change owner updates each status row and its evidence when the
corresponding implementation is merged. Platform maintainers retain dated live
CRD/controller and workload observations in the access-controlled consumer
record; this document is not a live deployment dashboard.

[S1]: https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-machine "InfraMachine contract"
[S2]: https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-cluster "InfraCluster contract"
[S3]: https://release-1-11.cluster-api.sigs.k8s.io/developer/providers/migrations/v1.10-to-v1.11 "Introduction of the v1beta2 API and contract"
[S4]: https://github.com/kubernetes-sigs/cluster-api/blob/v1.12.11/api/core/v1beta2/common_types.go "ContractVersionedObjectReference"
[S5]: https://github.com/kubernetes-sigs/cluster-api/blob/v1.12.11/api/core/v1beta2/machine_types.go "Machine references and bootstrap data"
[S6]: https://cluster-api.sigs.k8s.io/reference/versions "Current API, contract and component version policy"
[S7]: https://github.com/kubernetes-sigs/cluster-api/releases/tag/v1.14.1 "Latest stable release checked on 2026-09-08"
