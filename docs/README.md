# Documentation

Start with [what the provider does and how to use it](getting-started.md).
This documentation describes the open source provider in the checked-out
revision. Select tested versions from the [support matrix](support-matrix.md)
and use the documentation at your release tag when inspecting an older artifact.

## Understand and evaluate

| Your question | Read next |
|---|---|
| Who uses it, where does it run, and what happens when I add a worker? | [Getting started](getting-started.md) |
| Who owns host preparation, bootstrap and cleanup? | [Architecture and safety](architecture.md) |
| Which versions and features have evidence? | [Support matrix](support-matrix.md) |
| Why is the current CAPI contract v1beta1? | [Contract comparison and migration](capi-contract-migration.md) |
| Is clusterctl installation available? | [Integration status and plan](clusterctl-integration.md) |
| Are hardware plugins shipped? | [Plugin design boundary](plugin-contract.md) and [roadmap](roadmap.md) |

## Install, configure and operate

| Task | Guide |
|---|---|
| Find and pin a released image | [Container delivery](../CONTAINER_IMAGES.md) |
| Install controllers and accept a first workload | [Installation](installation.md), [rollout validation](live-rollout-validation.md) |
| Configure hosts and Machines | [API reference](api-reference.md), [external etcd](external-etcd.md) |
| Review privilege and trust | [Security policy](../SECURITY.md), [RBAC](rbac-requirements.md), [SSH key lifecycle](ssh-key-lifecycle.md) |
| Operate HA, pause, reboot, cleanup and recovery | [Operations](operations.md) |
| Diagnose failures or an empty fleet | [Troubleshooting and FAQ](faq.md) |

## Contribute and maintain

- [Development](../DEVELOPMENT.md), [test portfolio](testing.md), [contributing](../CONTRIBUTING.md).
- [CI and merge acceptance](ci-governance.md), [release process](release-process.md), [maintenance and backports](maintenance-policy.md).
- [P1 validation](p1-validation.md) and [post-merge lessons](merge-reviews.md) are historical product evidence, not live status dashboards.
- [Documentation boundaries and review checklist](documentation-readiness.md).

Operator inventories, actual deployment records, internal governance templates,
service contracts and customer-specific instructions are maintained by the
operator outside this public repository. Open source users do not need access
to a private company repository to understand or install the provider.

Explanations, procedures, reference and historical evidence have different
purposes, following [Diátaxis](https://diataxis.fr/). A procedure states its
prerequisites, expected result, acceptance check and recovery boundary. Claims
about certification, SLAs or optional features require their own evidence.
