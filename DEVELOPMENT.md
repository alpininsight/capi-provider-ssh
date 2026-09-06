# Development

Use an isolated branch from current `origin/develop`; preserve existing local
changes. See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR and DCO requirements.

## Tools and isolation

| Lane | Required tooling |
|---|---|
| Unit, contract and loopback transport | uv; Python 3.13 or 3.14; permission to bind loopback ports |
| Formatting and hooks | Locked Ruff; pre-commit 4.6.2 as used by CI |
| Manifest rendering | kubectl with Kustomize support; CI adds kubeconform |
| Full CAPI lifecycle | Docker, Kind 0.33.0, kubectl 1.34.11 and uv |
| Release version validation | GitVersion 6.8.x through the release workflow |

Python dependencies are locked in [python/uv.lock](python/uv.lock).
The Kind lane pins upstream assets in
[python/tests/kind/upstream.json](python/tests/kind/upstream.json).
Install tools through their official distribution channels and verify the
selected release/checksum. Do not replace these tested pins with a floating
latest version when reproducing CI.

## Setup and fast checks

From the repository root:

```bash
uv sync --project python --frozen --dev --python 3.13
uv run --project python ruff check python/capi_provider_ssh python/tests
uv run --project python ruff format --check python/capi_provider_ssh python/tests
```

Run tests from `python/`, so test paths and package resolution match CI:

```bash
cd python
uv run --frozen pytest -q -m 'not integration and not e2e and not kind'
```

The isolated lane does not require a management-cluster kubeconfig or external
host credentials. SSH/TLS tests bind temporary loopback ports; a sandbox denying
socket binding is an environment failure, not a passing skipped transport test.

From the repository root, run all configured hooks:

```bash
uvx --python 3.14 --from pre-commit==4.6.2 pre-commit run --all-files
```

Install local hooks with the same pre-commit version if desired, including the
`commit-msg` hook. Mypy is a development dependency but is not currently a required
provider CI job; do not describe a whole-project type check as passed without
running and inspecting it.

## Lifecycle tests

Run `bash scripts/test-kind-lifecycle.sh` from the repository root. The script
creates an isolated Kind management cluster and disposable SSH/kubeadm hosts;
allow approximately 8 GB Docker RAM and 30 minutes. It uses an explicit generated
kubeconfig and verified upstream assets. Never point this destructive lane at a
shared or production management cluster.

A failed run retains diagnostic state. Follow [testing](docs/testing.md) before
cleanup; retain Secrets and finalizers until normal CAPI deletion succeeds.
External SSH E2E is a separate opt-in lane with independently verified host trust.

## Cross-repository work

The provider produces source and images. The consumer GitOps repository owns
deployment pins, registry admission and platform placement. Follow that
repository's own instructions and checks, including diff-based CI guards; its
full test runner may not execute every PR-only policy gate.

The [test portfolio](docs/testing.md) explains evidence boundaries and temporary
coverage measurement. A private reusable workflow cannot be invoked directly by
this public repository; existing local CI documents the public-repository exception.
