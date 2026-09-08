# Security policy and trust boundary

## Reporting

Report security findings privately using
[**Report a vulnerability**](https://github.com/alpininsight/capi-provider-ssh/security/advisories/new).
GitHub private vulnerability reporting was enabled and its API setting verified
on **2026-09-08**. Repository administrators are responsible for this inbox;
`@dkdndes` is the currently verified administrator. A GitHub account is required.
Do not open a public issue with exploit details or affected infrastructure data.

Include the affected provider version/source SHA, the impact and a minimal
sanitized reproduction. Include component versions and relevant condition/reason
values when useful. Do not send production credentials, private keys, kubeconfigs
or raw bootstrap Secrets. Discuss any necessary sensitive evidence in the private
advisory before sharing it.

A maintainer acknowledges the report when triaged, assigns an owner, checks
supported/affected versions, agrees communication and disclosure with the
reporter, prepares a reviewed fix and coordinates the advisory with the fixed
release. Contributors are credited only with their consent. There is no guaranteed
response time, bounty or private email address. If the GitHub form is unavailable,
a public issue may request restoration of the private channel **without details**;
it is not a substitute disclosure channel.

See [GitHub's reporting guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

## Supported security scope

The [maintenance and backport policy](docs/maintenance-policy.md) maintains the
latest stable minor, currently **0.4.x**, on a best-effort basis. Older minors have
no routine backports. The [support matrix](docs/support-matrix.md) identifies the
tested source/runtime combinations. No LTS duration, patch deadline or security
SLA is promised. A release tag does not certify every distribution or host.

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
