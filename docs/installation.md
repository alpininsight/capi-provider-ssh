# Installation and first acceptance

This procedure prepares a reviewed provider installation in a management cluster.
It does not adopt existing VMs or create a workload cluster automatically. For an
isolated evaluation, use the disposable [Kind lifecycle procedure](testing.md)
first. Production placement, registry and credential delivery belong to the
management-platform owner.

## Preconditions

- Select the CAPI/Kubernetes/Python combination from [support](support-matrix.md).
  CAPI core, CABPK and KCP must be installed and healthy before workload creation.
- Select a reviewed source revision and corresponding immutable image digest for
  the target architecture. Verify source labels and publication evidence.
- Provide at least two schedulable nodes for required hostname anti-affinity.
  Physical-host spread and control-plane role affinity are consumer overlays.
- Verify the management API HA endpoint, Pod-to-API access, DNS and the container
  runtime's registry pull path on every eligible placement target.
- Prepare Linux hosts with a reviewed runtime/package baseline, reachable SSH,
  `flock`, and the privileges needed by bootstrap and cleanup commands. The
  validated examples use root; arbitrary sudo-only accounts are not certified.
- Deliver client keys and independently verified host trust as Secrets in the
  resource namespace. Follow [SSH key lifecycle](ssh-key-lifecycle.md).

Inspect the actual cluster before changes, using an explicitly selected kubeconfig:

```bash
: "${MANAGEMENT_KUBECONFIG:?set the reviewed management kubeconfig}"
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" version
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get nodes
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get clusters,machines -A
```

The last command requires installed CAPI CRDs. Record an absent API as a missing
installation prerequisite, not an empty fleet.

## Manifest delivery

[shared/crds](../shared/crds/) contains the provider CRDs.
[python/deploy](../python/deploy/) contains the namespace, RBAC, peering definition,
two-replica Deployment and PDB. Render and review both sets before delivery:

```bash
kubectl kustomize shared/crds
kubectl kustomize python/deploy
```

The base Deployment contains the development image tag. The consumer overlay
must replace it with its accepted `ghcr.io/alpininsight/capi-provider-ssh-python@sha256:…`
pin. Do not deploy the floating base unchanged as an accepted environment.
The repository does not yet provide `metadata.yaml` plus a versioned
`infrastructure-components.yaml` release bundle for `clusterctl init --infrastructure ssh`.

Deliver in this order through the environment's existing manifest owner:

1. Namespace and provider/peering CRDs; wait for each CRD to be Established.
2. ServiceAccount, RBAC and the `ClusterKopfPeering/capi-provider-ssh` object.
3. Deployment and PDB, preserving projected credentials and security settings.
4. Intended host inventory and CAPI workload resources only after controller acceptance.

management-cloud uses ArgoCD and its existing GitOps overlays. The peering CRD
and object contain sync-wave hints. A plain `kubectl apply` does not implement
Argo ordering; a manually managed evaluation must split these stages and wait
explicitly. Do not run a second deployment manager against GitOps-owned objects.

## Acceptance

Require two Ready/Available replicas on distinct eligible nodes, correct image
IDs, stable restart counters and successful exec readiness on **each** replica.
Observe fresh peering heartbeats and one active reconciler. Verify the configured
128 MiB request / 512 MiB limit and actual memory behavior. A higher limit uses
available memory on demand; it is not an autoscaler.

```bash
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n capi-provider-ssh-system \
  get deployment capi-provider-ssh-controller
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n capi-provider-ssh-system \
  get pods -l app.kubernetes.io/component=controller
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get clusterkopfpeerings.kopf.dev capi-provider-ssh
```

Use [operations](operations.md#liveness-readiness-and-the-live-ha-gate) for direct
probe checks. If the consumer installs the read-only namespace auditor, verify
its own image pull and successful execution as a separate gate.

## First workload and recovery

Use a dedicated, disposable host cohort and namespace. Create the full CAPI
Cluster/Machine ownership chain with valid bootstrap data; an isolated
SSHMachine example is not a complete cluster. Require the canary outcomes in
[rollout validation](live-rollout-validation.md) before expanding scope.

If installation or lifecycle acceptance fails, preserve the failing state and
use [troubleshooting](faq.md). Do not widen RBAC, remove finalizers, overwrite
host ownership or disable trust checks to force progress. Uninstall only after
normal workload deletion and claim cleanup; deleting the CRDs first destroys
the state needed for recovery.
