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

Use an encrypted Secret manifest in Git and let Flux decrypt it at apply time.

- Example: `python/deploy/examples/ssh-key-lifecycle/sops/secret.sops.yaml`
- The manifest shape matches the provider contract (`data.value` by default).

## GitOps Pattern B: External Secrets

Use `ExternalSecret` to materialize the Kubernetes Secret from your central
secret manager.

- Example:
  `python/deploy/examples/ssh-key-lifecycle/external-secrets/externalsecret.yaml`
- The target Secret is created as `type: Opaque` with key `value`.

## Rotation Runbook

1. Create a new versioned key Secret (`ssh-key-YYYYqN`) via SOPS or
   External Secrets.
2. Canary switch one `SSHHost` and one `SSHMachine` to the new Secret.
3. Verify readiness:
   - `SSHHost.status.ready=True` after probe cycle.
   - New or dry-run machine reconciliation succeeds.
4. Roll out to all remaining `SSHHost` and `SSHMachine` objects.
5. Keep the old Secret for a short rollback window, then remove it.

### Example Patches

```bash
# Switch one SSHHost
kubectl -n default patch sshhost host-a --type=merge \
  -p '{"spec":{"sshKeyRef":{"name":"ssh-key-2026q1","key":"value"}}}'

# Switch one SSHMachine
kubectl -n default patch sshmachine cp-0 --type=merge \
  -p '{"spec":{"sshKeyRef":{"name":"ssh-key-2026q1","key":"value"}}}'
```

## Audit Checks

```bash
# Inventory current SSH key refs
kubectl get sshhosts,sshmachines -A -o custom-columns='KIND:.kind,NS:.metadata.namespace,NAME:.metadata.name,KEYSECRET:.spec.sshKeyRef.name,KEYFIELD:.spec.sshKeyRef.key'

# Confirm no plaintext private key manifests under deploy/
rg -n "BEGIN OPENSSH PRIVATE KEY|BEGIN RSA PRIVATE KEY" python/deploy
```

## Rollback

If validation fails:

1. Patch affected `SSHHost` and `SSHMachine` resources back to the previous
   Secret name.
2. Confirm probes/reconciliations are healthy again.
3. Investigate key distribution before retrying rotation.
