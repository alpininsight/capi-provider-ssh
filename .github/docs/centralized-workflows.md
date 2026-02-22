# Centralized Workflows

This document describes the standardized GitHub Actions workflows that all
Alpine Insight repositories should adopt. These workflows are designed to work
consistently across repos with and without branch protection rules.

## Table of Contents

- [Changelog Workflow](#changelog-workflow)
- [GitVersion Configuration](#gitversion-configuration)
- [Required Secrets](#required-secrets)
- [Repository Settings](#repository-settings)

---

## Changelog Workflow

**File:** `.github/workflows/changelog.yml`

Automatically generates `CHANGELOG.md` using [git-cliff](https://git-cliff.org/)
when commits are pushed to the `develop` branch.

### How It Works

1. **Trigger:** Push to `develop` (excluding changes to `CHANGELOG.md` itself)
2. **Generate:** Runs `git-cliff` to produce an updated `CHANGELOG.md`
3. **PR Creation:** Creates (or updates) a PR from `chore/changelog-update` to `develop`
4. **Auto-merge:** Uses `gh pr merge --auto` to let GitHub merge the PR once
   all required checks pass. Falls back to direct merge for repos without
   required checks or without auto-merge enabled.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| PR-based merge (not direct push) | Works with branch protection rules that require PRs |
| `CHANGELOG_BOT_TOKEN` PAT | `GITHUB_TOKEN` cannot merge PRs when branch protection requires reviews or status checks from a different actor |
| `gh pr merge --auto` | Lets GitHub handle check-waiting natively; no fragile polling loops or timeouts |
| `paths-ignore: ['CHANGELOG.md']` | Prevents infinite trigger loops when the changelog PR merges |
| No `[skip ci]` in commit message | Required checks must run on the changelog PR for it to be mergeable |
| `concurrency` group | Prevents race conditions when multiple pushes happen in quick succession |
| Fallback to direct merge | Repos without required checks or auto-merge enabled still work |

### Adapting for Your Repo

The workflow is identical across all repos. No repo-specific customization is
needed. The auto-merge fallback handles the difference between repos with and
without required checks.

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Missing CHANGELOG_BOT_TOKEN secret` error | Secret not configured | Add `CHANGELOG_BOT_TOKEN` in repo Settings > Secrets |
| PR created but not merged | Auto-merge not enabled + required checks exist | Enable "Allow auto-merge" in repo Settings > General |
| `Auto-merge unavailable, attempting direct merge` then fails | Required checks block direct merge | Enable auto-merge in repo settings |
| Changelog not updating | `cliff.toml` missing or misconfigured | Ensure `cliff.toml` exists in repo root |

---

## GitVersion Configuration

**File:** `GitVersion.yml`

All repos use [GitVersion 5.x](https://gitversion.net/) for semantic versioning
based on conventional commits.

### Standard Configuration

```yaml
# GitVersion 5.x Configuration
mode: ContinuousDelivery
tag-prefix: '[vV]?'
next-version: 0.1.0
assembly-versioning-scheme: MajorMinorPatch
commit-message-incrementing: Enabled
major-version-bump-message: '(\+semver:\s?(breaking|major))|^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\(.+\))?!:|BREAKING CHANGE:'
minor-version-bump-message: '(\+semver:\s?(feature|minor))|^feat(\(.+\))?:'
patch-version-bump-message: '(\+semver:\s?(fix|patch))|^(fix|perf)(\(.+\))?:'
no-bump-message: '(\+semver:\s?(skip|none))|^(chore|docs|style|test|ci|build|revert)(\(.+\))?:'
branches:
  main:
    regex: ^main$
    mode: ContinuousDelivery
    tag: ''
    increment: Patch
    prevent-increment-of-merged-branch-version: false  # CRITICAL
    track-merge-target: false
    is-release-branch: true
    is-mainline: true
  develop:
    regex: ^develop$
    mode: ContinuousDelivery
    tag: alpha
    increment: Minor
    prevent-increment-of-merged-branch-version: false
    track-merge-target: true
    is-release-branch: false
    is-mainline: false
  feature:
    regex: ^(feature|feat)[/-]
    mode: ContinuousDelivery
    tag: alpha.{BranchName}
    increment: Inherit
    source-branches: ['develop', 'main']
  hotfix:
    regex: ^hotfix[/-]
    mode: ContinuousDelivery
    tag: beta
    increment: Patch
    source-branches: ['main']
  release:
    regex: ^release[/-]
    mode: ContinuousDelivery
    tag: rc
    increment: None
    source-branches: ['develop']
  ci:
    regex: ^ci[/-]
    mode: ContinuousDelivery
    tag: ci.{BranchName}
    increment: Inherit
    source-branches: ['develop']
  docs:
    regex: ^docs[/-]
    mode: ContinuousDelivery
    tag: docs.{BranchName}
    increment: Inherit
    source-branches: ['develop']
  fix:
    regex: ^fix[/-]
    mode: ContinuousDelivery
    tag: fix.{BranchName}
    increment: Inherit
    source-branches: ['develop']
```

### Critical Setting: `prevent-increment-of-merged-branch-version`

This setting **must be `false`** on the `main` branch. When set to `true`
(the GitVersion default for mainline branches), it causes `feat:` commits
merged from `develop` to `main` to produce **patch** bumps instead of the
correct **minor** bumps.

**Why this happens:** With `true`, GitVersion ignores the commit message-based
increment calculated on the source branch and falls back to the `increment`
setting on `main` (which is `Patch`). Setting it to `false` lets the
conventional commit prefix (`feat:` = minor, `fix:` = patch) flow through
correctly.

### Version Bump Rules

| Commit Prefix | Version Bump | Example |
|---------------|-------------|---------|
| `feat:` | Minor (0.X.0) | `feat(api): add user endpoint` |
| `fix:`, `perf:` | Patch (0.0.X) | `fix(auth): handle expired tokens` |
| `feat!:`, `BREAKING CHANGE:` | Major (X.0.0) | `feat!: redesign auth flow` |
| `chore:`, `docs:`, `ci:`, `test:`, `build:`, `style:`, `revert:` | None | `chore: update deps` |
| `+semver: minor` | Minor (override) | Any commit with `+semver: minor` in body |

---

## Required Secrets

| Secret | Purpose | Required By |
|--------|---------|-------------|
| `CHANGELOG_BOT_TOKEN` | Fine-grained PAT for changelog PR creation and merge | changelog.yml |

### Creating the PAT

1. Go to GitHub Settings > Developer settings > Personal access tokens > Fine-grained tokens
2. Create a token scoped to the `alpininsight` organization
3. **Permissions:** Contents (read/write), Pull requests (read/write), Metadata (read)
4. **Resource access:** Apply to all repos that use the changelog workflow
5. Add as a repository secret named `CHANGELOG_BOT_TOKEN`

### Rotation

- Set a reasonable expiry (e.g., 1 year)
- Document the expiry date and set a calendar reminder
- When rotating, update the secret in all repos simultaneously

---

## Repository Settings

For the changelog workflow to work optimally with branch protection:

1. **Enable "Allow auto-merge"** in repo Settings > General > Pull Requests
   - This allows `gh pr merge --auto` to queue the PR for merge after checks pass
   - Without this, repos with required checks will need the auto-merge fallback

2. **Branch protection on `develop`** (if applicable):
   - The `CHANGELOG_BOT_TOKEN` PAT must belong to a user/app that satisfies
     the branch protection requirements
   - If reviews are required, consider exempting the bot user or using a
     GitHub App with bypass permissions

---

## Adoption Checklist

When adding these workflows to a new repo:

- [ ] Copy `changelog.yml` to `.github/workflows/`
- [ ] Copy `GitVersion.yml` to repo root
- [ ] Ensure `cliff.toml` exists (git-cliff configuration)
- [ ] Add `CHANGELOG_BOT_TOKEN` secret to the repo
- [ ] Enable "Allow auto-merge" in repo settings (recommended)
- [ ] Verify `prevent-increment-of-merged-branch-version: false` on `main` branch
