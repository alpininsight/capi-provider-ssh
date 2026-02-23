# Issue #119 Design Plan: Cloud-Init Bootstrap Compatibility + Reconcile Reliability

Issue: [#119](https://github.com/alpininsight/capi-provider-ssh/issues/119)

## Problem Summary

The SSHMachine controller currently assumes bootstrap data is a shell script and executes it directly as `/tmp/bootstrap.sh`. In production CAPI flows, bootstrap data is commonly cloud-init (`#cloud-config`), which fails when executed as bash.

Issue #119 also highlights a reliability gap: reconciliation can be missed when `ownerReferences` are not present at first creation event and no later event re-triggers reconciliation.

## Goals

1. Make bootstrap execution format-aware (`cloud-config` and shell).
2. Preserve existing shell-script bootstrap behavior.
3. Keep external etcd wiring compatible with both bootstrap formats.
4. Add periodic SSHMachine reconciliation so missed create/update events recover automatically.
5. Add focused regression tests for both failures from issue #119.

## Non-Goals

1. Adding host-side `cloud-init` as a runtime dependency.
2. Supporting every cloud-init module; only modules required by kubeadm bootstrap output and current provider behavior.
3. Changing CRD schema for this fix.

## Design Decisions

1. Provider-side execution normalization:
   - Detect bootstrap payload format.
   - Convert supported cloud-init payload to executable shell before upload.
   - Execute one deterministic rendered script remotely.
2. Keep controller behavior idempotent:
   - Preserve existing `providerID`/`initialization.provisioned` checks.
   - Reuse current status/failure fields.
3. Add timer-driven reconcile for SSHMachine:
   - Retry non-ready machines at fixed interval.
   - Reuse existing reconcile logic rather than duplicating behavior.

## Atomic Implementation Slices

### Slice 1: Bootstrap Format Detection and Parsing Primitives

Files:
- `python/capi_provider_ssh/controllers/sshmachine.py`

Changes:
1. Add format detector:
   - `cloud-config` if a non-empty line starts with `#cloud-config` (allow optional leading `## template: jinja`).
   - `shell` if first non-empty line starts with shebang (`#!`) or fallback shell heuristic.
   - `unknown` otherwise.
2. Add parser helper for cloud-init YAML with schema validation for:
   - `write_files` (list of mappings)
   - `runcmd` (list of commands)
3. Add explicit failure mapping:
   - Unsupported/invalid bootstrap format -> `PermanentError` with status reason `BootstrapFormatError`.

Acceptance criteria:
1. Controller can classify cloud-init and shell inputs deterministically.
2. Invalid/unknown format fails with actionable status message.

### Slice 2: Cloud-Init -> Shell Renderer

Files:
- `python/capi_provider_ssh/controllers/sshmachine.py`

Changes:
1. Implement renderer that converts parsed cloud-init to shell:
   - `write_files`: create directories, write file content via quoted heredoc, apply permissions/owner if present.
   - `runcmd`: support string and list form commands.
2. Support expected encodings for `write_files.content`:
   - plain text
   - base64 (`encoding: b64`/`base64`)
3. Emit deterministic script with strict shell options (`set -euo pipefail`).

Acceptance criteria:
1. Rendered script is executable with current SSH execution path.
2. File payloads and command order from cloud-init are preserved.

### Slice 3: Reconcile Integration + External Etcd Compatibility

Files:
- `python/capi_provider_ssh/controllers/sshmachine.py`

Changes:
1. Before upload, normalize bootstrap payload:
   - shell input -> pass through
   - cloud-init input -> render to shell
2. External etcd patching:
   - Keep existing shell heredoc patch path.
   - Add cloud-init patch path by modifying kubeadm `ClusterConfiguration` content inside `write_files` entries for kubeadm YAML files.
3. Add explicit bootstrap-format logging (`shell` vs `cloud-config`) without leaking secrets.

Acceptance criteria:
1. Existing shell bootstrap tests remain green.
2. Cloud-init bootstrap succeeds through same SSH upload/execute interface.
3. External etcd injection works for both formats.

### Slice 4: Timer-Based Reconcile for SSHMachine

Files:
- `python/capi_provider_ssh/controllers/sshmachine.py`
- `python/capi_provider_ssh/main.py` (optional env naming cleanup only if needed)
- `python/deploy/deployment.yaml` (if introducing dedicated interval variable)

Changes:
1. Add `@kopf.timer` for `sshmachines` with interval default (for example 60s).
2. Refactor reconcile body into shared internal function used by:
   - create handler
   - update handler
   - timer handler
3. Timer guardrails:
   - skip paused objects
   - skip already-provisioned objects
   - retry objects waiting for owner, bootstrap data, or transient SSH errors

Acceptance criteria:
1. Missing initial event no longer leaves SSHMachine permanently stuck.
2. No behavioral regression for normal create/update-triggered reconciliation.

### Slice 5: Unit + Integration Test Expansion

Files:
- `python/tests/test_sshmachine.py`
- `python/tests/integration/conftest.py`
- `python/tests/integration/test_sshmachine_integration.py`

Changes:
1. Add unit tests for bootstrap normalization:
   - cloud-init with `write_files` + `runcmd` renders and executes successfully
   - invalid cloud-init structure returns `BootstrapFormatError`
   - shell format remains unchanged
2. Add unit tests for cloud-init + external etcd patch path.
3. Add timer-reconcile tests:
   - waiting-for-owner state recovered when owner appears later
   - provisioned machine skipped by timer
4. Change integration bootstrap fixture to cloud-init representative payload.

Acceptance criteria:
1. Tests fail on old behavior and pass with new implementation.
2. Regressions for issue #119 are permanently covered.

### Slice 6: Docs and Release Notes

Files:
- `README.md`
- `docs/architecture.md`
- `docs/faq.md`
- `CHANGELOG.md`

Changes:
1. Document bootstrap format support and controller behavior.
2. Add troubleshooting entry for bootstrap format mismatch symptoms.
3. Record fix in changelog.

Acceptance criteria:
1. Operator-facing docs clearly describe expected bootstrap formats and fallback behavior.

## Test Matrix

1. Static checks:
   - `cd python && .venv/bin/ruff check .`
2. Focused unit tests:
   - `cd python && .venv/bin/pytest tests/test_sshmachine.py -q`
3. SSH wrapper/controller safety checks:
   - `cd python && .venv/bin/pytest tests/test_ssh.py tests/test_sshhost.py -q`
4. Integration tests (when environment is available):
   - `cd python && INTEGRATION_TESTS=1 .venv/bin/pytest -m integration -q`

## Rollout Strategy

1. Merge feature PR to `develop`.
2. Run management-cluster canary validation:
   - verify a fresh SSHMachine with cloud-init bootstrap reaches `provisioned=true`
   - verify timer retries non-ready SSHMachine without manual annotation nudge
3. Promote `develop -> main` release PR.
4. Validate published image and release tag.

## Risks and Mitigations

1. Risk: cloud-init parsing misses uncommon kubeadm output shape.
   - Mitigation: strict validation + explicit error reason + fixture based on real bootstrap secret samples.
2. Risk: timer introduces duplicate reconcile attempts.
   - Mitigation: shared idempotency checks and timer guardrails.
3. Risk: external etcd patching diverges between formats.
   - Mitigation: single semantic patch target (`ClusterConfiguration`) with format-specific adapters and dedicated tests.

## Definition of Done

1. Issue #119 reproduction no longer fails with `write_files: command not found`.
2. SSHMachine eventually reconciles after missed ownerReference timing windows.
3. Unit + integration coverage includes cloud-init bootstrap and timer retry scenarios.
4. Docs and changelog updated.
