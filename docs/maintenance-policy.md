# Maintenance and backport policy

This policy applies to the open source provider. Repository maintainers own
triage and release acceptance; a PR names its change owner and independent
reviewer. The [support matrix](support-matrix.md) defines tested component and
host combinations. Maintenance does not certify additional platforms or promise
an SLA, fixed response time, LTS period or guaranteed release date.

## Supported releases

| Release line | Maintenance |
|---|---|
| Latest stable minor, currently **0.4.x** | Security fixes and compatibility-preserving corrections are considered on a best-effort basis; install the latest patch in the line |
| Older stable minors, currently 0.3.x and earlier | No routine backports; upgrade to the supported line |
| `develop`, alpha/beta/RC and branch images | Integration and evaluation; no stable-support or backport commitment |
| Future stable minor | Becomes the maintained line when its stable release and validated upgrade guidance are published; the superseded line then leaves routine maintenance |

A release PR must update this table when the maintained minor changes and clearly
state the transition in release notes. Deprecations, migration prerequisites and
any exceptional extension of support require a reviewed record before the
release. Do not infer maintenance from a retained Git tag or registry image.

## Triage and fix selection

Security reports go through the [private channel](../SECURITY.md). Maintainers
record affected and unaffected versions, impact, reproduction, owner and intended
fixed version in the private advisory. Public correctness reports use issues with
sanitized object/status evidence and version identifiers.

A patch candidate must be limited to the demonstrated defect and necessary tests.
Prefer a minimal fix over a dependency major upgrade or unrelated refactor.
Assess CRD/schema compatibility, persisted ownership and receipts, pause,
quarantine, bootstrap/reboot replay and downgrade risks. A schema/behavior change
that cannot safely run on the supported line belongs in an explicit migration
release; do not disguise it as a compatible security patch.

## Backport and release procedure

1. Reproduce the defect on the supported stable source and `develop`. Record which
   versions are affected and why a backport is needed. An older unsupported minor
   does not receive an implied backport commitment.
2. Create a work branch from current `origin/develop`; carry the fix and regression
   test through a PR to `develop`. Reference the original fix/advisory and describe
   any adaptation for the supported line. Private security work stays in the
   advisory's temporary private fork until the coordinated publication decision.
3. Use the existing protected **`develop` → `main`** release PR. The branch guard
   does not support direct hotfix PRs into `main` or a `support/*` publication lane.
   Before a stable patch, keep `develop` compatible with that stable minor. If it
   already contains incompatible unreleased work, remove that work through
   separately reviewed revert PRs, release the minimal stable fix, then restore
   the deferred feature through a new reviewed PR. Never merge a breaking change
   merely to get a security fix onto the stable line.
4. Run the required checks on the actual release head and independently review
   the final diff. Backport conflicts require renewed review and affected tests;
   an approval of the original commit does not approve the adaptation. Verify
   GitVersion's selected patch version, package/OCI identity and release notes.
5. Publish through the existing workflows, then verify source tag, image digest,
   package metadata, scan and provenance. Coordinate the advisory/fixed-version
   publication. Consumer rollout follows its own GitOps review and canary gates.
6. Record escaped defects and process lessons in the [merge review log](merge-reviews.md).

Maintaining multiple stable minors would require a separately reviewed branch,
protection, CI and publication design. This policy does not promise that currently
unimplemented route. Urgency does not authorize direct protected-branch commits,
review bypasses or removal of lifecycle finalizers.

## Independent review and continuity

`main` and `develop` require at least one approving review, code-owner approval,
dismissal of stale approvals, approval of the last push by a different actor,
resolved review threads and all eight strict checks. These requirements also
apply to bot, dependency, documentation and release PRs. A bot can queue
GitHub auto-merge; it cannot supply the independent approval.

The [CODEOWNERS](../.github/CODEOWNERS) file must resolve to actors with write
access. The previously listed `@alpininsight/sre` team did not resolve in GitHub's
validation. Peter Rosemann (`@dkdndes`), Alpin Insight Solutions, is the verified
existing repository administrator; naming that account does not add a second
maintainer. An administrator-authored PR still
needs a separately authorized eligible reviewer/code owner. If none is available,
the PR remains blocked; no emergency self-approval or bot substitution is defined.

At a maintainer change and before a release, check private reporting availability,
GitHub CODEOWNERS errors, effective branch rules and reviewer availability. Access
and team membership changes require the repository owner's authorization. See
[CI governance](ci-governance.md) for the live-rule verification commands.
