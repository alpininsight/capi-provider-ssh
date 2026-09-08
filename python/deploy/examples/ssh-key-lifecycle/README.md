# SSH Key Lifecycle Examples

These are templates, not deployable credentials. Replace the example backend/
encryption metadata through the environment's reviewed secret-delivery process.
Never commit a real plaintext/base64 private key. ArgoCD needs an explicit SOPS
integration; this provider does not decrypt Git content.

The examples illustrate two ways to provide SSH keys for
`SSHHost.spec.sshKeyRef` and `SSHMachine.spec.sshKeyRef`.

- `sops/secret.sops.yaml`: SOPS-managed Kubernetes Secret in Git.
- `external-secrets/externalsecret.yaml`: External Secrets sync from a central
  secret manager into a Kubernetes Secret.

Both examples create or reference a Secret with this shape:

```yaml
apiVersion: v1
kind: Secret
type: Opaque
data:
  value: <base64-encoded-private-key>
```

The provider reads `value` by default. If you use another key name, set
`spec.sshKeyRef.key` accordingly.

Also supply independently verified `sshHostKeyRef` trust in the same namespace.
Follow the [key lifecycle runbook](../../../../docs/ssh-key-lifecycle.md) for
host-side authorization, canary rotation and recovery.
