# CI routing and merge acceptance

The public provider uses GitHub-hosted runners. The organization notebook pool
is restricted to private repositories and is not an execution target for this
repository. External SSH E2E uses `ubuntu-24.04`; standard quality and build lanes
keep their existing GitHub-hosted runners.

## Required checks

[.github/required-checks.json](../.github/required-checks.json) contains the exact
PR check names and the GitHub Actions integration ID. The active repository
[main/develop ruleset](https://github.com/alpininsight/capi-provider-ssh/rules/13020318)
requires these checks against an up-to-date branch, with no bypass actors.
Organization PR, force-push and main-branch merge-method rules still apply.

The image validation and version jobs are required. Image publication is a
post-merge gate and intentionally is not a required PR job, because publication
is skipped for PRs. The scheduled external SSH lane is separate from the PR
suite. Missing target credentials cannot stand in for a completed external test.

When changing a check name or matrix, update the JSON and repository rule
together. The contract test derives current PR job names from the workflows and
fails when they differ from the checked-in list. Re-read effective rules after
an administration change; a JSON file alone does not configure GitHub.

## Changelog automation

The bot pushes its generated branch with an explicit force-with-lease expectation.
[merge_changelog.py](../python/scripts/merge_changelog.py) then:

1. Requires the expected commit, the same repository, the generated branch and
   `develop` target; the PR must change only `CHANGELOG.md`.
2. Waits for all required checks from the expected GitHub integration and commit.
   Missing or pending checks wait; unsuccessful, cancelled, skipped and neutral
   required checks cannot authorize a merge.
3. Rechecks the head, base and merge eligibility after collecting the evidence.
   A changed head, outdated branch or conflict requires a new reviewed run.
4. Uses a regular squash merge guarded by `--match-head-commit`. GitHub's strict
   rules remain the final gate for races; there is no administrator bypass or
   fallback after a rejected merge.

A concurrent GitHub auto-merge or maintainer merge can briefly leave a blocked
PR snapshot while its merged status settles. For a closed, outdated or conflicting
snapshot, the helper waits at most five seconds and re-reads once before reporting
failure. The expected head and repository/branch identity are validated again;
a still-blocked PR fails. This retries only observation, never the merge request.

The central private changelog workflow was compared during this correction. This
public implementation additionally enforces the completed-check wait above;
the central workflow's auto-merge/direct-merge behavior is not sufficient by
itself when required repository checks are missing.

Final develop CI and publication still require verification after a merge. If
concurrency replaces an earlier run, inspect the accepted replacement and its
source changes as described in [release delivery](release-process.md).

## External SSH test configuration

An approved disposable SSH target must be reachable from the hosted runner and
permit the test identity to execute commands and create/remove `/tmp/capi-e2e-*`
test files. The lane performs transport and stub-script tests, not real kubeadm
bootstrap. Do not substitute an unrelated production administrator credential.

Repository configuration:

| Setting | Purpose |
|---|---|
| Variable `E2E_SSH_HOST` | Explicit approved test endpoint; no hardcoded fallback |
| Optional variables `E2E_SSH_PORT`, `E2E_SSH_USER` | Defaults: port 22, user root; a restricted test account is preferable |
| Secret `E2E_SSH_PRIVATE_KEY` | Dedicated test identity private key |
| Secret `E2E_SSH_KNOWN_HOSTS` | Independently verified target host key or host CA trust |

The workflow validates configuration before checkout, reports missing setting
names without their values, uses private files in `runner.temp` and always
removes those files. Missing configuration fails explicitly. It does not enable
public access to the shared notebook runner group or bypass SSH host trust.

For verification, dispatch **E2E SSH Tests** on the reviewed branch and inspect
the actual runner, preflight and test result. A runner starting the job proves
routing only; the complete external test must also pass before claiming endpoint
coverage.

Sources: [GitHub runner-group access](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access),
[rulesets and required checks](https://docs.github.com/en/rest/repos/rules),
[merge commit matching](https://cli.github.com/manual/gh_pr_merge).
