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

## Changelog release boundaries

Use **git-cliff 2.14.2**, matching the changelog and Python quality workflows.
Version 2.14 corrected release attribution to use graph reachability; the older
2.7.0 generator can misattribute late-merged commits even after stable tags are
reachable. See the [upstream change](https://github.com/orhun/git-cliff/blob/main/website/blog/git-cliff-2.14.0.md).
Fetch the full remote history and tags, then run from the repository root:

```bash
git fetch origin --tags
python3 python/scripts/generate_changelog.py
```

The wrapper requires all stable tags reachable from `origin/main` to be present
in the current history. It validates the generated release commit IDs against
the peeled tags, checks commit ancestry and rejects already published work in
Unreleased. It renders only that verified context and replaces `CHANGELOG.md`
after success. Missing history or invalid attribution leaves the existing file
intact. Maintenance entries remain in the context but are hidden in the
template, so maintenance-only releases retain dated headings and source links.

After each `develop` → `main` release, fetch and reconcile the new main merge
commit through a working branch and a PR back to `develop`. Do this before the
next changelog update, not with direct protected-branch pushes or a job that
silently synchronizes branches. The changelog workflow deliberately fails if
the stable history is missing. Never move historical tags or republish images
to repair documentation. The [Git-history regression tests](../python/tests/test_changelog_generation.py)
cover missing main-only release merges, annotated tags, maintenance-only releases,
older topics merged after publication, corrupt contexts and repeat generation.

## Context7 documentation publication

[`context7.json`](../context7.json) selects `main` as the default documentation
source even though contributions target `develop`. Merge the configuration and
its referenced documentation through the release PR before refreshing Context7.
A successful merge into `develop` does not establish the effective index source.

After the refresh completes, verify all three independently: the configuration
shows `main`, the default entry under Versions shows `main`, and generated
snippet source URLs point to the intended `main` documentation. Retain the
repository-file configuration source; a dashboard override would otherwise hide
future reviewed JSON changes. Historical release tags may be indexed separately.
See [Context7 configuration](https://context7.com/docs/library-owners) and
[refresh behavior](https://context7.com/docs/library-updates).

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

Both artifacts include `LICENSE`, `NOTICE`, `License-Expression: Apache-2.0`,
`License-File` entries and public project URLs. `python/LICENSE` and `python/NOTICE`
must match the canonical repository files byte for byte; changing license terms requires a separate explicit decision.
These statements describe this source revision. Released v0.4.8 and earlier
artifacts retain their published MPL-2.0 identity. The Apache-2.0 + NOTICE change
was accepted in [#300](https://github.com/alpininsight/capi-provider-ssh/pull/300).
Release notes for the first stable promotion containing it must describe the
transition and verify the source, Python metadata and OCI license together. Never
rewrite a previous release or image to imply it used the new license.
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

The [container delivery guide](../CONTAINER_IMAGES.md) links release notes to
the registry package and explains version tags, immutable pins and linked
artifact records. After publication, release notes should identify the exact
container version and digest. Keep any deployment assertion tied to the
separate consumer evidence below.

| Gate | Evidence to retain | Acceptance |
|---|---|---|
| Reviewed source | PR head, merged commit and exact completed checks | No unresolved required failure or cancellation |
| Published image | OCI index, platform digests, source labels, scan and provenance/SBOM | Correct source for each advertised architecture |
| Consumer review | GitOps PR, CRD/RBAC ordering, immutable pin and resource/placement diff | Registry and platform prerequisites verified |
| Reconciliation | Observed GitOps revision and rendered objects | Desired manifests actually delivered |
| Controller runtime | Actual image IDs, both probes, peers, restart/OOM counters and scheduling | Stable active/standby operation |
| Workload canary | Bootstrap, Node association, deletion and host reuse | Required only when claiming workload lifecycle delivery |

## Preparing a release and a consumer rollout

Prepare a release PR from `develop` to `main` after its dependent fixes and
documentation PRs are accepted. Keep its reviewable description grouped by
behavior, dependencies/security, documentation and license changes. Record the
candidate source and checks, but calculate the final stable version with the
release workflow instead of inferring it from a development image tag.

A draft consumer PR can prepare the rollout procedure and verification gates
before that release exists. It must state the currently deployed image and leave
the deployable pin unchanged until the stable image and its provenance can be
verified. An unresolved placeholder or a development image presented as stable
must not enter an active manifest. Merge the release and accept publication
before filling the consumer's exact stable digest, source revision and VERSION
record. Changes to deployment probes, RBAC or CRDs need their own reviewed diff.

If ArgoCD tracks the consumer's `develop` branch, merging the consumer PR can
start reconciliation immediately. Preparation is not rollout authorization;
retain the platform's separate release/maintenance decision and live acceptance.
An empty CAPI inventory changes the lifecycle risk assessment, but does not
remove controller, registry, API or shared-platform acceptance gates.

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
