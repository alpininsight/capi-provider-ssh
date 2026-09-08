# Roadmap and maturity

This is a planning document. It does not assign release dates, guarantee support
or describe installed plugins. The [support matrix](support-matrix.md) records
the current implementation; [plugin requirements](plugin-contract.md) define the
extension work still required.

## Implemented foundation

The Python provider has persistent UID-bound allocation, verified SSH trust,
CAPI pause/identity checks, fenced bootstrap receipts, cleanup quarantine, reboot
observation and coordinated two-replica operation. Internal module boundaries
separate these concerns. They are not a stable third-party driver SDK.

## Next decision gates

| Area | Work before claiming support | Acceptance owner |
|---|---|---|
| CAPI contract evolution | [Current gaps and ordered v1beta2 migration](capi-contract-migration.md), API/upgrade decision and upstream compatibility tests | Provider maintainer |
| Provider packaging | Versioned clusterctl metadata/components and install/upgrade tests | Release maintainer |
| Hardware extensions | Shared asset identity, capability/version negotiation, authorization and cross-protocol fencing | Provider / platform maintainers |
| First OOB driver | Protocol emulator tests, lost-response/crash tests and an explicitly selected physical canary | Driver maintainer |
| Production operating envelope | Fleet-scale/soak measurements, resource sizing, recovery objectives and supported OS baselines | Platform owner |
| Security operations | Verified private reporting channel and an explicit maintenance/backport policy | Repository maintainers |

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
