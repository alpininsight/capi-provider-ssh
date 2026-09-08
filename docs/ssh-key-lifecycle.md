# SSH Key Lifecycle

This runbook defines a GitOps-safe lifecycle for SSH keys used by
`SSHHost.spec.sshKeyRef` and `SSHMachine.spec.sshKeyRef`.

## Secret Contract

- The controller reads the private key from `spec.sshKeyRef.name`.
- The Secret data key defaults to `value`; override with `spec.sshKeyRef.key`.
- Use versioned Secret names (for example `ssh-key-2026q1`) to make rotation
  explicit and auditable.
- Do not commit plaintext private keys to Git. Use either:
  - SOPS-encrypted Secret manifests.
  - External Secrets syncing from an external secret manager.

## GitOps Pattern A: SOPS

Use an encrypted Secret manifest with the environment's reviewed decryption integration.
management-cloud uses ArgoCD; SOPS decryption requires an explicitly configured
integration and is not a built-in capability of this provider. The checked-in
SOPS example is a template, not deployable encrypted credential material.

- Example: `python/deploy/examples/ssh-key-lifecycle/sops/secret.sops.yaml`
- The manifest shape matches the provider contract (`data.value` by default).

## GitOps Pattern B: External Secrets

Use `ExternalSecret` to materialize the Kubernetes Secret from your central
secret manager.

- Example:
  `python/deploy/examples/ssh-key-lifecycle/external-secrets/externalsecret.yaml`
- The target Secret is created as `type: Opaque` with key `value`.

## Rotation Runbook

1. Install the new public client key on the selected host through the trusted
   host-management process, retaining the old key during the rotation window.
   Create a new versioned key Secret (`ssh-key-YYYYqN`) via SOPS or
   External Secrets.
2. Switch one selected `SSHHost` in pool mode, or one direct `SSHMachine`,
   through GitOps to the new Secret. Allocated pool Machines refresh credential
   references from their original host; do not change the allocation identity.
3. Verify readiness:
   - `SSHHost.status.ready=True` after probe cycle.
   - New or dry-run machine reconciliation succeeds.
4. Roll out to all remaining `SSHHost` and `SSHMachine` objects.
5. Keep the old Secret for a short rollback window, then remove it.

### Illustrative resource patches

Update the GitOps source for managed objects. These imperative examples are
only for an explicitly managed canary, and require the reviewed kubeconfig.

```bash
# Switch one SSHHost
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n "$NAMESPACE" patch sshhost host-a --type=merge \
  -p '{"spec":{"sshKeyRef":{"name":"ssh-key-2026q1","key":"value"}}}'

# Switch one SSHMachine
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n "$NAMESPACE" patch sshmachine cp-0 --type=merge \
  -p '{"spec":{"sshKeyRef":{"name":"ssh-key-2026q1","key":"value"}}}'
```

## Audit Checks

```bash
# Inventory current SSH key refs
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" get sshhosts,sshmachines -A -o custom-columns='KIND:.kind,NS:.metadata.namespace,NAME:.metadata.name,KEYSECRET:.spec.sshKeyRef.name,KEYFIELD:.spec.sshKeyRef.key'

# Confirm no plaintext private key manifests under deploy/
rg -n "BEGIN OPENSSH PRIVATE KEY|BEGIN RSA PRIVATE KEY" python/deploy
```

## Rollback

If validation fails:

1. Patch affected `SSHHost` and `SSHMachine` resources back to the previous
   Secret name.
2. Confirm probes/reconciliations are healthy again.
3. Investigate key distribution before retrying rotation.

## Independent server identity

Client authentication and server identity are separate Secrets. Every direct
SSHMachine or selected SSHHost must also reference `sshHostKeyRef`; the default
Secret data key is `known_hosts`. Create `verified-ssh-hosts` in the same namespace
from independently verified OpenSSH entries before applying the examples:

```bash
kubectl --kubeconfig "$MANAGEMENT_KUBECONFIG" -n "$NAMESPACE" create secret generic verified-ssh-hosts \
  --from-file=known_hosts=./independently-verified-known_hosts
```

The file must come from a trusted provisioning/console channel. A scan of the
same untrusted SSH endpoint is insufficient. Keep private keys and trust material
out of plain Git; use the existing encrypted/External Secrets delivery path.
See [operations](operations.md) for rotation and legacy ownership migration.
