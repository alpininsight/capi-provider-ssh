# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Bug Fixes

- **security:** Remediate dependency and workflow risks
- **container:** Exclude transient build tooling
- **ci:** Inspect container metadata as root
- **container:** Remove vulnerable pip tooling
- Fence SSH lifecycle operations and validate provider HA
- **ci:** Validate updated hooks and normalize generated changelog
- **runtime:** Upgrade to Python 3.14 with matching validation
- **health:** Require API and fresh peering for readiness
- **health:** Reduce probe memory and allow controller bursts
- **ci:** Secure merges, route SSH tests and preserve release tags
- **ci:** Tolerate concurrent changelog merge status updates
- Complete lifecycle conditions, package identity and review policy
- Align stable package and image identity with release tags
- **context7:** Index released documentation from main

### CI/CD

- Test private reusable workflow access
- Locate container scan metadata
- Report container vulnerability targets

### Documentation

- Explain CAPI contract migration and current gaps
- Schedule Q4 migration and assess OSS readiness
- **context7:** Register repository-managed provider documentation

### Miscellaneous

- **deps-dev:** Bump ruff in /python in the version-updates group

### Testing

- Cover lifecycle failure boundaries and align operator docs

## [0.4.2] - 2026-08-14

### Bug Fixes

- **ci:** Sync main back into develop after release
- **ci:** Enforce auto-merge for changelog PRs
- **runtime:** Declare Kopf cluster scope

## [0.4.1] - 2026-03-01

### Bug Fixes

- **sshmachine:** Inject kubelet provider-id into bootstrap

## [0.4.0] - 2026-02-26

### Features

- **api:** Add SSHClusterTemplate CRD for ClusterClass
- **sshmachine:** Add bootstrap check strategy enum

### Styling

- Apply ruff formatting for bootstrap strategy changes

## [0.3.20] - 2026-02-25

### Bug Fixes

- **sshmachine:** Keep ready in every provisioned reconcile patch

## [0.3.19] - 2026-02-25

### Bug Fixes

- **sshmachine:** Persist ready ownership for provisioned machines
- **ci:** Satisfy ruff line-length for #196

## [0.3.18] - 2026-02-25

### Bug Fixes

- **sshmachine:** Backfill providerID and ready on provisioned machines

## [0.3.17] - 2026-02-25

### Bug Fixes

- Persist stale SSHHost claim clearing and document Lima reprovision

### Testing

- Allow route-dependent unreachable-host failures

## [0.3.16] - 2026-02-25

### Documentation

- **roadmap:** Add dev substrate provisioning objective

### Styling

- Apply ruff format for teardown test

### Testing

- **e2e:** Add SSH e2e tests against real target
- Enforce machine-first teardown ordering
- Expand E2E ssh key path before existence check

## [0.3.15] - 2026-02-24

### Bug Fixes

- **sshmachine:** Gate ready on kubelet post-bootstrap checks

## [0.3.14] - 2026-02-24

### Bug Fixes

- **sshmachine:** Classify bootstrap failure phases

## [0.3.13] - 2026-02-24

### Bug Fixes

- Skip stale SSHMachine reconcile events by UID

## [0.3.12] - 2026-02-24

### Bug Fixes

- Add host-side bootstrap sentinel guard

## [0.3.11] - 2026-02-24

### Bug Fixes

- Re-read live SSHMachine state before bootstrap

## [0.3.10] - 2026-02-24

### Bug Fixes

- Stabilize distributed lock holder identity across restarts

## [0.3.9] - 2026-02-24

### Miscellaneous

- Merge main into develop for release convergence

## [0.3.8] - 2026-02-24

### Release

- Promote develop to main

## [0.3.4] - 2026-02-23

### Release

- Promote develop to main

## [0.3.2] - 2026-02-23

### Bug Fixes

- **sshmachine:** Support cloud-init bootstrap and timer reconcile
- **sshmachine:** Prevent bootstrap rerun after provisioned
- **sshmachine:** Serialize reconcile to prevent bootstrap race
- **image:** Run provider module via kopf -m to avoid import errors
- **sshmachine:** Block stale timer/handler bootstrap reruns
- Prevent cross-pod concurrent SSHMachine bootstrap

### Documentation

- **governance:** Add ITSM and ISO 20000 continuity guidance

### Miscellaneous

- Sync main into develop for release PR mergeability

### Testing

- Enforce deterministic integration teardown cleanup

## [0.3.1] - 2026-02-23

### Release

- Python CAPI provider implementation and operational docs
- CAPI contract compliance and CI fixes
- V0.4.0 — CAPI contract compliance, CI guards, and docs

## [0.2.0] - 2026-02-21

### Bug Fixes

- **python:** Enable kopf liveness endpoint for probes
- **python:** Harden runtime startup and add SSHCluster unit tests
- **python:** Keep liveness enabled in hardened entrypoint
- **python:** Harden runtime startup by removing uv run from ENTRYPOINT
- **ci:** Address PR feedback and stabilize workflow checks
- **python:** Make package README available in docker build context
- **ci:** Unblock Docker build and publish on internal PRs
- **test:** Assert SSHCluster deletion succeeds after retry loop
- **test:** Resolve ruff lint and format issues in integration tests
- **crds:** Use additionalPrinterColumns instead of printcolumns
- **deploy:** Harden deployment for Gatekeeper compliance and kind e2e
- **docker:** Copy source before uv sync so package is installed
- **python:** Switch to flat layout for Python 3.14 compatibility
- **docker:** Copy source before uv sync so package is installed
- **ci:** Update CI paths for flat layout and resolve merge conflict
- **python:** Allow controller CRD discovery in RBAC
- **python:** Harden SSHHost claim and release semantics
- **python:** Requeue reboot remediation until machine is ready
- **python:** Prioritize unknown hosts and clear dry-run failures
- **flux:** Add explicit Flux rollout unsuspend step
- **docs:** Add provider-first ordering to kubectl fallback in flux runbook
- **ci:** Self-sufficient container tagging with GitVersion and OCI labels
- **ci:** Guard semver tag on main against no-bump commits
- **ci:** Prevent release image loss from concurrency cancellation
- **ci:** Inherit version bumps from develop on main merge
- **ci:** Sync changelog workflow from canonical template
- **capi:** Add status.ready, RBAC aggregation, and CRD contract labels
- **ci:** Add workflow_dispatch and branch guard for releases
- **ci:** Replace branch guard with canonical org template
- **ci:** Expand branch guard to all conventional commit prefixes
- **ssh:** Use asyncio.wait_for for asyncssh operations

### Documentation

- **security:** Add ssh key lifecycle runbook
- **roadmap:** Replace vendor-centric plugin taxonomy with protocol-based design
- Add FAQ covering RBAC, cleanup, health probing, and image tags
- **operations:** Add live rollout validation and teardown runbook
- **flux:** Make canary teardown GitOps-safe
- **operations:** Add DNS cutover runbook
- **faq:** Add staging-to-production DNS swap guidance
- Add RBAC requirements and external etcd contract documentation
- **external-etcd:** Fix missing ClusterConfiguration behavior description
- Fix minor documentation inaccuracies
- **external-etcd:** Fix apiVersion to match served v1beta1 contract

### Features

- **python:** Scaffold kopf controller with pyproject.toml
- **python:** Implement SSHCluster controller
- **python:** Implement SSH client wrapper
- **python:** Implement SSHMachine controller
- **ci:** Split #12 into CI and container workflows
- **crds:** Add SSHHost CRD for Metal3-style host inventory
- **python:** Add external etcd wiring and reboot remediation
- **python:** Add dry-run mode, SSHHost health probing, and docs
- **docs:** Add CI, release, and license badges to README

### Miscellaneous

- Add DCO and update README with contributing guidelines
- Remove AI references and update .gitignore
- **repo:** Add pre-commit config and conventional commit hook
- **gitignore:** Ignore coverage artifact
- Merge main back into develop to resolve divergence

### Styling

- Format sshmachine.py for ruff compliance
- **python:** Format sshmachine controller with ruff

### Testing

- **python:** Add unit tests for all controllers and SSH client
- **python:** Add runtime startup regression guard
- **python:** Add integration tests for SSHCluster and SSHMachine

### Release

- Python CAPI provider implementation and operational docs
- Merge develop into main

## [0.1.0] - 2026-02-20

### Miscellaneous

- Initialize repository with shared CRDs and project structure
- Add CI workflows, license, and project docs

---
*Generated by [git-cliff](https://git-cliff.org/)*
