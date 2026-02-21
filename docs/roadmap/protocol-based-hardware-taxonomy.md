# Protocol-Based Hardware Plugin Taxonomy

## Status

**Accepted** — incorporated into `docs/roadmap.md` v0.3.x section.

## Context

The original `docs/roadmap.md` listed hardware plugins by vendor name (`ilo5`,
`idrac`, `ucs`, `xclarity`). This created unnecessary duplication — HPE iLO and
Dell iDRAC both speak Redfish, yet they would be separate plugins. Worse, it
baked vendor lock-in into the design itself.

The industry confirms this direction: OpenStack Ironic started with
vendor-specific drivers and converged on protocol-based generic drivers
(redfish, ipmi). The Ironic community does not anticipate new vendor-specific
types since Redfish supersedes them.

## Decision

Redesign the hardware plugin taxonomy around **protocols and device classes**
instead of vendor names. Expand coverage to include edge devices (Raspberry Pi,
SBCs) and power distribution (smart PDUs).

## Protocol Landscape

| Protocol | Layer | Transport | Vendors / Devices | Capabilities |
|----------|-------|-----------|-------------------|-------------|
| **Redfish** | BMC (modern) | HTTPS + JSON | HPE iLO 5+, Dell iDRAC 8+, Lenovo XCC, Supermicro, Huawei iBMC, Cisco CIMC | Power, health, firmware, virtual media, BIOS config, RAID, telemetry |
| **IPMI** | BMC (legacy) | UDP/RMCP+ | Nearly all x86 servers since ~2000 | Power, basic sensors, SOL console, boot device |
| **SNMP** | Network/PDU | UDP | Smart PDUs (APC, Raritan, CyberPower), managed PoE switches | Per-outlet power on/off, environmental sensors, port control |
| **GPIO** | Physical | Direct wiring | Raspberry Pi, Jetson, SBCs, relay boards | Relay toggle for power, pin read for status |

## Key Insight: Protocol != Vendor

```
WRONG (vendor-centric):            RIGHT (protocol-centric):
┌─────────┐ ┌─────────┐           ┌──────────────────┐
│  ilo5   │ │  idrac  │           │     redfish      │ ← single plugin
└─────────┘ └─────────┘           │  HPE, Dell, SMC  │
  Both speak Redfish!             └──────────────────┘
```

Multiple vendors share the same protocol. A single `redfish` plugin handles
HPE iLO 5, Dell iDRAC 9, Lenovo XCC, and Supermicro BMC because they all
implement the DMTF Redfish standard. Vendor-specific quirks (extended OEM
schemas) are handled as configuration, not separate plugins.

## Device Classes (second axis)

| Device Class | Examples | Management Model | Typical Protocol |
|-------------|----------|-----------------|-----------------|
| Enterprise server | HPE DL380, Dell R750, Lenovo SR650 | Built-in BMC (iLO, iDRAC, XCC) | Redfish, IPMI |
| Whitebox server | Supermicro, custom builds | BMC with varying Redfish support | Redfish, IPMI |
| GPU edge / SBC | NVIDIA Jetson Orin, Raspberry Pi 5, Rock Pi | No BMC; external power control via PDU or relay | SNMP (via PDU), GPIO |
| Industrial edge | NVIDIA IGX Orin | OpenBMC with Redfish API | Redfish |
| Power distribution | APC, Raritan, Server Technology | Smart PDU with per-outlet control | SNMP, HTTP API |

## Final Plugin Taxonomy

Four plugins cover the entire hardware spectrum:

| Plugin ID | Protocol | Device Classes | What It Covers |
|-----------|----------|---------------|---------------|
| `redfish` | DMTF Redfish (HTTPS/JSON) | Enterprise servers, whitebox servers, industrial edge | HPE iLO 5+, Dell iDRAC 8+, Lenovo XCC, Supermicro, Huawei iBMC, Cisco CIMC, NVIDIA IGX Orin, any Redfish-compliant BMC |
| `ipmi` | IPMI over LAN (RMCP+) | Legacy servers, whitebox servers | Any server with IPMI BMC (fallback for servers without Redfish) |
| `snmp` | SNMP v2c/v3 | Smart PDUs, managed PoE switches | APC, Raritan, Server Technology, CyberPower, any managed PDU with per-outlet MIBs; PoE switches for SBC power control |
| `gpio` | SSH + GPIO | SBCs, relay boards | Raspberry Pi, Jetson — uses a controller host to toggle GPIO pins connected to power relays |

## Capability Matrix

| Operation | `redfish` | `ipmi` | `snmp` | `gpio` |
|-----------|-----------|--------|--------|--------|
| `PowerOn` | yes | yes | yes | yes |
| `PowerOff` (+ force flag) | yes | yes | yes | yes |
| `PowerCycle` | yes | yes | yes | yes |
| `PowerStatus` | yes | yes | yes | yes |
| `HealthCheck` | yes | yes (basic sensors) | no | no |
| `FirmwareVersion` | yes | yes (limited) | no | no |
| `IdentifyLED` | yes | no | no | no |

## SSHHost Examples

### Enterprise server (Redfish BMC)

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHHost
metadata:
  name: server-42
  labels:
    hardware-plugin: redfish
  annotations:
    hardware-plugin.alpininsight.ai/endpoint: "https://bmc-42.mgmt.local"
    hardware-plugin.alpininsight.ai/secret: "bmc-credentials-42"
spec:
  address: 10.0.0.42
  sshKeyRef:
    name: ssh-key
```

### Edge device managed via smart PDU (SNMP)

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHHost
metadata:
  name: rpi-node-3
  labels:
    hardware-plugin: snmp
  annotations:
    hardware-plugin.alpininsight.ai/endpoint: "192.168.1.200"
    hardware-plugin.alpininsight.ai/outlet: "6"
    hardware-plugin.alpininsight.ai/secret: "pdu-community"
spec:
  address: 10.0.0.103
  sshKeyRef:
    name: rpi-ssh-key
```

### Raspberry Pi managed via GPIO relay

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHHost
metadata:
  name: rpi-worker-1
  labels:
    hardware-plugin: gpio
  annotations:
    hardware-plugin.alpininsight.ai/endpoint: "10.0.0.200"
    hardware-plugin.alpininsight.ai/pin: "17"
    hardware-plugin.alpininsight.ai/secret: "relay-ssh-key"
spec:
  address: 10.0.0.101
  sshKeyRef:
    name: rpi-ssh-key
```

## Changes Made

- Replaced vendor-centric plugin table (`ilo5`, `idrac`, `ucs`, `xclarity`)
  with protocol-based taxonomy (`redfish`, `ipmi`, `snmp`, `gpio`)
- Added device class discussion explaining why protocol + device class replaces
  vendor name
- Added SBC/edge and PDU coverage (Raspberry Pi, smart PDUs)
- Added capability matrix showing which operations each plugin supports
- Added SSHHost label examples for each plugin type
- Added rationale section referencing Ironic's evolution as precedent
