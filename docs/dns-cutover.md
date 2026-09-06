# Environment traffic cutover

This is an operator planning checklist outside the SSH provider API. The provider
does not manage DNS, application data replication or production promotion.
The application/platform owners must approve the selected environment, change
window, validation and recovery plan before traffic changes.

## Preconditions and acceptance

- Verify the exact application image, configuration, migrations, credentials and
  certificates in the destination environment.
- Establish data ownership, replication lag and the write/freeze strategy. An
  old environment is a usable rollback target only if its data remains compatible.
- Test the destination through its intended routing and authentication paths,
  including background workers and critical read/write operations.
- Record DNS/routing state and propagation behavior using the selected provider's
  current official procedure; a low TTL does not force all clients to switch at once.
- Define acceptance thresholds, monitoring owner, rollback trigger and the
  conditions under which rollback would require data reconciliation.

## Cutover and recovery

Freeze unrelated delivery, perform the reviewed DNS/routing change, and verify
actual traffic, authentication, data operations and workers. Keep the old
environment available for the agreed window with its write behavior controlled.
Record the result in the private environment change record.

If acceptance fails, use the agreed recovery procedure. Repointing DNS alone is
not sufficient when both environments may have accepted writes or schemas differ.
Preserve diagnostic evidence and resolve the data boundary before resuming traffic.

## Retirement

Retire the old environment only after acceptance, the agreed rollback window,
backup/restore verification and the required audit retention are complete.
Delete CAPI Machines through normal lifecycle orchestration and verify provider
cleanup and host claims; do not delete CRDs or force finalizers as a shortcut.
See [rollout validation](live-rollout-validation.md) and [operations](operations.md).
