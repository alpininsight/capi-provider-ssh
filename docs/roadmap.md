# Roadmap

## Current Capabilities (v0.1.x)

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

Extensible plugin system for vendor-specific out-of-band (OOB) management
operations. SSH covers in-band management, but many bare-metal operations
require BMC/IPMI access that is vendor-specific.

### Problem

The SSH provider handles in-band operations (connect, execute, reboot). But
bare-metal servers often need out-of-band operations that vary by hardware
vendor:

- **Power management** — hard power cycle when a host is unresponsive to SSH
- **Health monitoring** — disk, memory, PSU, temperature status before claiming
- **Firmware queries** — BIOS/BMC version checks as pre-bootstrap gates
- **Console access** — remote KVM for debugging boot failures
- **LED identification** — locate a specific server in a rack

These operations are vendor-specific and should not be hardcoded into the
provider core.

### Design

```
SSHMachine Controller
├── In-band (SSH): bootstrap, cleanup, reboot — built-in
└── Out-of-band (BMC): power, health, firmware — delegated to plugins
        │
        │ gRPC or exec call
        ▼
Hardware Plugin (sidecar or standalone)
├── Implements HardwarePlugin contract
└── Vendor-specific SDK (iLO, iDRAC, Redfish, IPMI)
```

**Plugin discovery:** SSHHost annotation or label selects the plugin:

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHHost
metadata:
  name: server-42
  labels:
    hardware-plugin: ilo5
  annotations:
    hardware-plugin.alpininsight.ai/endpoint: "https://ilo-server-42.mgmt.local"
spec:
  address: 10.0.0.42
  sshKeyRef:
    name: ssh-key
```

**Plugin contract** (gRPC or exec-based sidecar):

| Operation | Input | Output |
|-----------|-------|--------|
| `PowerOn` | host identifier | success/failure |
| `PowerOff` | host identifier, force flag | success/failure |
| `PowerCycle` | host identifier | success/failure |
| `PowerStatus` | host identifier | on/off/unknown |
| `HealthCheck` | host identifier | component statuses (disk, memory, PSU, fans) |
| `FirmwareVersion` | host identifier | BIOS version, BMC version |
| `IdentifyLED` | host identifier, on/off | success/failure |

**Target vendor plugins:**

| Plugin | Hardware | Protocol |
|--------|----------|----------|
| `ilo5` | HPE ProLiant (iLO 5/6) | Redfish REST API |
| `idrac` | Dell PowerEdge (iDRAC 8/9) | Redfish REST API |
| `ucs` | Cisco UCS | Cisco UCS Manager XML API |
| `xclarity` | Lenovo ThinkSystem | Lenovo XClarity REST API |
| `ipmi` | Generic (any IPMI-capable server) | IPMI over LAN (ipmitool) |
| `redfish` | Generic Redfish-compliant BMC | DMTF Redfish standard |

**Integration points in the provider:**

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
