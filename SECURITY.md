# Security policy and trust boundary

## Reporting

Use the repository's **Security → Advisories → Report a vulnerability** option
when available. Private vulnerability reporting was **disabled when checked on
2026-09-07**. Until a private channel is available, open a public issue that only
asks the maintainers for a secure contact; do not include vulnerability details,
proof-of-concept payloads, credentials or affected infrastructure identifiers.
No private email address or response-time commitment is implied by this policy.

Maintainers should establish and verify a private intake channel, acknowledge
reports, assess affected revisions, coordinate remediation and publish an advisory
after the disclosure decision. Enabling GitHub's private reporting is a separate
repository-administration action; this document does not enable it.

Follow [GitHub's private reporting guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

## Supported security scope

The [support matrix](docs/support-matrix.md) identifies tested source/runtime
combinations. This project does not currently publish a separate LTS/backport
schedule, guaranteed patch window or security SLA. A release tag is not a claim
that every distribution, hardware target or deployment has been assessed.

The provider is part of the privileged management plane:

- Its shipped ClusterRole reads Secrets across namespaces. Namespace separation
  alone does not isolate mutually untrusted users from this controller.
- Authors of bootstrap data and SSH credentials can cause privileged commands
  to run on selected hosts. Restrict those writers and controller impersonation.
- Independently verified SSH host keys or host CA entries are required. Never
  bypass a changed key or use an unverified scan as the trust source.
- Host ownership, renewed Leases, remote locking and cleanup finalizers protect
  lifecycle consistency; they are not a sandbox for hostile bootstrap scripts.

See [RBAC](docs/rbac-requirements.md), [architecture](docs/architecture.md) and
[SSH key rotation](docs/ssh-key-lifecycle.md).

## Deployment and evidence handling

Use reviewed immutable image digests and inspect publication provenance/SBOM and
the configured vulnerability scan. Preserve the non-root/read-only filesystem,
projected token and dropped-capability settings in the deployment overlay.
The image's Kubernetes credentials and the SSH target's privileges are distinct.

Keep private keys, API tokens, kubeconfigs, bootstrap Secrets and raw host output
out of Git, public issues and CI artifacts. Diagnostic bundles must be reviewed
and redacted; a generic exception string may still contain sensitive upstream
data. Scope network access to the management API, approved SSH targets and the
registry path required by the container runtime.
