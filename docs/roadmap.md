# Roadmap and maturity

This is a planning document. Quarter targets prioritize implementation; releases
and support claims require completed acceptance. The [support matrix](support-matrix.md) records
the current implementation; [plugin requirements](plugin-contract.md) define the
extension work still required.

## Implemented foundation

The Python provider has persistent UID-bound allocation, verified SSH trust,
CAPI pause/identity checks, fenced bootstrap receipts, cleanup quarantine, reboot
observation and coordinated two-replica operation. Internal module boundaries
separate these concerns. They are not a stable third-party driver SDK.

## Q4 2026 — CAPI contract migration

Planning window: **2026-10-01 through 2026-12-31**, tracked in the
[Q4 2026 milestone](https://github.com/alpininsight/capi-provider-ssh/milestone/1).

| Work | Current state | Tracking and ownership | Completion gate |
|---|---|---|---|
| Implement the CAPI v1beta2 infrastructure contract and retire core v1beta1 API dependencies | Planned; initialization and lifecycle HA already exist, but API access, status transitions, schemas/references and acceptance coverage have gaps | [Issue #257](https://github.com/alpininsight/capi-provider-ssh/issues/257); provider/CI maintainers, release/platform owners for delivery | Complete the six [migration steps](capi-contract-migration.md#work-sequence-and-acceptance), preserve existing ownership, pass the new-contract and upgrade lanes, and record accepted release/consumer evidence |

The issue contains the comparison, current implementation and upstream references.
Failure domains, full ClusterClass support, clusterctl packaging and hardware
plugins remain separate capability decisions. An API rename is not automatically
required. Recheck upstream retirement dates and supported component versions when
implementation starts.

## Readiness priorities

The [documentation and OSS readiness assessment](documentation-readiness.md)
records existing coverage, concrete gaps and acceptance owners. Before broader
external adoption, the current source completes lifecycle condition reporting,
release-derived package/license metadata and the maintenance policy. Private
reporting is enabled. A temporary single-maintainer review exception applies;
restore independent approval when a second eligible maintainer is onboarded,
with no September 2026 availability assumed. Approved external SSH evidence
remains necessary. Published and deployed versions
still need their own release/rollout acceptance.

Improve the evaluation walkthrough, release-specific guidance and documentation
checks alongside those changes. Existing packaging, operating-envelope and
plugin decision gates remain below; they are not all assigned to the Q4 milestone.

## Next decision gates

| Area | Work before claiming support | Acceptance owner |
|---|---|---|
| CAPI contract evolution | Q4 2026 [issue #257](https://github.com/alpininsight/capi-provider-ssh/issues/257): [current gaps and ordered migration](capi-contract-migration.md), API/upgrade decision and upstream compatibility tests | Provider maintainer |
| Provider packaging | Versioned clusterctl metadata/components and install/upgrade tests | Release maintainer |
| Hardware extensions | Shared asset identity, capability/version negotiation, authorization and cross-protocol fencing | Provider / platform maintainers |
| First OOB driver | Protocol emulator tests, lost-response/crash tests and an explicitly selected physical canary | Driver maintainer |
| Production operating envelope | Fleet-scale/soak measurements, resource sizing, recovery objectives and supported OS baselines | Platform owner |
| Security operations | Intake enabled and [maintenance/backport policy](maintenance-policy.md) implemented; exercise triage | Repository maintainers |
| Review continuity | [#261](https://github.com/alpininsight/capi-provider-ssh/issues/261): end the temporary single-maintainer exception and restore the standard review profile when a second eligible maintainer is onboarded; no September 2026 or fixed Q4 delivery commitment | Repository owner |
| Distribution metadata | Implemented in source: release-derived version, license/project metadata and isolated rebuild checks; verify publication of each accepted version | Release maintainer |

## Research inputs

The proposed protocol categories are Redfish, IPMI, SNMP and GPIO. Whether they
cover a specific device or operation must be established during driver design;
they are not a universal hardware support matrix.

- [Protocol-based taxonomy](roadmap/protocol-based-hardware-taxonomy.md): historical proposals and illustrative metadata.
- [Edge-device research](roadmap/nvidia-jetson-edge-devices.md): historical vendor/device observations requiring revalidation.
- [Bootstrap issue plan](roadmap/issue-119-bootstrap-cloud-init-and-reconcile-plan.md): historical implementation investigation, superseded where current code/tests differ.

Research labels, endpoint examples and pseudocode are non-deployable design
inputs. Credentials and URLs should not be copied into Kubernetes labels as a
future driver configuration contract. Promote a proposal only after an ADR,
versioned interface, tests, security review and operator documentation are merged.
