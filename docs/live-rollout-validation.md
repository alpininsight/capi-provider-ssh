# Live Rollout Validation and Teardown

This runbook validates the full rollout path and defines a remove/teardown
action for each build-up phase.

Use this after merging provider changes into `develop` and before promoting
`develop` to `main`.

## Preconditions

- Flux source: `flux-system`
- Provider Kustomization: `capi-provider-ssh`
- Cluster Kustomization: `capi-clusters`
- `kubectl` access to management cluster
- Optional: `flux` CLI (fallback `kubectl` commands are included)

## Phase 0: Baseline Snapshot

Build-up:

```bash
flux -n flux-system get kustomizations
kubectl get clusters,machines -A
kubectl get sshhosts,sshmachines -A
kubectl -n capi-provider-ssh-system get deploy,pods
```

Teardown:
- None needed. Snapshot is read-only.

## Phase 1: Reconcile Source and Provider

Build-up:

```bash
flux -n flux-system reconcile source git flux-system
flux -n flux-system reconcile kustomization capi-provider-ssh --with-source
```

Validation:
- `capi-provider-ssh` Kustomization is `Ready=True`.
- Provider deployment is available.

Teardown:

```bash
# Freeze provider reconciliation if bad manifests were applied
flux -n flux-system suspend kustomization capi-provider-ssh
```

## Phase 2: Unsuspend Cluster Layer

Build-up:

```bash
flux -n flux-system resume kustomization capi-clusters
flux -n flux-system reconcile kustomization capi-clusters --with-source
```

Validation:
- `capi-clusters` Kustomization is `Ready=True`.
- CAPI objects are reconciling.

Teardown:

```bash
# Stop cluster rollout quickly
flux -n flux-system suspend kustomization capi-clusters
```

## Phase 3: Canary Cluster Validation

Build-up:

```bash
# Replace values for your canary
kubectl -n <namespace> get cluster <canary-cluster>
kubectl -n <namespace> get machines -l cluster.x-k8s.io/cluster-name=<canary-cluster>
kubectl -n <namespace> get sshmachines -l cluster.x-k8s.io/cluster-name=<canary-cluster>
```

Validation:
- Control-plane and worker `Machine` objects progress normally.
- `SSHMachine` objects provision and clear failure fields.
- `SSHHost.spec.consumerRef` claims are consistent.

Teardown:

```bash
# Make deletion durable in GitOps before deleting the Cluster object.
#
# Preferred path: remove the canary manifest from Git, push, then reconcile.
# Alternative fast path: suspend capi-clusters if Git change is not immediate.
flux -n flux-system suspend kustomization capi-clusters

# Remove canary cluster resources
kubectl -n <namespace> delete cluster <canary-cluster>

# Verify cleanup (finalizers + host release)
kubectl -n <namespace> get machines,sshmachines
kubectl -n <namespace> get sshhosts -o custom-columns='NAME:.metadata.name,CONSUMER:.spec.consumerRef.name'
```

Git-first durable teardown (preferred):

```bash
# In your Git repo containing capi-clusters manifests:
git rm <path-to-canary-cluster-manifest.yaml>
git commit -m "chore: remove canary cluster after rollout validation"
git push

flux -n flux-system reconcile source git flux-system
flux -n flux-system reconcile kustomization capi-clusters --with-source
```

Expected teardown outcome:
- Canary `Machine`/`SSHMachine` objects are removed.
- Claimed `SSHHost` entries have empty `consumerRef`.

## Phase 4: Promote Full Rollout

Build-up:

```bash
flux -n flux-system reconcile source git flux-system
flux -n flux-system reconcile kustomization capi-provider-ssh --with-source
flux -n flux-system resume kustomization capi-clusters
flux -n flux-system reconcile kustomization capi-clusters --with-source
```

Validation:
- `flux -n flux-system get kustomizations` stays healthy.
- `kubectl get clusters,machines -A` stabilizes without crash loops.
- Provider logs show normal reconcile cadence.

Teardown:

```bash
# Emergency stop
flux -n flux-system suspend kustomization capi-clusters
flux -n flux-system suspend kustomization capi-provider-ssh
```

## kubectl-Only Teardown Equivalents

```bash
kubectl -n flux-system patch kustomization capi-clusters --type=merge \
  -p '{"spec":{"suspend":true}}'
kubectl -n flux-system patch kustomization capi-provider-ssh --type=merge \
  -p '{"spec":{"suspend":true}}'
```
