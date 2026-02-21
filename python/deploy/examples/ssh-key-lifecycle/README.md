# SSH Key Lifecycle Examples

These examples show two GitOps-safe ways to provide SSH keys for
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
