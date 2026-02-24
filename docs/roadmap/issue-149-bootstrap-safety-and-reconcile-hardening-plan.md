# Issue #149 Design Plan: Bootstrap Safety and Reconcile Hardening

## Scope

Primary driver:
- [Issue #149](https://github.com/alpininsight/capi-provider-ssh/issues/149) - cross-pod concurrent bootstrap risk.

Related follow-up issues:
- [Issue #144](https://github.com/alpininsight/capi-provider-ssh/issues/144) - host-side bootstrap idempotency sentinel.
- [Issue #146](https://github.com/alpininsight/capi-provider-ssh/issues/146) - stale event UID validation.
- [Issue #145](https://github.com/alpininsight/capi-provider-ssh/issues/145) - post-bootstrap readiness semantics.
- [Issue #147](https://github.com/alpininsight/capi-provider-ssh/issues/147) - bootstrap error classification.

Already implemented (no new fix needed for this item):
- In-process per-machine lock and reconcile serialization in v0.3.8 (single process path).

## Problem Statement

v0.3.8 fixed in-process timer/handler races, but process-local locking cannot
prevent concurrent bootstrap if two operator processes handle the same object
(rolling update overlap, misconfigured replicas, or parallel runtime instances).

## Design Goals

1. Prevent concurrent bootstrap execution across operator processes.
2. Make repeated bootstrap execution safe at host level.
3. Reject stale reconcile events by object identity (UID).
4. Improve readiness semantics so `Ready=True` matches node usability.
5. Improve failure diagnostics for faster operator triage.

## Non-Goals

1. Replacing bootstrap provider behavior (kubeadm data generation remains upstream).
2. Introducing new external dependencies beyond Kubernetes-native coordination primitives.

## Atomic Implementation Slices

### Slice 1: Cross-Process Reconcile Safety Baseline (Issue #149)

Changes:
1. Configure controller runtime for singleton execution safety:
   - enforce Deployment strategy that avoids overlapping active pods during updates
   - explicitly document replica constraint and operational guardrails
2. Introduce cluster-scoped active-controller coordination (leader/peering).
3. Fail fast (or refuse bootstrap) when active leader coordination is unavailable.

Acceptance criteria:
1. With two controller pods started concurrently, only one processes `SSHMachine` bootstrap.
2. Rolling update cannot trigger simultaneous bootstrap on the same `SSHMachine`.
3. Safety behavior is observable in logs/conditions.

### Slice 2: Host-Side Bootstrap Sentinel Guard (Issue #144)

Changes:
1. Wrap bootstrap script execution with provider-injected sentinel logic:
   - pre-check sentinel file and return success when present
   - write sentinel only after successful bootstrap completion
2. Keep behavior transparent in logs (guard-hit vs full bootstrap path).

Acceptance criteria:
1. Reconcile re-run after successful bootstrap does not execute destructive commands again.
2. Guard path preserves successful idempotent outcome.

### Slice 3: UID-Based Stale Event Validation (Issue #146)

Changes:
1. At reconcile entry, fetch live `SSHMachine` and compare event `meta.uid` to live UID.
2. Exit safely if object no longer exists or UID mismatch is detected.
3. Apply the same identity validation to timer and handler paths.

Acceptance criteria:
1. Stale callbacks for deleted/recreated objects never execute bootstrap.
2. Unit tests cover mismatch/no-object cases.

### Slice 4: Post-Bootstrap Readiness Gate (Issue #145)

Changes:
1. Separate "bootstrap command completed" from "machine ready for CAPI consumption".
2. Add host-level readiness probes before setting `Ready=True`:
   - kubelet service/activity checks
   - optional bounded retry with explicit condition reasons

Acceptance criteria:
1. `SSHMachine Ready=True` only after post-bootstrap readiness checks pass.
2. Failures set `Ready=False` with actionable reason.

### Slice 5: Failure Classification and Diagnostics (Issue #147)

Changes:
1. Classify bootstrap failures by phase and known stderr signatures.
2. Persist concise diagnostic fields:
   - phase
   - exit code
   - sanitized stderr excerpt
3. Keep backward compatibility for consumers expecting current failure fields.

Acceptance criteria:
1. Distinct failure reasons for reset/init/join classes.
2. Unit tests verify classification mapping.

## Testing Strategy

### Unit Tests

1. Cross-process coordination behavior (mocked coordinator state).
2. Sentinel guard hit/miss behavior.
3. UID mismatch and no-object short-circuit.
4. Readiness gate pass/fail.
5. Failure classification matrix.

### Integration Tests

1. Simulated rolling update overlap scenario (two controller instances).
2. Delete/recreate same-name `SSHMachine` with stale timer callback.
3. Reconcile retry after successful bootstrap to confirm sentinel no-op.

### Rollout Validation

1. Validate in staging with explicit control-plane bootstrap replay checks.
2. Confirm no duplicate bootstrap execution in logs.
3. Confirm `Ready` semantics match observed kubelet/node state.

## Delivery Sequence

1. Slice 1 (critical blocker, issue #149)
2. Slice 2 (safety net, issue #144)
3. Slice 3 (identity hardening, issue #146)
4. Slice 4 (readiness semantics, issue #145)
5. Slice 5 (diagnostics quality, issue #147)

## Documentation Updates

1. Keep `docs/faq.md` aligned with implemented behavior and known limitations.
2. Link this plan from `docs/roadmap.md`.
3. Update release notes when each slice ships.
