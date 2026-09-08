# Documentation and OSS readiness

Reviewed: **2026-09-08**, against develop source
`598b62de93c7289451c681249f91f5d88391b6e0` after documentation PR #255 and
changelog PR #256. Product code matches the v0.4.3 baseline. This assessment
prioritizes work; it is not an OpenSSF badge assessment, certification or SLA.

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
| Participate and report problems | Contribution/DCO guidance, [security policy](../SECURITY.md), [CODEOWNERS](../.github/CODEOWNERS), organization [Code of Conduct](https://github.com/alpininsight/.github/blob/main/CODE_OF_CONDUCT.md) and [issue forms](https://github.com/alpininsight/.github/tree/main/.github/ISSUE_TEMPLATE) | Existing and inherited community material should be reused; the private security intake remains an operational gap |
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
| Before broader external adoption — security operations, already on the [roadmap](roadmap.md#next-decision-gates) | Private vulnerability reporting is still disabled on the review date; no verified alternative private channel or maintenance/backport schedule is published | Repository maintainers establish and verify intake, name triage responsibility and publish an achievable supported-release/security-fix policy. Update SECURITY.md after the operational channel exists |
| Before broader external adoption — distribution metadata, newly verified | The local wheel and source archive build as **0.1.0**, while the current provider release is **v0.4.3**. The wheel has an MPL-2.0 license expression but no `License-File` or `Project-URL` metadata; neither artifact includes a license file. GitHub detects the repository LICENSE as `Other` | Release maintainer defines a traceable package/release version relationship, includes the intended license files and public project URLs, and inspects built artifacts. Review license-text recognition against the declared license without treating an automated classification as a legal conclusion. See [pyproject](../python/pyproject.toml), [LICENSE](../LICENSE) and [PyPA guidance](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) |
| Early correctness work within Q4 [#257](https://github.com/alpininsight/capi-provider-ssh/issues/257) | Machine cleanup changes the legacy `ready` flag without updating an existing `Ready` condition. Pause reporting and transition/generation handling have gaps | Provider/CI maintainers complete lifecycle condition updates and negative tests while preserving ownership and quarantine. This reporting correction can be delivered before the whole contract migration; see [migration step 3](capi-contract-migration.md#work-sequence-and-acceptance) |
| Q4 2026 — [#257](https://github.com/alpininsight/capi-provider-ssh/issues/257) | Legacy CAPI API/reference paths, CRD contract labels, template metadata and v1beta2/upgrade evidence remain open | Provider/CI maintainers complete the six migration steps; release/platform owners retain separate release and consumer acceptance. Keep current HA, receipts and UID fencing |
| Before claiming external host acceptance — existing test gap | Repository-level E2E target variables and secrets are not configured at review. Hosted routing and disposable Kind tests do not establish an approved external endpoint result | Platform/CI owners supply an approved disposable target and independently verified trust through secure configuration, run bootstrap/delete/reuse and retain redacted results. No credentials belong in an issue or documentation |
| Existing [#222](https://github.com/alpininsight/capi-provider-ssh/issues/222) — container hardening | Non-root UID, digest pinning and Python 3.14 exist. The Dockerfile has one runtime stage, retains `uv` and lacks Docker `HEALTHCHECK`; it uses `python:3.14-slim`, not DHI | Release/security owners reconcile the existing checklist with evidence, decide the DHI/minimal-runtime scope and test the resulting image. Kubernetes probes and generic hardening do not establish DHI adoption. See [Dockerfile](../python/Dockerfile) and [Docker DHI](https://docs.docker.com/dhi/) |
| Before offering clusterctl installation — existing packaging gate | The current release has no attached metadata/components bundle; manual reviewed manifests are documented | Release maintainer supplies versioned components, matching metadata/contract labels and install/upgrade tests if clusterctl is offered. This is separate from basic contract conformance |
| Before stronger assurance claims — governance decision | Effective develop rules require eight strict checks but zero approving reviews and do not require code-owner approval. CODEOWNERS identifies a reviewer; its comment alone cannot enforce approval | Repository maintainers decide the required independent-review policy for privileged lifecycle/security changes, align wording and actual rules, and document any chosen exceptions in [CI governance](ci-governance.md) |
| Before fleet/SLA claims — existing operating-envelope gate | No certified fleet-scale, sustained soak, physical failure-domain recovery or RPO/RTO envelope; no shipped Prometheus/SLO package | Platform/provider owners choose representative scale, supported OS/architecture targets, diagnostics/alerts and recovery objectives; retain measured results and exercised runbooks |
| Later capability work — existing plugin/topology plans | No stable plugin API, loader or OOB driver; full ClusterClass and failure-domain support are not established | Resolve versioned interfaces, shared physical identity, cross-protocol fencing and dedicated tests before capability claims. These optional features do not all block the Q4 basic contract migration |

The package findings were reproduced with an offline `uv build --project python`
into a temporary directory and inspection of wheel metadata and both archives;
no generated artifacts were saved in Git. This identifies distribution metadata
gaps, not a different running controller version. The supported delivery path
currently centers on source/manifests and OCI images; this review does not assert
that a PyPI release exists or change the project's license choice.

Security intake setup follows [GitHub's repository configuration guidance](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

## Documentation improvements alongside implementation

| Improvement | Concrete next result | Dependency |
|---|---|---|
| Guided evaluation | Extend the existing disposable Kind procedure with expected object/status transitions and a complete create/delete/reuse walkthrough for a new reader | Can start now on the supported legacy baseline; update with #257 |
| Release-specific usage and upgrades | Make the selected release/source and image relationship easy to follow; provide tested supported upgrade paths and recovery decisions | Publish each actual migration recipe with its tests, not a speculative universal downgrade procedure |
| Reference and example maintenance | Check CRD fields/defaults, environment variables and sample manifests against the implementation; add automatic local-link/anchor checks and bounded external-link checks | Current file hooks check formatting and YAML; they do not provide a documentation link/example-validation lane |
| Support and contribution discovery | Reuse inherited issue forms; make provider versions, CAPI versions, sanitized conditions and reproduction details easy to report; link the chosen support/security policy clearly | Private channel and maintenance commitments require a maintainer decision first |
| Historical planning clarity | Keep resolved issue investigations and old version-target statements explicitly historical, with links to current code and support | #119 is closed; cloud-config handling and periodic Machine reconciliation exist. Do not reopen the old plan merely because its original problem text remains in the archive |
| Navigation and optional publishing | Keep tutorials, procedures, reference and explanation distinct; add hosted version navigation/search when reader needs justify it | A docs site is an accessibility improvement, not a prerequisite for fixing provider behavior |

Use the [Diátaxis model](https://diataxis.fr/) to organize those reader needs.
The contributor changing behavior updates the corresponding documentation and
support claim in the same PR; reviewers check examples and evidence, and the
change owner records post-merge findings. Update this assessment when a gap is
closed, linking its issue/PR and the actual acceptance result.
