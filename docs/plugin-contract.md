# Hardware plugin design boundary

**Status: design requirements, not an implemented or versioned plugin API.**
There is no plugin loader, driver registration, RPC service, capability discovery
or Redfish/IPMI/SNMP/GPIO implementation in the shipped provider. Existing
internal Python modules are not a supported third-party extension interface.

## Existing preparation

`contracts.py` centralizes identity, pause and persisted status checks;
`inventory.py` owns allocation; `operations.py` fences SSH execution;
`lifecycle.py` observes reboot and cleanup outcomes. These separations allow a
future extension to reuse safety boundaries. They do not solve physical identity
or remote fencing for an out-of-band protocol.

## Required design decisions before implementation

| Concern | Required contract and acceptance evidence |
|---|---|
| Physical identity | Bind SSH, BMC and power outlet to one independently verified asset; reject ambiguous/replaced identity |
| Capability discovery | Explicit operation support and protocol/version negotiation; unsupported operations fail closed |
| Authorization | Separate read/health from destructive power/firmware actions; identify the initiating resource and policy |
| Coordination | A shared asset lock across SSH and every OOB driver; protocol-specific fencing against delayed commands |
| Operation state | Durable request ID, intent, submission, observation and completion; Unknown is a first-class result |
| Retry policy | Idempotency and receipt lookup; no automatic destructive replay after timeout, crash or lost response |
| Pause / deletion | Respect the same CAPI ownership and pause chain; resolve pending operations before cleanup/reassignment |
| Credentials | Namespaced references, rotation, independent endpoint trust and least privilege; no credentials in labels |
| Isolation | Explicit in-process versus sidecar/service decision, failure containment and resource budgets |
| Audit | Redacted actor/asset/request/outcome evidence with bounded retention and access controls |
| Upgrade | Versioned schema/API, compatibility tests and migration/recovery for persisted operation state |

A label naming a protocol cannot authorize a power cycle. A Lease keyed only by
SSH address/port cannot fence another driver that addresses the same hardware
through a BMC or PDU. Resolve that shared asset contract before implementing an
automatic OOB fallback for failed SSH.

## Admission test portfolio

Each future driver needs contract tests plus protocol/emulator tests for denied
authorization, changed certificates/identity, stale commands, delayed receipts,
duplicate requests, controller restarts, concurrent SSH/OOB operations and
credential rotation. Destructive functions require a dedicated canary on a
reviewed asset and explicit recovery evidence before support is claimed.

A driver PR must include the versioned interface, capability matrix, resource
budget, threat model, operator runbook and compatibility evidence. A protocol
library import or a successful power API call is insufficient.

## Roadmap relation

[Protocol taxonomy](roadmap/protocol-based-hardware-taxonomy.md) and
[edge-device research](roadmap/nvidia-jetson-edge-devices.md) are historical design
inputs. Their labels and pseudocode are not installable configuration. Hardware
claims must be revalidated against current vendor documentation when a driver is
proposed. The [roadmap](roadmap.md) records priorities without release guarantees.
