# Maintenance and backport policy

This policy applies to the open source provider. Repository maintainers own
triage and release acceptance; a PR names its change owner and records acceptance
under the current review policy below. The [support matrix](support-matrix.md)
defines tested component and host combinations. Maintenance does not certify
additional platforms or promise an SLA, fixed response time, LTS period or
guaranteed release date.

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
4. Run the required checks on the actual release head and inspect the final diff
   under the current review policy. Backport conflicts require renewed review
   and affected tests; an approval of the original commit does not approve the
   adaptation. Verify
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

The standard policy requires independent approval. On **2026-09-08**, the repository
owner authorized a **temporary single-maintainer exception** for `main` and
`develop`. Peter Rosemann (`@dkdndes`), Alpin Insight Solutions, remains the
administrator and [CODEOWNER](../.github/CODEOWNERS). Ownership and review routing
remain active; a second person's approval is temporarily optional. This applies
equally to provider, dependency, documentation, bot and release PRs.

| Review control | Current temporary policy | Standard policy to restore |
|---|---|---|
| Required approving reviews | 0 | At least 1 independent approval |
| Required CODEOWNER and last-push approval | Disabled | Enabled |
| Extra approval for unattributed changes | Disabled | Enabled |
| Stale-approval dismissal and resolved review threads | Required | Required |
| PR, up-to-date branch and all eight technical checks | Required | Required |
| Administrator/bot bypass or synthetic self-approval | None | None |

The active parameters are in [required-reviews.json](../.github/required-reviews.json);
the [standard profile](../.github/required-reviews-standard.json) preserves the
restoration values. During the exception, the maintainer inspects the final diff,
tests and release evidence. This is owner acceptance, not independent assurance.
Contributors may still provide reviews; requested changes and unresolved threads
must be addressed. Automation cannot supply a human approval.

Restore the standard policy **when a second eligible maintainer is onboarded**,
tracked in [issue #261](https://github.com/alpininsight/capi-provider-ssh/issues/261).
That availability is not planned for September 2026. This is an event-based
transition, with no automatic October 1 switch and no promised hiring date:

1. The repository owner authorizes the second maintainer's write access and adds
   a valid owner entry through a PR. Verify GitHub CODEOWNERS validation on the
   relevant base branches; an entry only in a PR head does not govern that PR.
2. Copy the standard profile into `required-reviews.json` through a PR and update
   the repository ruleset to match. Retain all technical checks, branch protections
   and the main-branch merge-commit requirement.
3. Verify the effective rules on both branches and exercise author-created and
   bot-created PRs: each must wait for a distinct eligible CODEOWNER's approval,
   and a new push must require fresh approval. Record the evidence and end the
   temporary exception in the documentation and tracking issue.

At every maintainer change and before a release, verify private reporting,
CODEOWNERS errors, effective rules and whether the restoration trigger is met.
Do not treat this exception as a permanent change to the standard policy. See
[CI governance](ci-governance.md) for live-rule verification commands.
