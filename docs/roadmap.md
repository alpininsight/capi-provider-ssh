# Roadmap

## Active Fix Plans

- [Issue #119: Cloud-init bootstrap compatibility + SSHMachine reconcile reliability](roadmap/issue-119-bootstrap-cloud-init-and-reconcile-plan.md)
- [Issue #149: Bootstrap safety and reconcile hardening (cross-process concurrency, sentinel guard, UID validation, readiness semantics, diagnostics)](roadmap/issue-149-bootstrap-safety-and-reconcile-hardening-plan.md)

## Current Capabilities (v0.3.x)

| Feature | Status |
|---------|--------|
| SSH bootstrap (kubeadm init/join) | Implemented |
| Host inventory (SSHHost pool, Metal3-style claim/release) | Implemented |
| External etcd wiring (cert distribution, kubeadm patching) | Implemented |
| Reboot remediation (in-band SSH reboot) | Implemented |
| Dry-run mode (preflight validation without execution) | Implemented |
| SSHHost health probing (periodic SSH connectivity checks) | Implemented |
| Cleanup on deletion (kubeadm reset) | Implemented |
| Pause/unpause support | Implemented |
| SSH key lifecycle (SOPS/External Secrets + rotation runbook) | Implemented |
| Flux rollout gate (explicit unsuspend/rollback runbook) | Implemented |
| Live rollout validation + teardown runbook | Implemented |
| DNS cutover runbook (staging promotion + rollback gate) | Implemented |

## Planned: Image Builder Support (v0.2.x)

Move from Tier 2 (`preKubeadmCommands` for package installation) to Tier 1
(pre-built OS images) for production deployments.

- Integration with [kubernetes-sigs/image-builder](https://github.com/kubernetes-sigs/image-builder)
  for bare-metal and dedicated server environments
- Pre-built images with containerd, kubeadm, and kubelet baked in
- Eliminates `preKubeadmCommands` for package installation
- Image versioning tied to Kubernetes version (e.g., `k8s-1.32-ubuntu-24.04`)
- Support for common provisioning workflows: rescue mode → write image → reboot → SSH bootstrap

## Planned: Hardware Plugin Interface (v0.3.x)

Extensible plugin system for out-of-band (OOB) management operations. SSH
covers in-band management, but bare-metal servers and edge devices often need
out-of-band operations — power cycling unresponsive hosts, health monitoring,
firmware checks — that vary by **protocol**, not vendor.

### Problem

The SSH provider handles in-band operations (connect, execute, reboot). But
hardware management spans a wider range of devices and use cases:

- **Power management** — hard power cycle when a host is unresponsive to SSH
- **Health monitoring** — disk, memory, PSU, temperature status before claiming
- **Firmware queries** — BIOS/BMC version checks as pre-bootstrap gates
- **Console access** — remote KVM for debugging boot failures
- **LED identification** — locate a specific server in a rack
- **Edge device power** — toggle PoE ports or GPIO relays for SBCs

These operations should not be hardcoded into the provider core.

### Why Protocol-Based, Not Vendor-Based

The industry confirms this direction. OpenStack Ironic started with
vendor-specific drivers (ilo, drac, cisco-ucs) and converged on protocol-based
generic drivers (redfish, ipmi). The Ironic community does not anticipate new
vendor-specific hardware types since Redfish supersedes them.

The key insight: multiple vendors share the same protocol. HPE iLO 5, Dell
iDRAC 9, Lenovo XCC, and Supermicro BMCs all implement DMTF Redfish. A single
`redfish` plugin handles all of them. Vendor-specific quirks (OEM extensions)
are handled as configuration, not separate plugins.

```
WRONG (vendor-centric):            RIGHT (protocol-centric):
┌─────────┐ ┌─────────┐           ┌──────────────────┐
│  ilo5   │ │  idrac  │           │     redfish      │ ← single plugin
└─────────┘ └─────────┘           │  HPE, Dell, SMC  │
  Both speak Redfish!             └──────────────────┘
```

### Protocol Landscape

| Protocol | Layer | Transport | Vendors / Devices | Capabilities |
|----------|-------|-----------|-------------------|-------------|
| **Redfish** | BMC (modern) | HTTPS + JSON | HPE iLO 5+, Dell iDRAC 8+, Lenovo XCC, Supermicro, Huawei iBMC, Cisco CIMC | Power, health, firmware, virtual media, BIOS config, RAID, telemetry |
| **IPMI** | BMC (legacy) | UDP/RMCP+ | Nearly all x86 servers since ~2000 | Power, basic sensors, SOL console, boot device |
| **SNMP** | Network/PDU | UDP | Smart PDUs (APC, Raritan, CyberPower), managed PoE switches | Per-outlet power on/off, environmental sensors, port control |
| **GPIO** | Physical | Direct wiring | Raspberry Pi, Jetson, SBCs, relay boards | Relay toggle for power, pin read for status |

### Device Classes

Protocols alone are not enough. Devices also differ by **class** — what kind of
hardware they are and what management operations apply:

| Device Class | Examples | Management Model | Typical Protocol |
|-------------|----------|-----------------|-----------------|
| Enterprise server | HPE DL380, Dell R750, Lenovo SR650 | Built-in BMC (iLO, iDRAC, XCC) | Redfish, IPMI |
| Whitebox server | Supermicro, custom builds | BMC with varying Redfish support | Redfish, IPMI |
| GPU edge / SBC | NVIDIA Jetson Orin, Raspberry Pi 5, Rock Pi | No BMC; external power control via PDU or relay | SNMP (via PDU), GPIO |
| Industrial edge | NVIDIA IGX Orin | OpenBMC with Redfish API | Redfish |
| Power distribution | APC, Raritan, Server Technology | Smart PDU with per-outlet control | SNMP, HTTP API |

The plugin label on SSHHost is a **protocol identifier**. Device class is
implicit from the protocol and annotations used.

### Design

```
SSHMachine Controller
├── In-band (SSH): bootstrap, cleanup, reboot — built-in
└── Out-of-band: power, health, firmware — delegated to plugins
        │
        │ gRPC or exec call
        ▼
Hardware Plugin (sidecar or standalone)
├── Implements HardwarePlugin contract
└── Protocol-specific client (Redfish, IPMI, SNMP, GPIO)
```

### Plugin Taxonomy

Four plugins cover the entire hardware spectrum — from enterprise rack servers
to Raspberry Pi edge nodes. No vendor names in plugin IDs.

| Plugin ID | Protocol | Device Classes | What It Covers |
|-----------|----------|---------------|---------------|
| `redfish` | DMTF Redfish (HTTPS/JSON) | Enterprise servers, whitebox servers, industrial edge | HPE iLO 5+, Dell iDRAC 8+, Lenovo XCC, Supermicro, Huawei iBMC, Cisco CIMC, NVIDIA IGX Orin, any Redfish-compliant BMC |
| `ipmi` | IPMI over LAN (RMCP+) | Legacy servers, whitebox servers | Any server with IPMI BMC (fallback for servers without Redfish) |
| `snmp` | SNMP v2c/v3 | Smart PDUs, managed PoE switches | APC, Raritan, Server Technology, CyberPower, any managed PDU with per-outlet MIBs; PoE switches for SBC power control |
| `gpio` | SSH + GPIO | SBCs, relay boards | Raspberry Pi, Jetson — uses a controller host to toggle GPIO pins connected to power relays |

### Capability Matrix

Not every plugin implements every operation. The contract uses optional
capabilities — a `gpio` plugin reports `PowerOn`/`PowerOff`/`PowerStatus`
but returns "unsupported" for `HealthCheck` and `FirmwareVersion`.

| Operation | `redfish` | `ipmi` | `snmp` | `gpio` |
|-----------|-----------|--------|--------|--------|
| `PowerOn` | yes | yes | yes | yes |
| `PowerOff` (+ force flag) | yes | yes | yes | yes |
| `PowerCycle` | yes | yes | yes | yes |
| `PowerStatus` | yes | yes | yes | yes |
| `HealthCheck` | yes | yes (basic sensors) | no | no |
| `FirmwareVersion` | yes | yes (limited) | no | no |
| `IdentifyLED` | yes | no | no | no |

### Plugin Discovery via SSHHost

The `hardware-plugin` label selects the protocol. Annotations provide
connection details specific to that protocol.

**Enterprise server (Redfish BMC):**

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

**Edge device managed via smart PDU (SNMP):**

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

**Raspberry Pi managed via GPIO relay:**

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

### Target Hardware for Startup / Edge Clusters

For startups and small teams that need simple, repeatable setups on standard
hardware without expensive vendor software, two device families stand out:

| Device | GPU | Price | K8s | Power Mgmt | Software Cost |
|--------|-----|-------|-----|------------|---------------|
| **Raspberry Pi 5** (8GB) | None (VideoCore, no CUDA) | ~$80 | Standard kubeadm | PDU or GPIO relay | Free |
| **Jetson Orin Nano Super** | 1024 CUDA cores, 67 TOPS | $249 (dev kit) | Standard kubeadm + nvidia-container-toolkit | PDU or GPIO relay | Free (JetPack, CUDA, TensorRT) |
| **Jetson Orin NX 16GB** | 1024 CUDA cores, 157 TOPS | ~$599 (module + carrier) | Standard kubeadm + nvidia-container-toolkit | PDU or GPIO relay | Free |

Both run standard aarch64 Linux, support kubeadm natively, and are managed
identically by the CAPI SSH provider. Neither has a BMC — power management
uses the `snmp` plugin (smart PDU) or `gpio` plugin (relay board).

A 5-node Jetson Orin Nano Super cluster costs ~$1,700 total and provides CUDA
GPU on every node. A mixed cluster (3x RPi workers + 2x Jetson GPU workers)
offers the best cost/capability balance.

NVIDIA Jetson software (JetPack, CUDA, cuDNN, TensorRT, container toolkit) is
**free for commercial use** with no per-unit royalties or subscriptions. The
GPU Operator does not support Jetson — the GPU stack is managed at the OS level
via JetPack, which the CAPI SSH provider treats as a `preKubeadmCommands`
concern.

See [nvidia-jetson-edge-devices.md](roadmap/nvidia-jetson-edge-devices.md) for
the full evaluation.

### Integration Points

1. **`_choose_host` enhancement** — optionally call `HealthCheck` before
   claiming a host, skip hosts with degraded hardware
2. **Reboot remediation fallback** — if SSH reboot fails (host unresponsive),
   fall back to `PowerCycle` via the hardware plugin
3. **Pre-bootstrap gate** — validate firmware versions meet minimum
   requirements before executing the bootstrap script
4. **SSHHost probing enrichment** — include hardware health data in
   `status.conditions` alongside SSH reachability

## What We Explicitly Do NOT Build

| Feature | Why Not |
|---------|---------|
| Package installation in provider | Solved by `preKubeadmCommands` at bootstrap layer |
| External tool dependency (Ansible, etc.) | All host preparation handled by `preKubeadmCommands` |
| Generic pre/post-bootstrap hook framework | YAGNI — only external etcd exists as a specific feature |
| OS installation | Out of scope — SSH provider assumes OS already installed |
| Host auto-discovery | Manual SSHHost registration is sufficient for known inventory |
