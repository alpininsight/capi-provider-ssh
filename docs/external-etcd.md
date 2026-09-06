# External Etcd Configuration

The SSHMachine resource supports optional external etcd wiring via
`spec.externalEtcd`. When configured, the controller:

1. Reads etcd CA, client certificate, and client key from Kubernetes Secrets
2. Stages certificates privately and installs them under the remote operation lock
3. Patches the kubeadm `ClusterConfiguration` in the bootstrap data with
   `etcd.external` and version-correct API server arguments pointing to the external etcd cluster

This is useful when the etcd cluster is managed separately from the Kubernetes
control plane (for example, a dedicated etcd cluster on bare-metal nodes).

## Configuration Fields

All fields live under `spec.externalEtcd` on the SSHMachine resource.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `endpoints` | `string[]` | Yes | List of etcd endpoints (e.g., `https://10.0.0.10:2379`) |
| `caCertRef` | `{name, key}` | Yes | Secret reference for the CA certificate |
| `clientCertRef` | `{name, key}` | Yes | Secret reference for the client certificate |
| `clientKeyRef` | `{name, key}` | Yes | Secret reference for the client private key |
| `files` | `object` | No | Override target paths on the host (see below) |

Each Secret reference requires a `name` field (the Secret name in the same
namespace). The `key` field defaults to `"value"` if omitted.

## Secret Format

All certificate material must be PEM-encoded. The controller reads the
specified key from each referenced Secret.

| Field | Secret Name | Key (default) | Content |
|-------|------------|---------------|---------|
| CA certificate | `caCertRef.name` | `value` | CA cert that signed etcd server certificates |
| Client certificate | `clientCertRef.name` | `value` | Client cert for API server to etcd authentication |
| Client key | `clientKeyRef.name` | `value` | Private key matching the client certificate |

## File Placement on Target Host

The controller uploads certificate material and sets permissions:

| File | Default Path | Permissions |
|------|-------------|-------------|
| CA cert | `/etc/kubernetes/pki/etcd-external/ca.crt` | 0644 |
| Client cert | `/etc/kubernetes/pki/etcd-external/client.crt` | 0644 |
| Client key | `/etc/kubernetes/pki/etcd-external/client.key` | 0600 |

Override paths via `spec.externalEtcd.files`:

| Field | Default |
|-------|---------|
| `files.caFile` | `/etc/kubernetes/pki/etcd-external/ca.crt` |
| `files.certFile` | `/etc/kubernetes/pki/etcd-external/client.crt` |
| `files.keyFile` | `/etc/kubernetes/pki/etcd-external/client.key` |

All paths must be absolute.

## Kubeadm Injection

The controller patches `ClusterConfiguration` documents found in the bootstrap
data Secret with the following `apiServer.extraArgs`:

| Argument | Value |
|----------|-------|
| `etcd-servers` | Comma-joined `endpoints` list |
| `etcd-cafile` | Target path of CA cert |
| `etcd-certfile` | Target path of client cert |
| `etcd-keyfile` | Target path of client key |

This patching happens in-memory before the bootstrap script is uploaded. The
original bootstrap Secret is not modified.

The same external etcd endpoints and certificate paths must also be declared in
`KubeadmControlPlane.spec.kubeadmConfigSpec.clusterConfiguration.etcd.external`
or the owning `KubeadmConfig`. Otherwise KCP would still assume stacked etcd.
Follow the [upstream CAPI external-etcd contract](https://cluster-api.sigs.k8s.io/tasks/external-etcd)
for the cluster CA/client Secrets; SSH certificate delivery does not replace it.

For initial control-plane bootstrap the provider writes `etcd.external` and
removes any conflicting local-etcd configuration. `v1beta3` arguments are maps;
`v1beta4` arguments are lists of name/value pairs. Unrelated repeated arguments
are preserved. A control-plane `JoinConfiguration` uses the existing cluster's
configuration and still receives the certificates. A worker-only join or an
unrecognized kubeadm API with externalEtcd configured is rejected.

## Example

```yaml
apiVersion: infrastructure.alpininsight.ai/v1beta1
kind: SSHMachine
metadata:
  name: cp-0
  namespace: default
spec:
  address: 10.0.0.20
  port: 22
  user: root
  sshKeyRef:
    name: ssh-key
  sshHostKeyRef:
    name: verified-ssh-hosts
  externalEtcd:
    endpoints:
      - https://10.0.0.10:2379
      - https://10.0.0.11:2379
      - https://10.0.0.12:2379
    caCertRef:
      name: etcd-ca
    clientCertRef:
      name: etcd-client-cert
    clientKeyRef:
      name: etcd-client-key
    files:
      caFile: /etc/kubernetes/pki/etcd-external/ca.crt
      certFile: /etc/kubernetes/pki/etcd-external/client.crt
      keyFile: /etc/kubernetes/pki/etcd-external/client.key
```

All Secrets must exist in the SSHMachine namespace. The external-etcd Secrets
contain PEM-encoded certificate/key material under `value` (or the custom key
specified in the ref). The separate SSH client key and verified host-trust
Secrets follow the [SSH trust contract](operations.md#ssh-trust-and-existing-installations).
