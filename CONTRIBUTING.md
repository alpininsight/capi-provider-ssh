# Contributing

Start with [development](DEVELOPMENT.md) and the [test portfolio](docs/testing.md).
Changes to lifecycle behavior must preserve the ownership, pause, trust and
recovery contracts in [operations](docs/operations.md).

## Workflow

1. Inspect `git status` and current repository instructions. Preserve unrelated
   changes; use a dedicated worktree when necessary.
2. Fetch `origin/develop` and create a `<type>/<description>` branch from it.
   Do not commit directly to `main` or `develop`.
3. Reproduce the defect or define the intended contract. Add tests for meaningful
   failure boundaries, not assertions that merely duplicate the implementation.
4. Update the relevant reference and runbook with the code. Validate examples,
   local links, supported versions and recovery instructions.
5. Run locked tests, Ruff and all configured hooks. Run the explicit lifecycle
   lane for lifecycle, runtime or dependency changes and inspect CI evidence.
6. Commit with a Conventional Commit message and DCO sign-off (`git commit -s`).
   Open a PR targeting `develop`; state the problem, changed behavior, checks,
   limitations and deployment implications.

## Review acceptance

Review the current PR head, not an earlier green run. Required evidence includes
the configured Python matrix, hooks, structural manifests, image validation and
CAPI lifecycle/failover checks. A cancelled or skipped required lane is not a pass.
The actual repository rules and completed checks must be inspected before merge;
an auto-merge setting by itself is not a quality gate.

For documentation, cross-check cleanup ordering, persisted field names, RBAC
verbs and defaults against source. Mark proposals and historical evidence
explicitly. Keep operational credentials, private inventories, generated reports,
local approval files and machine-specific runtime state out of the repository.

All required checks and resolved review threads remain mandatory. During the
temporary single-maintainer exception, Peter Rosemann (`@dkdndes`), Alpin Insight
Solutions, records owner acceptance; independent approval becomes mandatory again
when a second eligible maintainer is onboarded. Bot-generated PRs follow the same
active policy. See [CI governance](docs/ci-governance.md) and
[maintenance/backports](docs/maintenance-policy.md).

## After merge

The change owner records the merged source, final checks and delivery boundary
in the PR follow-up and [merge review log](docs/merge-reviews.md). Identify any
failure that escaped review, its cause, a concrete preventive action and its
owner. Inspect replacement runs when a changelog merge cancels earlier CI.

Source merge, image publication and consumer rollout are separate outcomes.
Detailed environment evidence belongs in the access-controlled consumer record;
public documentation should retain aggregate product findings and source links.
See [release and delivery](docs/release-process.md).

Security reports follow [SECURITY.md](SECURITY.md). Do not put exploit details
or credentials in a public bug report.
