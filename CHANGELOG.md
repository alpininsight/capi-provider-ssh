# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Bug Fixes

- **sshmachine:** Support cloud-init bootstrap and timer reconcile
- **sshmachine:** Prevent bootstrap rerun after provisioned 
- **sshmachine:** Serialize reconcile to prevent bootstrap race
- **image:** Run provider module via kopf -m to avoid import errors

### Documentation

- **governance:** Add ITSM and ISO 20000 continuity guidance

### Testing

- Enforce deterministic integration teardown cleanup

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
