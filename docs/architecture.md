# Architecture: Provider Boundaries

## CAPI's Three-Layer Model

Cluster API splits cluster lifecycle into three provider types, each with a
distinct responsibility:

| Layer | Provider | Responsibility |
|-------|----------|---------------|
| **Infrastructure** | `capi-provider-ssh` (this project) | Provide a reachable machine (SSH connectivity, host inventory) |
| **Bootstrap** | `kubeadm` (upstream) | Generate the bootstrap script (package installation, kubeadm init/join) |
| **Control Plane** | `kubeadm` (upstream) | Manage control plane topology (scaling, upgrades, rollouts) |

```
┌────────────────────────────────────────────────────┐
│              Control Plane Provider                 │
│   (KubeadmControlPlane -- topology, upgrades)      │
├────────────────────────────────────────────────────┤
│              Bootstrap Provider                     │
│   (KubeadmConfig -- script generation,             │
│    package installation, kubeadm init/join)         │
├────────────────────────────────────────────────────┤
│              Infrastructure Provider                │
│   (SSHMachine -- SSH connectivity, host claiming,  │
│    script upload + execution)                       │
└────────────────────────────────────────────────────┘
```

## Where Package Installation Belongs

A common question: *"Shouldn't the infrastructure provider install containerd, kubeadm, and kubelet?"*

**No.** Package installation belongs in the **bootstrap provider**, not the
infrastructure provider. The kubeadm bootstrap provider supports
`preKubeadmCommands` specifically for this purpose -- commands that run before
`kubeadm init`/`kubeadm join` in the generated bootstrap script.

### Why This Separation Matters

1. **The bootstrap provider already generates a shell script.** Our SSH provider
   uploads and executes that script. Adding package installation to the infra
   provider would duplicate what `preKubeadmCommands` already does.

2. **Package versions are a bootstrap concern.** The Kubernetes version is
   declared in `KubeadmControlPlane` / `KubeadmConfig`, not in the
   infrastructure provider. The bootstrap layer knows which versions to install.

3. **Other providers do the same.** CAPD (Docker), CAPH (Hetzner Cloud), and
   Metal3 all rely on `preKubeadmCommands` or pre-built images for package
   installation. None install packages in the infrastructure provider.

4. **Separation of concerns.** The infra provider's job is: *"give me a
   reachable machine."* The bootstrap provider's job is: *"prepare that machine
   for Kubernetes."*

### Host Preparation Tiers

Enterprise CAPI deployments use one of three approaches for host preparation:

| Tier | Approach | When to Use |
|------|----------|-------------|
| **Tier 1** | Pre-built images via [image-builder](https://github.com/kubernetes-sigs/image-builder) | Production — containerd, kubeadm, kubelet baked into OS image |
| **Tier 2** | Grouped `preKubeadmCommands` | Bare-metal without image pipelines — atomic steps per concern |
| **Tier 3** | Single large script block | Not recommended — hard to debug, no per-step logging |

### Example: Production-Ready Bare-Metal Bootstrap (Tier 2)

```yaml
apiVersion: controlplane.cluster.x-k8s.io/v1beta1
kind: KubeadmControlPlane
metadata:
  name: my-cluster-cp
spec:
  kubeadmConfigSpec:
    preKubeadmCommands:
      # 1. System prerequisites
      - swapoff -a && sed -i '/swap/d' /etc/fstab
      - modprobe overlay && modprobe br_netfilter
      - |
        cat > /etc/sysctl.d/99-kubernetes.conf <<EOF
        net.bridge.bridge-nf-call-iptables = 1
        net.bridge.bridge-nf-call-ip6tables = 1
        net.ipv4.ip_forward = 1
        EOF
        sysctl --system

      # 2. Container runtime
      - apt-get update && apt-get install -y containerd
      - |
        mkdir -p /etc/containerd
        containerd config default > /etc/containerd/config.toml
        sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
        systemctl restart containerd
        systemctl enable containerd

      # 3. Kubernetes packages
      - |
        curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key \
          | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
        echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
          https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /" \
          > /etc/apt/sources.list.d/kubernetes.list
        apt-get update
        apt-get install -y kubelet kubeadm kubectl
        apt-mark hold kubelet kubeadm kubectl
        systemctl enable kubelet

    initConfiguration:
      nodeRegistration:
        kubeletExtraArgs:
          cloud-provider: external
```

**Why grouped atomic steps:**
- If step 2 fails, you know it's the container runtime — not buried in a 50-line script
- The bootstrap provider logs each command's output separately
- Individual concerns can be version-controlled and adapted per-cluster
- Workers might skip some steps (e.g., kubectl not needed on workers)

For worker nodes, the same pattern applies in `KubeadmConfigTemplate`:

```yaml
apiVersion: bootstrap.cluster.x-k8s.io/v1beta1
kind: KubeadmConfigTemplate
metadata:
  name: my-cluster-workers
spec:
  template:
    spec:
      preKubeadmCommands:
        # Workers skip kubectl and use the same container runtime + kubelet setup
        - swapoff -a && sed -i '/swap/d' /etc/fstab
        - modprobe overlay && modprobe br_netfilter
        - apt-get update && apt-get install -y containerd
        - |
          mkdir -p /etc/containerd
          containerd config default > /etc/containerd/config.toml
          sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
          systemctl restart containerd
          systemctl enable containerd
        - |
          curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.32/deb/Release.key \
            | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
          echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] \
            https://pkgs.k8s.io/core:/stable:/v1.32/deb/ /" \
            > /etc/apt/sources.list.d/kubernetes.list
          apt-get update
          apt-get install -y kubelet kubeadm
          apt-mark hold kubelet kubeadm
          systemctl enable kubelet
```

## What the Infrastructure Provider Does

`capi-provider-ssh` is intentionally minimal. It handles:

| Capability | Description |
|-----------|-------------|
| **SSH connectivity** | Connect to pre-provisioned hosts via key-based auth |
| **Host inventory** | Claim/release hosts from SSHHost pool (Metal3-style) |
| **Script execution** | Upload and execute the bootstrap script generated by kubeadm |
| **Cleanup** | Run `kubeadm reset` on deletion |
| **External etcd** | Distribute certs and patch kubeadm config for external etcd |
| **Health probing** | Periodic SSH connectivity checks on SSHHost pool |
| **Dry-run** | Validate prerequisites without executing bootstrap |
| **Reboot remediation** | In-band SSH reboot for machine remediation |

## SSH Key Lifecycle Boundary

The provider consumes SSH private keys from Kubernetes Secrets referenced by
`spec.sshKeyRef`; it does not generate, rotate, or escrow keys itself.

- Provider contract: `spec.sshKeyRef.name` plus optional `spec.sshKeyRef.key`
  (defaults to `value`)
- Operational lifecycle: managed via GitOps (SOPS or External Secrets)
- Rotation and rollback procedure: [docs/ssh-key-lifecycle.md](ssh-key-lifecycle.md)

## What the Infrastructure Provider Does NOT Do

| Capability | Why Not | Where It Belongs |
|-----------|---------|-----------------|
| Package installation | Solved by `preKubeadmCommands` | Bootstrap provider |
| OS provisioning | SSH provider assumes OS is installed | Out of scope (rescue mode, cloud-init, PXE) |
| Image building | Not an infra provider concern | Packer, image pipelines |
| Generic hook framework | YAGNI -- only external etcd exists as a specific feature | Reconsider when a second use case emerges |

## How the Bootstrap Script Flows

```
1. KubeadmControlPlane / KubeadmConfig
   └─ Bootstrap provider generates shell script
      ├─ preKubeadmCommands (package install, system config)
      ├─ kubeadm init / kubeadm join
      └─ postKubeadmCommands (optional post-setup)

2. Bootstrap provider stores script in a Secret
   └─ Machine.spec.bootstrap.dataSecretName

3. SSHMachine controller reads the Secret
   └─ Optionally patches it (external etcd wiring)

4. SSHMachine controller uploads + executes via SSH
   └─ Sets providerID and initialization.provisioned on success
```
