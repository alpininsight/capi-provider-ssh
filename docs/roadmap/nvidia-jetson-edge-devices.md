# NVIDIA Jetson Edge Devices for CAPI SSH Provider

## Status

**Research complete** — informs v0.3.x hardware plugin taxonomy and device class
coverage.

## Context

As a startup requiring simple, repeatable setups on standard hardware without
expensive vendor software, NVIDIA Jetson devices are a compelling option for
GPU-enabled edge/worker nodes in Kubernetes clusters managed by the CAPI SSH
provider. This document evaluates the Jetson family for fit with our
protocol-based hardware plugin architecture.

## Product Lineup (Current)

### Jetson Orin Family (Mainstream, Available Now)

| Model | AI Perf | RAM | Power | Price |
|-------|---------|-----|-------|-------|
| Jetson Orin Nano Super | 67 TOPS | 8 GB | 7-25W | $249 (dev kit) |
| Jetson Orin NX 8GB | 70 TOPS | 8 GB | 10-25W | ~$399 (module) |
| Jetson Orin NX 16GB | 157 TOPS | 16 GB | 10-40W | ~$599 (module) |
| Jetson AGX Orin 32GB | 200 TOPS | 32 GB | 15-40W | ~$999 (module) |
| Jetson AGX Orin 64GB | 275 TOPS | 64 GB | 15-60W | $1,999 (dev kit) |

The **Orin Nano Super** ($249 dev kit) is the best-value entry point. All Orin
devices run JetPack 6.x (Ubuntu 22.04 aarch64), support standard kubeadm, and
include CUDA/cuDNN/TensorRT at no additional software cost.

### Jetson AGX Thor (Next Gen, Blackwell Architecture)

| Model | AI Perf | RAM | Power | Price |
|-------|---------|-----|-------|-------|
| Jetson AGX Thor | 2,070 TOPS | 128 GB | 130W | $3,499 (dev kit) |

Overkill for most clusters. Relevant only for heavy inference workloads (70B+
parameter LLMs at the edge).

### Avoid for New Deployments

- Jetson Nano (original) — discontinued, Maxwell GPU, JetPack 4.x only
- Jetson Xavier NX / AGX Xavier — approaching EOL

## Management Interfaces: The Critical Finding

### Standard Jetson: No BMC, No IPMI, No Redfish

Jetson modules are embedded SoMs, fundamentally like Raspberry Pis regarding
management. They have **no out-of-band management** — no BMC, no IPMI, no
Redfish. All management is in-band via SSH or external power control.

This places Jetson devices in the same CAPI plugin categories as Raspberry Pi:

- **`snmp`** — power managed via a smart PDU with per-outlet SNMP control
- **`gpio`** — power managed via a relay controller

### Exception: NVIDIA IGX Orin (Enterprise)

The IGX Orin is the enterprise variant with a full **OpenBMC-based BMC** and
**Redfish API**. It provides remote power control, virtual media, telemetry,
firmware management, and serial console. However:

- Price: $2,000-5,000+ (enterprise quoting)
- 10-year lifecycle with enterprise support
- Designed for industrial/medical use, not startup clusters

**Verdict:** IGX Orin falls under the `redfish` plugin. Standard Jetson devices
fall under `snmp` or `gpio`, same as Raspberry Pi.

### Turing Pi 2.5: Interesting Middle Ground

The Turing Pi 2.5 ($359) is a mini-ITX carrier board accepting up to 4 Jetson
Nano/NX modules with:

- Built-in BMC with open-source firmware
- Per-node remote power control (on/off/reset)
- Serial console over LAN
- 8-port managed Ethernet with VLAN (802.1Q)
- Remote OS image flashing

This provides BMC-like management for Jetson at reasonable cost. It only
supports SO-DIMM form factor (Nano/NX), not AGX. If adopted, this would likely
be a fifth plugin (`turingpi`) or extend the `gpio` plugin with a Turing Pi
backend.

## Kubernetes on Jetson

### Standard kubeadm Path

JetPack 6.x runs standard aarch64 Ubuntu 22.04. Kubernetes works normally:

1. Flash JetPack 6.x (SD card or NVMe)
2. Install `nvidia-container-toolkit` (included in JetPack, or via apt)
3. Install `kubeadm`/`kubelet`/`kubectl` from standard K8s apt repo
4. `kubeadm init` / `kubeadm join` as usual
5. Configure containerd with NVIDIA runtime
6. Deploy NVIDIA `k8s-device-plugin` DaemonSet

GPU resources appear as `nvidia.com/gpu` in pod specs.

### Caveats

- **ARM64 only** — all container images must support `linux/arm64`
- **Integrated GPU** — shares system memory, no separate VRAM pool
- **GPU Operator not supported** — NVIDIA GPU Operator does not work on Jetson;
  GPU stack is managed at the OS level via JetPack
- **CAPI SSH provider** needs no GPU-specific logic — the GPU is exposed as a
  standard Kubernetes extended resource via the device plugin

### Fit with CAPI SSH Provider

The CAPI SSH provider manages Jetson nodes identically to any SSH-accessible
Linux host:

| Operation | How |
|-----------|-----|
| Provisioning | SSH into pre-flashed node, `kubeadm join` |
| Health probing | SSH connectivity check, kubelet status |
| Soft reboot | SSH `sudo reboot` |
| Hard power cycle | Via PDU (SNMP plugin) or relay (GPIO plugin) |
| GPU workloads | No CAPI handling — k8s-device-plugin manages GPU scheduling |

## Software Licensing: All Free

| Component | License | Cost |
|-----------|---------|------|
| JetPack SDK (OS, drivers, libraries) | NVIDIA EULA | Free |
| CUDA Toolkit | Free | Free |
| cuDNN, TensorRT | Free | Free |
| nvidia-container-toolkit | Apache 2.0 | Free |
| k8s-device-plugin | Apache 2.0 | Free |
| DeepStream SDK | Free on Jetson | Free |

**No per-unit royalties, no subscriptions, no production licenses.** The EULA
only restricts the software to NVIDIA Jetson hardware. Enterprise support
contracts (NVIDIA AI Enterprise, ~$4,500/GPU/year) are optional and irrelevant
for startup clusters.

## Cost Comparison: 5-Node Cluster

| Component | Raspberry Pi 5 (8GB) | Jetson Orin Nano Super |
|-----------|---------------------|----------------------|
| Compute (5 units) | $400 | $1,245 |
| Storage (NVMe) | $200 | $250 |
| Networking | $30 | $30 |
| Power (adapters) | $50 | $100 |
| Power management (smart PDU) | $40 | $40 |
| Cases/cooling | $50 | $50 |
| **Total** | **~$770** | **~$1,715** |
| **GPU (CUDA)** | None | 5x CUDA GPU nodes |

Jetson costs ~2x Raspberry Pi but provides CUDA GPU capability on every node.
Both are managed identically by the CAPI SSH provider — same plugin
architecture, same power management approach.

## Power Management Recommendation

For a startup cluster of 3-10 Jetson (or mixed Jetson + RPi) nodes:

### Primary: Smart PDU with SNMP (recommended)

- Network-managed PDU with per-outlet switching
- APC Switched PDU, or budget: Tasmota-flashed smart plugs (~$15-20/outlet)
- Maps to CAPI SSH provider `snmp` hardware plugin
- Configure Jetson carrier board for auto-power-on when power restored

### Alternative: Turing Pi 2.5 (for Nano/NX clusters)

- 4 nodes per board with integrated BMC-like management
- Per-node power control, serial console, VLAN networking
- Would need a dedicated plugin backend or custom integration

### Fallback: GPIO relay

- Separate controller (RPi or microcontroller) toggles relay board
- Maps to CAPI SSH provider `gpio` hardware plugin
- Most flexible but requires custom wiring

## Implications for Plugin Taxonomy

No changes needed to the four-protocol taxonomy. Jetson devices fit naturally:

| Device | Plugin | Notes |
|--------|--------|-------|
| Jetson Orin (any) + Smart PDU | `snmp` | PDU per-outlet power control |
| Jetson Orin (any) + GPIO relay | `gpio` | Relay controller toggles power |
| Jetson on Turing Pi 2.5 | `gpio` or future `turingpi` | BMC-like API, could be GPIO backend |
| NVIDIA IGX Orin | `redfish` | Full OpenBMC with Redfish API |

The device class table in the roadmap already covers "SBC / Edge" which
includes Jetson. No new plugin IDs needed.

## Sources

- [NVIDIA Jetson Orin Product Page](https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/)
- [NVIDIA IGX Platform](https://www.nvidia.com/en-us/edge-computing/products/igx/)
- [IGX Orin BMC Redfish API](https://docs.nvidia.com/igx-orin/bmc/latest/redfish-api.html)
- [Turing Pi 2.5](https://turingpi.com/product/turing-pi-2-5/)
- [NVIDIA k8s-device-plugin](https://github.com/NVIDIA/k8s-device-plugin)
- [Cloud-Native on Jetson](https://developer.nvidia.com/embedded/jetson-cloud-native)
- [JetPack EULA](https://docs.nvidia.com/jetson/jetpack/eula/index.html)
