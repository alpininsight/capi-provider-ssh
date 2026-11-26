# Edge-host qualification: NVIDIA Jetson and other ARM64 Linux hosts

This is a research boundary, not a supported-device list or a hardware purchasing
guide. The current provider works with prepared Linux hosts over verified SSH.
A device-specific Kubernetes lifecycle must be validated before claiming support.
See the [support matrix](../support-matrix.md) and [plugin design](../plugin-contract.md).

## What must be established for an edge host?

| Question | Required evidence |
|---|---|
| Is the host prepared? | Compatible Linux, network/SSH reachability, independently verified host trust, required privileges and `flock` |
| Does the Kubernetes baseline work? | Reviewed runtime and kubeadm/packages; successful init or join with the selected versions |
| Is the architecture covered? | Matching controller and workload images; an ARM64 image publication alone does not certify a physical device |
| Who owns GPU setup? | The host/image and workload platform supply vendor drivers, runtime integration and any Kubernetes device plugin |
| What happens on failure? | Measured SSH lifecycle, reboot observation, cleanup/reuse and controller failover on the intended host type |
| Is remote power required? | An independently designed and accepted out-of-band integration; none is shipped by this provider |

The SSH controller does not provision JetPack, install a GPU stack, expose a GPU
resource or schedule GPU workloads. Those decisions belong to host preparation
and the workload platform. Check current vendor guidance for the exact device,
OS, driver, runtime and Kubernetes combination rather than extrapolating from a
single board or development kit.

## Optional power-management research

[Protocol-based taxonomy](protocol-based-hardware-taxonomy.md) discusses possible
Redfish, IPMI, SNMP and GPIO integrations. They are design candidates, not
installed drivers or guaranteed hardware coverage. A carrier board, PDU or relay
may introduce its own protocol, security and shared-asset identity requirements.
The SSH-only lifecycle requires no such plugin.

There is no product price comparison, vendor license assessment or purchase
recommendation in this support documentation. Evaluate those through the vendor's
current terms and the operator's own procurement process.

## Primary inputs to a future qualification

- [NVIDIA Jetson platform](https://developer.nvidia.com/embedded/jetson).
- [NVIDIA cloud-native guidance for Jetson](https://developer.nvidia.com/embedded/jetson-cloud-native).
- [NVIDIA Kubernetes device plugin](https://github.com/NVIDIA/k8s-device-plugin).

These links are evaluation inputs, not evidence that this provider has completed
a physical Jetson lifecycle or certified a particular vendor configuration.
