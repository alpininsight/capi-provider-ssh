# Documentation and OSS readiness

Updated: **2026-09-08**, for the priority-fix source based on develop
`9ac6495d8a367e15752bf3f62ae26c7a3f960bcb`. The initial audit used the v0.4.3
product baseline after PRs #255/#256. Implementation below describes this
checked-out source; published v0.4.3 artifacts and consumer deployments are not
retroactively changed. This is not an OpenSSF certification or SLA.

The current documentation substantially covers the implemented provider and
states its support boundaries. A wholesale rewrite is not the next dependency.
Improve evaluation and maintenance guidance alongside the work below, and
complete the relevant implementation and evidence before expanding support
claims. A documentation website or more process templates cannot establish a
missing lifecycle, upgrade or recovery result.

## Coverage already present

| Reader need | Current material | Assessment |
|---|---|---|
| Evaluate scope and compatibility | [README](../README.md), [architecture](architecture.md), [support matrix](support-matrix.md), [contract comparison](capi-contract-migration.md) | Current foundation, unsupported capabilities and migration gaps are distinguished |
| Install and operate | [Installation](installation.md), [operations](operations.md), [SSH trust](ssh-key-lifecycle.md), [troubleshooting](faq.md) | Prerequisites, HA, claims, cleanup, pause and recovery boundaries are documented |
| Configure the API | [API reference](api-reference.md), [RBAC](rbac-requirements.md), [structural CRDs](../shared/crds/) | Human-readable reference and authoritative schemas exist; examples and status semantics must evolve with implementation |
| Develop and validate | [Development](../DEVELOPMENT.md), [testing](testing.md), [contributing](../CONTRIBUTING.md) | Locked commands and isolated, transport, Kind and external evidence boundaries exist |
| Release and learn from failures | [Release process](release-process.md), [CI governance](ci-governance.md), [merge reviews](merge-reviews.md) | Source, publication and consumer acceptance are separate gates; historical failures have preventive actions |
| Participate and report problems | Contribution/DCO guidance, [security policy](../SECURITY.md), [CODEOWNERS](../.github/CODEOWNERS), organization [Code of Conduct](https://github.com/alpininsight/.github/blob/main/CODE_OF_CONDUCT.md) and [issue forms](https://github.com/alpininsight/.github/tree/main/.github/ISSUE_TEMPLATE) | Private GitHub intake was enabled and verified on 2026-09-08; supported-release and triage responsibilities are in the maintenance policy |
| Govern a consumer deployment | [Governance index](../.github/docs/README.md), change/continuity templates and [rollout validation](live-rollout-validation.md) | Useful existing process material; consumer owners still supply objectives, approved procedures and actual exercise results |

GitHub's community profile checks file presence. It is not proof that examples
work, release artifacts are complete or operations meet an enterprise objective.
Use [GitHub's community guidance](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)
for discoverability, and [OpenSSF's criteria](https://www.bestpractices.dev/en/criteria/0)
as a source of concrete documentation, interface, release-note and reporting
expectations; neither substitutes for project evidence.

## Provider and project work to prioritize

Only the CAPI migration has the Q4 delivery target approved in this roadmap.
Other rows are recommended priorities or existing gates, not newly promised dates.

| Priority / tracking | Current finding | Work and acceptance owner |
|---|---|---|
| Security operations — intake configured, policy implemented | Private reporting is enabled; repository administrators own triage. The latest stable minor is maintained on a best-effort basis | Follow [SECURITY.md](../SECURITY.md) and [maintenance/backports](maintenance-policy.md); verify the channel and reviewer availability before releases |
| Distribution metadata — implemented in this source | Versioned builds derive package identity from release GitVersion; wheel/sdist include the intended MPL-2.0 license and public URLs. Source without release input is explicitly unversioned | The required artifact gate builds both formats, rebuilds outside Git/version environment and imports the installed package; see [package identity](release-process.md#python-package-identity-and-license-verification). Older published artifacts are unchanged; GitHub license-text recognition remains a separate classification question |
| Lifecycle conditions — implemented before full Q4 migration | Cleanup updates readiness and durable cleanup conditions, pause reports True/False/Unknown, timestamps and observed generations are maintained. A release failure after cleanup cannot erase its success receipt | Stateful regressions and real API/Kind assertions cover the reporting contract; retain final-head CI evidence. Actual v1beta2 and automatic remediation acceptance remain in [#257](https://github.com/alpininsight/capi-provider-ssh/issues/257) |
| Q4 2026 — [#257](https://github.com/alpininsight/capi-provider-ssh/issues/257) | Legacy CAPI API/reference paths, CRD contract labels, template metadata and v1beta2/upgrade evidence remain open | Provider/CI maintainers complete the six migration steps; release/platform owners retain separate release and consumer acceptance. Keep current HA, receipts and UID fencing |
| Before claiming external host acceptance — existing test gap | Repository-level E2E target variables and secrets are not configured at review. Hosted routing and disposable Kind tests do not establish an approved external endpoint result | Platform/CI owners supply an approved disposable target and independently verified trust through secure configuration, run bootstrap/delete/reuse and retain redacted results. No credentials belong in an issue or documentation |
| Existing [#222](https://github.com/alpininsight/capi-provider-ssh/issues/222) — container hardening | Non-root UID, digest pinning and Python 3.14 exist. The Dockerfile has one runtime stage, retains `uv` and lacks Docker `HEALTHCHECK`; it uses `python:3.14-slim`, not DHI | Release/security owners reconcile the existing checklist with evidence, decide the DHI/minimal-runtime scope and test the resulting image. Kubernetes probes and generic hardening do not establish DHI adoption. See [Dockerfile](../python/Dockerfile) and [Docker DHI](https://docs.docker.com/dhi/) |
| Before offering clusterctl installation — existing packaging gate | The current release has no attached metadata/components bundle; manual reviewed manifests are documented | Release maintainer supplies versioned components, matching metadata/contract labels and install/upgrade tests if clusterctl is offered. This is separate from basic contract conformance |
| Governance — temporary single-maintainer exception | Peter Rosemann (`@dkdndes`), Alpin Insight Solutions, is the valid CODEOWNER. Required independent/CODEOWNER/last-push approval is temporarily disabled; all eight strict checks, PRs, stale-review dismissal and resolved threads remain required | Restore the [standard policy](maintenance-policy.md#independent-review-and-continuity) when a second eligible maintainer is onboarded, not during September 2026. Verify base-branch owners and effective rules; this exception does not establish independent assurance |
| Before fleet/SLA claims — existing operating-envelope gate | No certified fleet-scale, sustained soak, physical failure-domain recovery or RPO/RTO envelope; no shipped Prometheus/SLO package | Platform/provider owners choose representative scale, supported OS/architecture targets, diagnostics/alerts and recovery objectives; retain measured results and exercised runbooks |
| Later capability work — existing plugin/topology plans | No stable plugin API, loader or OOB driver; full ClusterClass and failure-domain support are not established | Resolve versioned interfaces, shared physical identity, cross-protocol fencing and dedicated tests before capability claims. These optional features do not all block the Q4 basic contract migration |

The initial package audit reproduced the old 0.1.0 version and missing license
files. The new [artifact check](../python/scripts/check_package.py) validates
stable and prerelease identities, both archives and an isolated installed import
using temporary output. No build artifacts are committed. The supported delivery
path remains source/manifests and OCI images; this does not assert a PyPI release
or change the project's license choice.

Security intake setup follows [GitHub's repository configuration guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

## Documentation improvements alongside implementation

| Improvement | Concrete next result | Dependency |
|---|---|---|
| Guided evaluation | Extend the existing disposable Kind procedure with expected object/status transitions and a complete create/delete/reuse walkthrough for a new reader | Can start now on the supported legacy baseline; update with #257 |
| Release-specific usage and upgrades | Make the selected release/source and image relationship easy to follow; provide tested supported upgrade paths and recovery decisions | Publish each actual migration recipe with its tests, not a speculative universal downgrade procedure |
| Reference and example maintenance | Check CRD fields/defaults, environment variables and sample manifests against the implementation; add automatic local-link/anchor checks and bounded external-link checks | Current file hooks check formatting and YAML; they do not provide a documentation link/example-validation lane |
| Support and contribution discovery | Reuse inherited issue forms; include provider/CAPI versions, sanitized conditions and reproduction details, with clear security/support links | Intake and maintenance policy now exist; review response and release evidence remains ongoing maintainer work |
| Historical planning clarity | Keep resolved issue investigations and old version-target statements explicitly historical, with links to current code and support | #119 is closed; cloud-config handling and periodic Machine reconciliation exist. Do not reopen the old plan merely because its original problem text remains in the archive |
| Navigation and optional publishing | Keep tutorials, procedures, reference and explanation distinct; add hosted version navigation/search when reader needs justify it | A docs site is an accessibility improvement, not a prerequisite for fixing provider behavior |

Use the [Diátaxis model](https://diataxis.fr/) to organize those reader needs.
The contributor changing behavior updates the corresponding documentation and
support claim in the same PR; reviewers check examples and evidence, and the
change owner records post-merge findings. Update this assessment when a gap is
closed, linking its issue/PR and the actual acceptance result.
