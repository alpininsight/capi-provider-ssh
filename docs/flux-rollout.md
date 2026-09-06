# Historical Flux rollout reference

Flux is retired in management-cloud. Use [live rollout validation](live-rollout-validation.md)
for ArgoCD delivery and [operations](operations.md) for CAPI pause and recovery.

Suspending a GitOps reconciler never stops existing CAPI/provider reconciliation.
Older commands which described Flux suspension as an emergency stop are superseded.
