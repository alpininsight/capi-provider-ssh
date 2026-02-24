# Frequently Asked Questions

## RBAC: Does the example RBAC include CRD permissions for Kopf?

**Yes.** The shipped `python/deploy/rbac.yaml` includes:

```yaml
# CRD discovery for dynamic watch setup and contract checks
- apiGroups: ["apiextensions.k8s.io"]
  resources: ["customresourcedefinitions"]
  verbs: ["get", "list", "watch"]
```

Kopf needs `apiextensions.k8s.io` get/list/watch to discover CRDs and set up
watches. If your ServiceAccount is missing these permissions, verify you are
using the reference RBAC from `python/deploy/rbac.yaml` and not a customized
version that dropped this rule. See
[docs/rbac-requirements.md](rbac-requirements.md) for the full permission
table.

**Symptoms when missing:** Kopf logs 403 Forbidden errors during CRD discovery
and may fail to reconcile resources. The controller does not add custom logging
for this — Kopf emits the warnings internally.

## Does the controller run kubeadm reset on Machine deletion?

**Yes.** The SSHMachine delete handler
(`python/capi_provider_ssh/controllers/sshmachine.py`) performs two actions:

1. Releases the claimed SSHHost back to the pool (clears `consumerRef`)
2. SSHes into the host and runs:
   ```bash
   kubeadm reset -f && rm -rf /etc/kubernetes /var/lib/kubelet
   ```

Cleanup failures (SSH unreachable, command fails, missing SSH key) are logged
as warnings but **never block finalizer removal** — the Machine resource is
always deletable.

If you are not seeing cleanup happen, check which image tag you are running.
The cleanup logic landed in develop after v0.1.0. Pin to the latest release
tag rather than the floating `develop` tag.

## Is there a configurable cleanup hook (postDeleteCommands)?

**Not yet.** The cleanup command is currently hardcoded. A configurable
`spec.cleanupCommands` field is a good enhancement for cases where additional
post-deletion cleanup is needed (CNI-specific teardown, custom iptables flush,
application state removal). This is tracked as a wishlist item.

As a workaround, you can add cleanup steps to `preKubeadmCommands` so that
stale state is cleared before re-provisioning:

```yaml
preKubeadmCommands:
  - kubeadm reset -f || true
  - rm -rf /etc/cni/net.d /var/lib/cni
  - iptables -F && iptables -t nat -F && iptables -t mangle -F
```

## Is SSHHost health probing functional?

**Yes.** The SSHHost controller runs a timer-based probe on each SSHHost:

- **Interval:** 300 seconds (configurable via `SSHHOST_PROBE_INTERVAL` env var)
- **Timeout:** 10 seconds per probe (configurable via `SSHHOST_PROBE_TIMEOUT`)
- **Initial delay:** 10 seconds after controller startup

Each probe tests SSH connectivity (connect and disconnect) and updates:

| Status field | Description |
|-------------|-------------|
| `status.ready` | `true` if last probe succeeded |
| `status.lastProbeTime` | ISO 8601 timestamp of last probe |
| `status.lastProbeSuccess` | `true`/`false` result of last probe |
| `status.conditions[SSHReachable]` | Condition with reason `ProbeSucceeded` or `ProbeFailed` |

The SSHMachine controller's `_choose_host()` logic uses probe results to
prefer healthy hosts when claiming from the pool.

**To verify probing is working:**

```bash
kubectl get sshhosts -o custom-columns=\
NAME:.metadata.name,\
READY:.status.ready,\
LAST_PROBE:.status.lastProbeTime,\
IN_USE:.status.inUse
```

## Should I use the floating develop tag in staging?

**No.** Pin to a release tag (e.g., `v0.2.0`) for staging and production. The
`develop` tag is a floating tag that points to the latest commit on the develop
branch — it may include incomplete features or breaking changes.

New releases are cut automatically when `develop` is merged into `main`. Check
the [Releases page](https://github.com/alpininsight/capi-provider-ssh/releases)
for the latest stable tag.

## How does the provider prevent concurrent bootstrap across multiple controller pods?

The SSHMachine controller now applies a **cross-process distributed lock** on
each `SSHMachine` by writing a lock annotation with optimistic concurrency
(`metadata.resourceVersion` compare-and-swap). This sits on top of the existing
in-process `asyncio.Lock`.

Behavior:

1. Reconcile/delete handlers first acquire the in-process per-machine lock.
2. Then they acquire the distributed lock annotation.
3. Under lock, reconcile re-reads the live `SSHMachine` from the API server
   when the event contains `metadata.uid`, and skips bootstrap when
   `status.initialization.provisioned=true`.
4. If another pod already holds the lock, the handler requeues with
   `kopf.TemporaryError` and does not execute bootstrap/cleanup.

Bootstrap execution also has a host-side sentinel guard:
- On entry: if `/run/cluster-api/bootstrap-success.complete` exists, bootstrap
  short-circuits to success without rerunning script steps.
- On success: provider creates that sentinel file.

Reconcile also validates object identity under lock: if the live object is gone
or the live `metadata.uid` differs from the event UID, the handler exits
without bootstrap. This prevents stale timer/update callbacks from acting on a
deleted/recreated `SSHMachine` with the same name.

Environment controls:

- `SSHMACHINE_DISTRIBUTED_LOCK_ENABLED` (default: `true`)
- `SSHMACHINE_DISTRIBUTED_LOCK_TTL_SECONDS` (default: `7200`)
- `SSHMACHINE_DISTRIBUTED_LOCK_RETRY_DELAY_SECONDS` (default: `5`)

Lock holder identity is stable across process restarts (`POD_NAME`/`HOSTNAME`
based, no random suffix), so a controller restart can reclaim its own
non-expired lock instead of waiting for TTL expiry.

This protects rolling-update overlap windows where two operator instances may
be active briefly.

## How does integration test teardown avoid leaked test namespaces?

Integration tests now use a deterministic teardown contract in
`python/tests/integration/cleanup.py`:

1. Teardown is allowed only for namespaces with prefix `test-capi-ssh-` and
   label `capi-provider-ssh-test=true`.
2. Resources are deleted in explicit order (`SSHMachine`/`SSHCluster` first,
   then CAPI/Bootstrap test objects, then namespace).
3. Teardown asserts there is no residue (`Machine`, `SSHMachine`,
   `KubeadmConfig`, test Secrets, test namespaces).
4. On teardown failure, a debug bundle is written (when
   `TEARDOWN_ARTIFACT_DIR` is set) and uploaded by CI.

This is designed to prevent recurring `test-cluster not found` noise from
orphaned test resources.

## Can I swap DNS so staging becomes production and keep old production as backup?

**Yes.** This is a valid blue/green-style cutover pattern:

1. Promote staging to production traffic via DNS.
2. Keep old production online as rollback target.
3. Tear down old production only after review acceptance and rollback-window
   expiry.

Recommended controls:
- Lower DNS TTL before cutover (for example 60s).
- Keep old production read-only during rollback window.
- Validate health/smoke checks immediately after DNS switch.
- If issues appear, switch DNS back to old production first, then debug.

Use `docs/dns-cutover.md` for the full cutover and teardown gate runbook.

## Pod logs unreachable via tunnel (kubectl logs returns NotFound)

This is typically a tunnel or API server subresource routing issue, not a
provider problem. `kubectl logs` requires the API server to proxy a
subresource request to the kubelet on the target node.

**Troubleshooting steps:**

1. Verify the pod exists: `kubectl get pod <name> -n <namespace>`
2. Try `kubectl describe pod` (uses the API server directly, no subresource)
3. Check if `kubectl exec` also fails (same subresource mechanism)
4. If both fail, the tunnel likely does not support subresource proxying —
   access the node directly or check your tunnel configuration

The controller itself logs to stdout. If `kubectl logs` is broken through
your tunnel, access the controller pod's logs via the node directly or
through your cluster's log aggregation.
