# Documentation

This documentation describes the Python provider in the checked-out revision.
Use the [support matrix](support-matrix.md) for tested versions and known limits;
use immutable release/source references when reviewing an older deployment.

## Evaluation and reference

| Document | Decision it supports |
|---|---|
| [Architecture](architecture.md) | Ownership, CAPI boundaries and safety model |
| [Support matrix](support-matrix.md) | Tested combinations, contract level and evidence gaps |
| [API and configuration](api-reference.md) | Resource fields, defaults and controller settings |
| [RBAC](rbac-requirements.md) | Actual permissions and trust scope |
| [External etcd](external-etcd.md) | Certificate and kubeadm configuration contract |
| [Plugin design](plugin-contract.md) | Required extension boundaries; no implemented plugin API |

## Operator procedures

| Document | Outcome |
|---|---|
| [Installation](installation.md) | Reviewed manifests, credentials, placement and acceptance |
| [Operations](operations.md) | HA, pause, cleanup, reboot and recovery decisions |
| [SSH key lifecycle](ssh-key-lifecycle.md) | Independently verified trust and credential rotation |
| [Troubleshooting](faq.md) | Symptom, diagnostic evidence and next safe action |
| [Release process](release-process.md) | Source-to-image-to-GitOps acceptance |
| [Rollout validation](live-rollout-validation.md) | Canary lifecycle and teardown evidence |
| [Security policy](../SECURITY.md) | Reporting channel, privilege boundary and evidence handling |

## Contributor material and historical records

- [Development](../DEVELOPMENT.md), [test portfolio](testing.md) and [contribution guide](../CONTRIBUTING.md).
- [CI routing and merge acceptance](ci-governance.md) defines required checks, changelog automation and external SSH configuration.
- [P1 validation record](p1-validation.md) and [post-merge lessons](merge-reviews.md) are dated historical evidence, not live status dashboards.
- [Roadmap](roadmap.md) and its research notes describe proposals, not supported features or release commitments.
- [DNS cutover](dns-cutover.md) is an environment-level procedure outside the provider API.
- [Former Flux guide](flux-rollout.md) redirects to the current rollout documentation.

## Documentation maintenance

The contributor changing behavior owns the corresponding documentation update;
the PR reviewer checks commands, examples, failure/recovery semantics and support
claims against code, CRDs and actual test evidence. Platform maintainers own
private deployment records. Date any deployment observation and retain detailed
host/account evidence in the access-controlled environment repository.

Keep explanations, reference, procedures and evidence distinguishable, following
the [Diátaxis documentation model](https://diataxis.fr/). Each procedure must state
its prerequisites, intended outcome, acceptance check and recovery boundary.
No document may imply certification, an SLA or plugin support without an
explicit supporting contract and validation record.
