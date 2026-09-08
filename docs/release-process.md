# Release and delivery

The change owner coordinates source review and evidence. The platform owner
controls the consumer GitOps rollout. A security fix also follows
[SECURITY.md](../SECURITY.md) and the [maintenance/backport policy](maintenance-policy.md). Neither a release nor a merge authorizes unrelated
infrastructure changes.

## Source acceptance

Work from current `develop` through a PR. Require completed checks on the current
head: Python 3.13/3.14, hooks, manifest validation, image/runtime validation and
the CAPI lifecycle lane. For changed behavior, update the support and operator
documentation before review. Inspect failed logs; do not replace failures with
skips or weaken a policy gate to obtain a green status.

The exact check names and active rules are described in
[CI routing and merge acceptance](ci-governance.md). Release PRs go from
`develop` to `main` and use a merge commit, preserving the release branch history.

The existing [release workflow](../.github/workflows/release.yml) uses GitVersion
6.8.x and creates a GitHub release from `main`; the [container workflow](../.github/workflows/container-build-python.yml)
publishes separately. Release metadata alone does not prove that a compatible
image or a `clusterctl` provider-components bundle exists. The current repository
does not ship a complete versioned `clusterctl` installation bundle.

The release and container workflows can finish in either order. An existing Git
tag on the build's own commit still permits the matching image version tag; a
tag on a different commit is preserved. Verify the release tag, image version
tag and immutable source digest together after publication.

## Python package identity and license verification

The required version job selects GitVersion `MajorMinorPatch` on `main`, matching
the stable GitHub release, and retains `SemVer` for all other refs. In
`ManualDeployment` mode, the raw `SemVer` can still contain a numeric prerelease
suffix before the parallel release workflow creates its tag. That candidate
suffix must not become a stable image's package identity. Both calculated values
must identify the same version core; invalid inputs fail before building.

The selected value supplies both validation and published container builds as
`PROVIDER_VERSION`, and supplies the OCI version labels and annotations. The
installed Python package, its `__version__` and wheel/sdist metadata use the
PEP 440 equivalent:

| Build identity | Python metadata |
|---|---|
| Stable `v0.4.3` / `0.4.3` | `0.4.3` |
| `0.5.0-alpha.12`, beta or RC | `0.5.0a12`, corresponding `b` or `rc` version |
| Other GitVersion branch prerelease | `<base>.dev0+gitversion.<hex-encoded-prerelease>`; identity retained without implying a stable release |
| Source without release input | `0.0.0+unversioned`; no release claim |

The Hatch build hook freezes the calculated value in each artifact. Rebuilding
from a source archive needs neither Git nor the original version environment.
The non-editable container installation removes the source copy so it cannot
shadow the installed package's release identity. The OCI version metadata retains
the selected SemVer; compare using the documented conversion above.

Both artifacts include `LICENSE`, `License-Expression: MPL-2.0`, `License-File` and
public project URLs. `python/LICENSE` must match the canonical repository license
byte for byte; changing license terms requires a separate explicit decision.
The artifact check inspects both formats, rebuilds a wheel outside Git and the
version environment, then imports an isolated installation:

```bash
uv run --project python --frozen python python/scripts/check_package.py --version v0.4.3
```

Use the intended release's calculated version, not the example version, for a
release candidate. Add `--offline` only when build dependencies are cached.
Artifacts live in a temporary directory and are removed after inspection. This
check does not upload to PyPI or retroactively repair older published images.
The published `v0.4.4` image has a known identity mismatch; see the
[support notice](support-matrix.md#v044-package-identity-notice). A correction
must use a new stable patch and retain the original tag/digest for traceability.
See [PyPA package metadata](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/),
[Hatch build hooks](https://hatch.pypa.io/latest/plugins/build-hook/reference/)
and [GitVersion Manual Deployment](https://gitversion.net/docs/reference/modes/manual-deployment).

## Evidence chain

| Gate | Evidence to retain | Acceptance |
|---|---|---|
| Reviewed source | PR head, merged commit and exact completed checks | No unresolved required failure or cancellation |
| Published image | OCI index, platform digests, source labels, scan and provenance/SBOM | Correct source for each advertised architecture |
| Consumer review | GitOps PR, CRD/RBAC ordering, immutable pin and resource/placement diff | Registry and platform prerequisites verified |
| Reconciliation | Observed GitOps revision and rendered objects | Desired manifests actually delivered |
| Controller runtime | Actual image IDs, both probes, peers, restart/OOM counters and scheduling | Stable active/standby operation |
| Workload canary | Bootstrap, Node association, deletion and host reuse | Required only when claiming workload lifecycle delivery |

For a mirror/relay, test the actual consumer identity and exact image pull path;
an existing local image cache does not prove registry authorization. Include a
negative identity check when changing admission. Preserve maintenance cordons and
other operators' work. A namespace-audit Job has different permissions from the
controller and must use its own operation contract.

## Upgrade and recovery

Choose component versions from [support](support-matrix.md). CAPI upgrades follow
the upstream version-skew policy and are staged separately from provider changes
when that makes evidence attributable. Do not combine an unsupported version jump
with lifecycle ownership migration.

Before a rollout, record current ownership/claims and agree the recovery boundary.
If validation fails, pause new lifecycle work through CAPI and preserve the
remote receipts, claims and finalizers. An accepted remote command can continue
after pause. A blind image downgrade can misinterpret persisted ownership state;
use the inspected state and a reviewed forward fix. Restore credentials or trust
only through the verified procedures in [operations](operations.md).

For management-plane disaster recovery, the platform must back up Kubernetes
state including CAPI/provider objects, relevant Secrets and their encryption
keys. There is no provider-owned backup service or guaranteed RPO/RTO. After a
restore, verify remote ownership/receipts against restored object UIDs before
allowing reconciliation; never infer identity from a reused object name.

## Post-merge review

Inspect replacement develop runs when changelog automation cancels earlier CI;
compare runtime inputs before reusing evidence. Record escaped defects, review
ambiguities and preventive actions in [merge reviews](merge-reviews.md).
Do not report delivery complete until the requested consumer gate passed.
Keep detailed deployment evidence in the access-controlled consumer record and
publish only appropriate aggregate product findings.
