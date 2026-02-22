# RBAC Permission Requirements

The capi-provider-ssh controller requires a set of Kubernetes RBAC permissions
to reconcile its custom resources, interact with CAPI owner objects, and manage
operator state. This document describes the permission contract so that
consumers know what to grant -- it is not intended as a copy-paste RBAC YAML.

The reference implementation is in
[python/deploy/rbac.yaml](../python/deploy/rbac.yaml).

## Permission Table

### Provider CRDs

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `infrastructure.alpininsight.ai` | sshclusters, sshhosts, sshmachines, sshmachinetemplates | get, list, watch, create, update, patch, delete | Reconcile owned resources |
| `infrastructure.alpininsight.ai` | sshclusters/status, sshhosts/status, sshmachines/status | get, update, patch | Update status subresources |
| `infrastructure.alpininsight.ai` | sshclusters/finalizers, sshmachines/finalizers | update | Manage cleanup finalizers |

### CAPI Owner Resources

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `cluster.x-k8s.io` | clusters, machines | get, list, watch | Read ownerRef chain and bootstrap data references |

### CRD Discovery

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `apiextensions.k8s.io` | customresourcedefinitions | get, list, watch | Kopf dynamic watch setup (see [FAQ](faq.md#rbac-does-the-example-rbac-include-crd-permissions-for-kopf)) |

Without these permissions Kopf logs `403 Forbidden` errors during CRD
discovery and may fail to reconcile resources.

### Core Resources

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `""` (core) | secrets | get, list, watch | Read SSH private keys, bootstrap data, and etcd certificate Secrets |
| `""` (core) | events | create, patch | Emit Kubernetes events on reconcile actions |
| `""` (core) | configmaps | get, list, watch, create, update, patch | Kopf internal state storage |

### Leader Election

| API Group | Resources | Verbs | Purpose |
|-----------|-----------|-------|---------|
| `coordination.k8s.io` | leases | get, list, watch, create, update, patch, delete | Kopf leader election for HA deployments |

## Notes

- The controller is **read-only** for CAPI resources (`cluster.x-k8s.io`) and
  Secrets. It never creates or modifies Secrets, Clusters, or Machines.
- ConfigMap and Lease permissions are required by Kopf's internal machinery,
  not by provider-specific logic.
- If you customize the RBAC, keep the `apiextensions.k8s.io` rule -- dropping
  it causes silent failures during startup.
