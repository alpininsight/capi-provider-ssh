# Flux Rollout Step

This runbook makes the CAPI rollout step explicit when Flux-managed
`capi-clusters` are suspended.

For end-to-end rollout validation with teardown/remove actions per phase, see
[live-rollout-validation.md](live-rollout-validation.md).

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

If `flux` CLI is unavailable, use `kubectl`. The same ordering applies —
reconcile source and provider **before** unsuspending the cluster layer:

```bash
# 1) Trigger source + provider reconcile first
kubectl -n flux-system annotate gitrepository flux-system \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
kubectl -n flux-system annotate kustomization capi-provider-ssh \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite

# 2) Wait for provider to be ready
kubectl -n flux-system wait kustomization/capi-provider-ssh \
  --for=condition=Ready --timeout=120s

# 3) Unsuspend cluster layer
kubectl -n flux-system patch kustomization capi-clusters --type=merge \
  -p '{"spec":{"suspend":false}}'
kubectl -n flux-system annotate kustomization capi-clusters \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```

## Verification

Allow up to 2 minutes for CAPI machines to reconcile after unsuspend.

```bash
# Flux status
flux -n flux-system get kustomizations

# CAPI objects and provider inventory
kubectl get clusters,machines -A
kubectl get sshhosts,sshmachines -A

# Provider controller health
kubectl -n capi-provider-ssh-system get deploy,pods

# Wait for machines to reach Running phase (optional)
kubectl wait machines -A --for=jsonpath='{.status.phase}'=Running --timeout=120s
```

## Rollback

```bash
# Stop rollout quickly
flux -n flux-system suspend kustomization capi-clusters

# Reconcile provider layer back to known state if needed
flux -n flux-system reconcile kustomization capi-provider-ssh --with-source
```

If `flux` CLI is unavailable:

```bash
kubectl -n flux-system patch kustomization capi-clusters --type=merge \
  -p '{"spec":{"suspend":true}}'
kubectl -n flux-system annotate kustomization capi-provider-ssh \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```
