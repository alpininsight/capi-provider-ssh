# Flux Rollout Step

This runbook makes the CAPI rollout step explicit when Flux-managed
`capi-clusters` are suspended.

## Preconditions

Run this only after the provider blockers are closed in `develop`:

- RBAC includes CRD discovery (`apiextensions.k8s.io/customresourcedefinitions`)
- Multi-host allocation is active for control plane replicas
- SSHMachine delete/finalizer flow is validated

## Rollout (Unsuspend)

```bash
# 1) Refresh Git source and provider layer first
flux -n flux-system reconcile source git flux-system
flux -n flux-system reconcile kustomization capi-provider-ssh --with-source

# 2) Unsuspend cluster layer
flux -n flux-system resume kustomization capi-clusters

# 3) Reconcile immediately
flux -n flux-system reconcile kustomization capi-clusters --with-source
```

If `flux` CLI is unavailable, use `kubectl`:

```bash
kubectl -n flux-system patch kustomization capi-clusters --type=merge \
  -p '{"spec":{"suspend":false}}'
kubectl -n flux-system annotate kustomization capi-clusters \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```

## Verification

```bash
# Flux status
flux -n flux-system get kustomizations

# CAPI objects and provider inventory
kubectl get clusters,machines -A
kubectl get sshhosts,sshmachines -A

# Provider controller health
kubectl -n capi-provider-ssh-system get deploy,pods
```

## Rollback

```bash
# Stop rollout quickly
flux -n flux-system suspend kustomization capi-clusters

# Reconcile provider layer back to known state if needed
flux -n flux-system reconcile kustomization capi-provider-ssh --with-source
```
