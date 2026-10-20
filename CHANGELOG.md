# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Bug Fixes

- **lease:** Keep the Lease duration an integer and make renewal cadence its own setting
- **release:** Preserve stable changelog boundaries and promotion metadata

### Documentation

- **provider:** Correct ownership, release boundaries and clusterctl roadmap
- **release:** Keep maintenance scope valid after the next minor promotion


### Miscellaneous

- **license:** Convert to Apache-2.0 with NOTICE

## [0.4.8](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.8) - 2026-09-27

Source: [v0.4.8](https://github.com/alpininsight/capi-provider-ssh/tree/508ad173c286c1e8d1ebc41adc83f406b4a5db78)

### Bug Fixes

- **container:** Apply scoped Debian security updates
- **license:** Let automated license detection recognise MPL-2.0

### Documentation

- Clarify provider use and delivery
- **readme:** Lead with the problem the provider solves


### Miscellaneous

- **deps-dev:** Bump ruff in /python in the version-updates group
- **deps-dev:** Bump ruff in /python in the version-updates group

### Testing

- Diagnose CAPI lifecycle clone races

## [0.4.7](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.7) - 2026-09-09

Source: [v0.4.7](https://github.com/alpininsight/capi-provider-ssh/tree/1bf69c80d68f2d0ba30c22bc19090b114bbc0dc3)

### Bug Fixes

- **controller:** Protect bootstrap errors and isolate Kubernetes API I/O


## [0.4.6](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.6) - 2026-09-08

Source: [v0.4.6](https://github.com/alpininsight/capi-provider-ssh/tree/cc4895e4a75a8fdde89c8c31f7f6463c671ee8e8)

### Bug Fixes

- **context7:** Index released documentation from main
- **context7:** Align main publication and effective index verification
- **context7:** Keep indexing rule within schema length limit

### Documentation

- **context7:** Register repository-managed provider documentation
- **packages:** Document verified container delivery and discovery


## [0.4.5](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.5) - 2026-09-08

Source: [v0.4.5](https://github.com/alpininsight/capi-provider-ssh/tree/e39a7af2475df888679fae12831be4b5f029e33b)

### Bug Fixes

- Align stable package and image identity with release tags


## [0.4.4](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.4) - 2026-09-08

Source: [v0.4.4](https://github.com/alpininsight/capi-provider-ssh/tree/701452fd5ca3b1f32b711e90d28ca5b425fdb8bc)

### Bug Fixes

- Complete lifecycle conditions, package identity and review policy

### Documentation

- Explain CAPI contract migration and current gaps
- Schedule Q4 migration and assess OSS readiness


## [0.4.3](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.3) - 2026-09-08

Source: [v0.4.3](https://github.com/alpininsight/capi-provider-ssh/tree/3a7e36385d917ea9a531fbf20a50d88068f1bdb8)

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

### CI/CD

- Test private reusable workflow access
- Locate container scan metadata
- Report container vulnerability targets


### Miscellaneous

- **deps-dev:** Bump ruff in /python in the version-updates group

### Testing

- Cover lifecycle failure boundaries and align operator docs

## [0.4.2](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.2) - 2026-08-14

Source: [v0.4.2](https://github.com/alpininsight/capi-provider-ssh/tree/1a5fe97b455a728c114a41f17e02dd0f28c3162a)

### Bug Fixes

- **ci:** Sync main back into develop after release
- **ci:** Enforce auto-merge for changelog PRs
- **runtime:** Declare Kopf cluster scope


## [0.4.1](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.1) - 2026-03-01

Source: [v0.4.1](https://github.com/alpininsight/capi-provider-ssh/tree/4be719e64c7a006c405ace4bfe7882d64f26756e)

### Bug Fixes

- **sshmachine:** Inject kubelet provider-id into bootstrap


## [0.4.0](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.4.0) - 2026-02-26

Source: [v0.4.0](https://github.com/alpininsight/capi-provider-ssh/tree/077c9796c7bc115b9b5ee035b5856d97b96ff7a5)

### Features

- **api:** Add SSHClusterTemplate CRD for ClusterClass
- **sshmachine:** Add bootstrap check strategy enum


### Styling

- Apply ruff formatting for bootstrap strategy changes

## [0.3.20](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.20) - 2026-02-25

Source: [v0.3.20](https://github.com/alpininsight/capi-provider-ssh/tree/102e7051d4a9c5c6d2521c73801323c925dfe2fd)

### Bug Fixes

- **sshmachine:** Keep ready in every provisioned reconcile patch


## [0.3.19](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.19) - 2026-02-25

Source: [v0.3.19](https://github.com/alpininsight/capi-provider-ssh/tree/2c2e3aea3a8ffdb2c43b4212a367a34edfdcd01e)

### Bug Fixes

- **sshmachine:** Persist ready ownership for provisioned machines
- **ci:** Satisfy ruff line-length for #196


## [0.3.18](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.18) - 2026-02-25

Source: [v0.3.18](https://github.com/alpininsight/capi-provider-ssh/tree/3f1ec4ffceb304f76f829b2efb128aa10b673123)

### Bug Fixes

- **sshmachine:** Backfill providerID and ready on provisioned machines


## [0.3.17](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.17) - 2026-02-25

Source: [v0.3.17](https://github.com/alpininsight/capi-provider-ssh/tree/aa1475672d2e4a3d0c12353bc82cbe1303ad480f)

### Bug Fixes

- Persist stale SSHHost claim clearing and document Lima reprovision


### Testing

- Allow route-dependent unreachable-host failures

## [0.3.16](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.16) - 2026-02-25

Source: [v0.3.16](https://github.com/alpininsight/capi-provider-ssh/tree/0cc6134695d150e793a21e4650e3593236b03b79)

### Documentation

- **roadmap:** Add dev substrate provisioning objective


### Styling

- Apply ruff format for teardown test

### Testing

- **e2e:** Add SSH e2e tests against real target
- Enforce machine-first teardown ordering
- Expand E2E ssh key path before existence check

## [0.3.15](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.15) - 2026-02-24

Source: [v0.3.15](https://github.com/alpininsight/capi-provider-ssh/tree/3aece6df8225359472feb5031c7577269dd8f9df)

### Bug Fixes

- **sshmachine:** Gate ready on kubelet post-bootstrap checks


## [0.3.14](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.14) - 2026-02-24

Source: [v0.3.14](https://github.com/alpininsight/capi-provider-ssh/tree/e78d5c9f2c69dcc00e773af527c619717aa2c48b)

### Bug Fixes

- **sshmachine:** Classify bootstrap failure phases


## [0.3.13](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.13) - 2026-02-24

Source: [v0.3.13](https://github.com/alpininsight/capi-provider-ssh/tree/53da6d95e9b090b31c15626ec300cc6c37e84e48)

### Bug Fixes

- Skip stale SSHMachine reconcile events by UID


## [0.3.12](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.12) - 2026-02-24

Source: [v0.3.12](https://github.com/alpininsight/capi-provider-ssh/tree/3ec63f6c7c3627bc38880fc10ed8cf5956f55654)

### Bug Fixes

- Add host-side bootstrap sentinel guard


## [0.3.11](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.11) - 2026-02-24

Source: [v0.3.11](https://github.com/alpininsight/capi-provider-ssh/tree/a8b650b2705625790e404174a51cec0dbd8da87a)

### Bug Fixes

- Re-read live SSHMachine state before bootstrap


## [0.3.10](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.10) - 2026-02-24

Source: [v0.3.10](https://github.com/alpininsight/capi-provider-ssh/tree/13103556f3a73ec15cd19f5b700cb74e53e7df5e)

### Bug Fixes

- Stabilize distributed lock holder identity across restarts


## [0.3.9](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.9) - 2026-02-24

Source: [v0.3.9](https://github.com/alpininsight/capi-provider-ssh/tree/e9f75fe70e1af8f05667feff5771124776112db5)

### Bug Fixes

- **sshmachine:** Block stale timer/handler bootstrap reruns
- Prevent cross-pod concurrent SSHMachine bootstrap


### Miscellaneous

- Sync main into develop for release PR mergeability
- Merge main into develop for release convergence

## [0.3.8](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.8) - 2026-02-24

Source: [v0.3.8](https://github.com/alpininsight/capi-provider-ssh/tree/bbbd2956f443e218a2508609f2360b2f3c41eca8)

### Release

- Promote develop to main

## [0.3.7](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.7) - 2026-02-24

Source: [v0.3.7](https://github.com/alpininsight/capi-provider-ssh/tree/868366f991c7549c0e2542cc510077b3424698e2)

### Bug Fixes

- **image:** Run provider module via kopf -m to avoid import errors


## [0.3.6](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.6) - 2026-02-24

Source: [v0.3.6](https://github.com/alpininsight/capi-provider-ssh/tree/6b52065fb179b295c3a5e3a8b50b44ed3b2ba028)

### Bug Fixes

- **sshmachine:** Serialize reconcile to prevent bootstrap race

### Documentation

- **governance:** Add ITSM and ISO 20000 continuity guidance


## [0.3.5](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.5) - 2026-02-24

Source: [v0.3.5](https://github.com/alpininsight/capi-provider-ssh/tree/4b3f8bd14c3f5796f2bbad49796096dfa63a6b54)

### Bug Fixes

- **sshmachine:** Prevent bootstrap rerun after provisioned


### Testing

- Enforce deterministic integration teardown cleanup

## [0.3.4](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.4) - 2026-02-23

Source: [v0.3.4](https://github.com/alpininsight/capi-provider-ssh/tree/09d01d181a0aabd303c16397c429dc6c760343e5)

### Release

- Promote develop to main

## [0.3.3](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.3) - 2026-02-23

Source: [v0.3.3](https://github.com/alpininsight/capi-provider-ssh/tree/f6fedaacc1efcd995fad85ffed2c1f415fa862cb)

### Bug Fixes

- **sshmachine:** Support cloud-init bootstrap and timer reconcile


## [0.3.2](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.2) - 2026-02-23

Source: [v0.3.2](https://github.com/alpininsight/capi-provider-ssh/tree/4207be5cc78e582eaf8e89998004b8b205f42fb8)

### Bug Fixes

- **ssh:** Use asyncio.wait_for for asyncssh operations


## [0.3.1](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.1) - 2026-02-23

Source: [v0.3.1](https://github.com/alpininsight/capi-provider-ssh/tree/0080865397aea0d8e0db71ca52878a8ae043e1b8)

### Bug Fixes

- **ci:** Sync changelog workflow from canonical template
- **capi:** Add status.ready, RBAC aggregation, and CRD contract labels
- **ci:** Add workflow_dispatch and branch guard for releases
- **ci:** Replace branch guard with canonical org template
- **ci:** Expand branch guard to all conventional commit prefixes

### Documentation

- Add RBAC requirements and external etcd contract documentation
- **external-etcd:** Fix missing ClusterConfiguration behavior description
- Fix minor documentation inaccuracies
- **external-etcd:** Fix apiVersion to match served v1beta1 contract


### Miscellaneous

- Merge main back into develop to resolve divergence

### Release

- Python CAPI provider implementation and operational docs
- Python CAPI provider implementation and operational docs
- CAPI contract compliance and CI fixes
- V0.4.0 — CAPI contract compliance, CI guards, and docs

## [0.3.0](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.3.0) - 2026-02-22

Source: [v0.3.0](https://github.com/alpininsight/capi-provider-ssh/tree/ceefbe1c55e9fe84eaa3a55e1a08cd1ab1d56706)

### Features

- **docs:** Add CI, release, and license badges to README


## [0.2.4](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.2.4) - 2026-02-22

Source: [v0.2.4](https://github.com/alpininsight/capi-provider-ssh/tree/1634e3f5629b7ea70885253639257d65217b7a1d)

### Bug Fixes

- **ci:** Prevent release image loss from concurrency cancellation
- **ci:** Inherit version bumps from develop on main merge


## [0.2.3](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.2.3) - 2026-02-22

Source: [v0.2.3](https://github.com/alpininsight/capi-provider-ssh/tree/7cbefc88d4f0eeccfa26e0e139aabba67534b8db)

### Bug Fixes

- **ci:** Self-sufficient container tagging with GitVersion and OCI labels
- **ci:** Guard semver tag on main against no-bump commits


## [0.2.2](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.2.2) - 2026-02-21

Source: [v0.2.2](https://github.com/alpininsight/capi-provider-ssh/tree/7ab3255f52dd50376e4aba9c762d1e8270349c97)

### Documentation

- Add FAQ covering RBAC, cleanup, health probing, and image tags
- **operations:** Add live rollout validation and teardown runbook
- **flux:** Make canary teardown GitOps-safe
- **operations:** Add DNS cutover runbook
- **faq:** Add staging-to-production DNS swap guidance


## [0.2.1](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.2.1) - 2026-02-21

Source: [v0.2.1](https://github.com/alpininsight/capi-provider-ssh/tree/0a9c7044ec122f3e71ab3d624ef6c743b4067f6f)

### Bug Fixes

- **docs:** Add provider-first ordering to kubectl fallback in flux runbook

### Documentation

- **roadmap:** Replace vendor-centric plugin taxonomy with protocol-based design


### Miscellaneous

- **gitignore:** Ignore coverage artifact

## [0.2.0](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.2.0) - 2026-02-21

Source: [v0.2.0](https://github.com/alpininsight/capi-provider-ssh/tree/27b130722878ae1f27197b1e538e8ba222bb05fa)

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

### Documentation

- **security:** Add ssh key lifecycle runbook

### Features

- **python:** Scaffold kopf controller with pyproject.toml
- **python:** Implement SSHCluster controller
- **python:** Implement SSH client wrapper
- **python:** Implement SSHMachine controller
- **ci:** Split #12 into CI and container workflows
- **crds:** Add SSHHost CRD for Metal3-style host inventory
- **python:** Add external etcd wiring and reboot remediation
- **python:** Add dry-run mode, SSHHost health probing, and docs


### Miscellaneous

- Add DCO and update README with contributing guidelines
- Remove AI references and update .gitignore
- **repo:** Add pre-commit config and conventional commit hook

### Styling

- Format sshmachine.py for ruff compliance
- **python:** Format sshmachine controller with ruff

### Testing

- **python:** Add unit tests for all controllers and SSH client
- **python:** Add runtime startup regression guard
- **python:** Add integration tests for SSHCluster and SSHMachine

### Release

- Merge develop into main

## [0.1.0](https://github.com/alpininsight/capi-provider-ssh/releases/tag/v0.1.0) - 2026-02-20

Source: [v0.1.0](https://github.com/alpininsight/capi-provider-ssh/tree/3b55587d20a2e4dba33a4018bbdbb9251d871ea2)

### Miscellaneous

- Initialize repository with shared CRDs and project structure
- Add CI workflows, license, and project docs

---
*Generated by [git-cliff](https://git-cliff.org/)*
