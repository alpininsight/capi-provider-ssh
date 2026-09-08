# Test portfolio and evidence

Use the locked dependencies and commands in [development](../DEVELOPMENT.md).
The portfolio verifies behavior at several levels; percentages and green
controller pods do not replace a lifecycle test.

## Lanes

| Lane | What it establishes | What it does not establish |
|---|---|---|
| Unit and stateful contract tests | UID/resourceVersion persistence, allocation, pause, cleanup, reboot, Lease failure and crash-boundary behavior | Real API admission or all network failures |
| Loopback SSH and TLS | Real host-key verification, private transfer, API certificate/hostname verification, token rotation, denial and stalled responses | Reachability or identity of a production host |
| Real API integration in Kind | Structural CRDs, defaults, status subresources, controller reconciliation, readiness and concurrent probe memory behavior | Every Kubernetes version or hardware platform |
| Full CAPI lifecycle in Kind | CABPK/KCP init/join, providerID association, deletion/reuse and takeover during bootstrap | A production SLA or external-etcd availability |
| Explicit external SSH E2E | The selected endpoint's SSH behavior with independently verified trust | General fleet or multi-distribution certification |
| Consumer GitOps acceptance | Actual image, CRD/RBAC delivery, registry pull, readiness and coordination | Workload lifecycle unless a canary was also run |

Unit collection intentionally excludes `integration`, `e2e` and `kind` markers.
Those lanes must be selected explicitly and fail if their prerequisites are
missing. The loopback transport tests remain part of the isolated unit command.
The full disposable command is `bash scripts/test-kind-lifecycle.sh`.

CI governance tests exercise missing, pending, failed and cancelled checks,
changed PR heads/bases, conflicting branches, unexpected changes, check origin
and server rejection. They also validate the required-check names against the
actual workflows and execute the external-SSH configuration preflight.
See [CI governance](ci-governance.md) for routing and external target setup.

## Failure cases that must remain covered

- An API-denied, missing or recreated CAPI owner cannot authorize bootstrap.
- Lease read/create/update errors and CAS conflicts cannot enter a host operation;
  loss during work cancels local execution without releasing a new holder's Lease.
- External task cancellation is preserved; release failure cannot hide the
  original error or authorize another operation before expiry.
- Cleanup with mismatched ownership or multiple unstarted claims retains the
  claims. Retrying persisted successful cleanup does not repeat the reset.
- An unknown reboot is not replayed; a new request cannot overlap a submitted
  request; deletion waits for reboot observation before cleanup.
- A failed bootstrap submission/receipt read never becomes speculative replay.
- Readiness handles TLS/auth failures and stalled headers/body with a bounded
  failure result, without credential disclosure or retries.
- Concurrent exec probes stay within the declared cgroup budget, with zero OOM
  kills and unchanged controller process/restart identity.

Source pointers: [stateful lifecycle tests](../python/tests/test_lifecycle_contract.py),
[bootstrap receipts](../python/tests/test_durable_bootstrap.py),
[TLS transport](../python/tests/test_readiness_transport.py),
[Kind lifecycle](../python/tests/kind/test_lifecycle.py).

## Temporary coverage measurement

Coverage is a diagnostic for selecting meaningful gaps. From `python/`, write
all measurement files outside the repository:

```bash
coverage_dir="$(mktemp -d "${TMPDIR:-/tmp}/capi-coverage.XXXXXX")"
COVERAGE_FILE="$coverage_dir/.coverage" uv run --frozen pytest -q \
  -m 'not integration and not e2e and not kind' \
  --cov=capi_provider_ssh --cov-branch --cov-report=term-missing \
  --cov-report="json:$coverage_dir/coverage.json"
```

Keep the denominator explicit: line coverage, branch coverage and their combined
percentage differ. This command measures the local Python processes instrumented
by pytest-cov, not remote controller containers or target-host shell execution.
pytest-cov 7 does not automatically instrument subprocesses. Do not interpret
uncovered remote-runtime code as proof that the separate Kind lane never tested it.
Do not commit `.coverage`, JSON/XML/HTML reports or a dry-run configuration.

The private organization `reusable-ci.yml` exposes `coverage-package` and uses
self-hosted runners, but assumes a root project with a `dev` extra and `src/`.
This repository instead uses `python/` and a `dev` dependency group. Its public
CI aligns with the configurable Python quality workflow and cannot directly
call a private reusable workflow. A local adapted pytest command is sufficient
for a dry run; no runner restart or new workflow integration is needed.

References: [pytest-cov reporting](https://pytest-cov.readthedocs.io/en/latest/reporting.html),
[subprocess coverage](https://pytest-cov.readthedocs.io/en/latest/subprocess-support.html),
[GitHub workflow access](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations).

## Acceptance and remaining gaps

Retain final-head CI evidence for the configured Python matrix, image and Kind
lanes. Historical counts in [P1 validation](p1-validation.md) are snapshots.
An environment failure, missing fixture or skipped prerequisite is an open
verification gap. Fixtures must not remove finalizers to manufacture success.

Hardware plugins, sustained fleet-scale behavior, every cloud-init form/Linux
distribution and an externally managed etcd cluster are not fully certified by
this portfolio. Add a risk-specific lane when introducing such support; do not
raise a coverage threshold as a substitute for it.
